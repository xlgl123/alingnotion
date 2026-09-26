from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .errors import AppError, NotionAPIError
from .ids import normalize_notion_id


class NotionClient:
    def __init__(
        self,
        token: str,
        *,
        version: str = "2026-03-11",
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token = token
        self._version = version
        self._timeout = timeout
        self._client = http_client
        self._owns_client = http_client is None
        self._request_ids: list[str] = []

    async def __aenter__(self) -> "NotionClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://api.notion.com",
                timeout=httpx.Timeout(self._timeout, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Notion-Version": self._version,
                    "Content-Type": "application/json",
                    "User-Agent": "aling-notion-mcp/0.1",
                },
            )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def request_ids(self) -> list[str]:
        return list(self._request_ids)

    def _record_request_id(self, value: str | None) -> None:
        if value:
            self._request_ids.append(value)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._client is None:
            raise RuntimeError("NotionClient 必须在 async with 中使用")

        for attempt in range(4):
            try:
                response = await self._client.request(method, path, json=json, params=params)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 3:
                    raise AppError("NOTION_UNAVAILABLE", "Notion API 网络请求失败", retryable=True) from exc
                await asyncio.sleep(0.5 * (2**attempt))
                continue

            payload: dict[str, Any]
            try:
                payload = response.json()
            except ValueError:
                payload = {}

            request_id = response.headers.get("x-notion-request-id") or payload.get("request_id")
            self._record_request_id(request_id)

            if response.status_code < 400:
                return payload

            notion_code = str(payload.get("code") or "unknown_error")
            message = str(payload.get("message") or "Notion API 请求失败")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 3:
                    retry_after = response.headers.get("retry-after")
                    try:
                        delay = float(retry_after) if retry_after else 0.5 * (2**attempt)
                    except ValueError:
                        delay = 0.5 * (2**attempt)
                    await asyncio.sleep(min(max(delay, 0.1), 10.0))
                    continue

            code_map = {
                400: "INVALID_ARGUMENT",
                401: "UNAUTHORIZED",
                403: "NOTION_FORBIDDEN",
                404: "NOT_FOUND",
                409: "EDIT_CONFLICT",
                429: "RATE_LIMITED",
            }
            safe_message = {
                401: "Notion 密钥无效或已失效",
                403: "Notion 集成没有访问或修改目标内容的权限",
                404: "目标 Notion 页面、Database 或 Data Source 不存在，或尚未共享给集成",
                429: "Notion API 请求频率过高，请稍后重试",
            }.get(response.status_code, message[:500])
            raise NotionAPIError(
                code=code_map.get(response.status_code, "NOTION_UNAVAILABLE"),
                message=safe_message,
                retryable=response.status_code == 429 or response.status_code >= 500,
                details={"notion_code": notion_code},
                status=response.status_code,
                notion_code=notion_code,
                request_id=request_id,
            )

        raise AppError("NOTION_UNAVAILABLE", "Notion API 暂时不可用", retryable=True)

    async def retrieve_page(self, page: str) -> dict[str, Any]:
        return await self.request("GET", f"/v1/pages/{normalize_notion_id(page)}")

    async def retrieve_block(self, block: str) -> dict[str, Any]:
        return await self.request("GET", f"/v1/blocks/{normalize_notion_id(block)}")

    async def retrieve_database(self, database: str) -> dict[str, Any]:
        return await self.request("GET", f"/v1/databases/{normalize_notion_id(database)}")

    async def retrieve_data_source(self, data_source: str) -> dict[str, Any]:
        return await self.request("GET", f"/v1/data_sources/{normalize_notion_id(data_source)}")

    async def resolve_resource(self, value: str, allowed: tuple[str, ...] = ("data_source", "database", "page")) -> tuple[str, dict[str, Any]]:
        resource_id = normalize_notion_id(value)
        methods = {
            "data_source": self.retrieve_data_source,
            "database": self.retrieve_database,
            "page": self.retrieve_page,
        }
        last_error: AppError | None = None
        for kind in allowed:
            try:
                return kind, await methods[kind](resource_id)
            except NotionAPIError as exc:
                if exc.status != 404:
                    raise
                last_error = exc
        raise last_error or AppError("NOT_FOUND", "无法识别目标 Notion 资源")

    async def block_children(self, block: str, *, recursive: bool = True) -> list[dict[str, Any]]:
        block_id = normalize_notion_id(block)
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            payload = await self.request("GET", f"/v1/blocks/{block_id}/children", params=params)
            batch = list(payload.get("results") or [])
            if recursive:
                for child in batch:
                    if child.get("has_children"):
                        child["children"] = await self.block_children(child["id"], recursive=True)
            results.extend(batch)
            if not payload.get("has_more"):
                break
            cursor = payload.get("next_cursor")
            if not cursor:
                break
        return results

    async def search_pages(self, *, query: str | None = None, limit: int = 200) -> tuple[list[dict[str, Any]], bool]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        has_more = False
        while len(results) < limit:
            body: dict[str, Any] = {
                "page_size": min(100, limit - len(results)),
                "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            }
            if query:
                body["query"] = query
            if cursor:
                body["start_cursor"] = cursor
            payload = await self.request("POST", "/v1/search", json=body)
            for item in payload.get("results") or []:
                if item.get("object") == "page":
                    results.append(item)
                    if len(results) >= limit:
                        break
            has_more = bool(payload.get("has_more"))
            cursor = payload.get("next_cursor")
            if not has_more or not cursor:
                break
        return results, has_more

    async def query_data_source(
        self,
        data_source: str,
        *,
        filter_: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None, bool]:
        data_source_id = normalize_notion_id(data_source)
        results: list[dict[str, Any]] = []
        next_cursor = cursor
        has_more = False
        while len(results) < limit:
            body: dict[str, Any] = {"page_size": min(100, limit - len(results))}
            if filter_:
                body["filter"] = filter_
            if sorts:
                body["sorts"] = sorts
            if next_cursor:
                body["start_cursor"] = next_cursor
            payload = await self.request("POST", f"/v1/data_sources/{data_source_id}/query", json=body)
            results.extend(payload.get("results") or [])
            has_more = bool(payload.get("has_more"))
            next_cursor = payload.get("next_cursor")
            if not has_more or not next_cursor:
                break
        return results[:limit], next_cursor, has_more

    async def create_page(self, *, parent: dict[str, Any], properties: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/v1/pages", json={"parent": parent, "properties": properties})

    async def update_page(self, page: str, *, properties: dict[str, Any] | None = None, erase_content: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if properties:
            body["properties"] = properties
        if erase_content:
            body["erase_content"] = True
        return await self.request("PATCH", f"/v1/pages/{normalize_notion_id(page)}", json=body)

    async def append_blocks(self, page: str, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        page_id = normalize_notion_id(page)
        appended: list[dict[str, Any]] = []
        for offset in range(0, len(blocks), 100):
            batch = blocks[offset : offset + 100]
            payload = await self.request(
                "PATCH",
                f"/v1/blocks/{page_id}/children",
                json={"children": batch, "position": {"type": "end"}},
            )
            appended.extend(payload.get("results") or [])
        return appended

    async def update_block(self, block: str, *, text: str | None = None, checked: bool | None = None) -> dict[str, Any]:
        block_obj = await self.retrieve_block(block)
        block_type = str(block_obj.get("type") or "")
        if block_type not in {
            "paragraph",
            "heading_1",
            "heading_2",
            "heading_3",
            "bulleted_list_item",
            "numbered_list_item",
            "quote",
            "to_do",
            "code",
        }:
            raise AppError("INVALID_ARGUMENT", f"暂不支持修改 {block_type} 类型的 Block")
        payload = dict(block_obj.get(block_type) or {})
        if text is not None:
            from .markdown_blocks import rich_text

            payload["rich_text"] = rich_text(text)
        if checked is not None:
            if block_type != "to_do":
                raise AppError("INVALID_ARGUMENT", "checked 只能用于 to_do Block")
            payload["checked"] = checked
        return await self.request(
            "PATCH", f"/v1/blocks/{normalize_notion_id(block)}", json={block_type: payload}
        )
