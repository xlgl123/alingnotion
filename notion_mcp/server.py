from __future__ import annotations

import logging
from typing import Any, Callable

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .auth import PrivateMCPMiddleware
from .errors import AppError
from .notion_client import NotionClient
from .services import ToolService
from .settings import Settings


logger = logging.getLogger("notion_mcp")
ClientFactory = Callable[[], NotionClient]


def create_mcp(settings: Settings, *, service: ToolService | None = None, client_factory: ClientFactory | None = None) -> FastMCP:
    service = service or ToolService(settings)
    client_factory = client_factory or (
        lambda: NotionClient(
            settings.notion_token,
            version=settings.notion_version,
            timeout=settings.request_timeout_seconds,
        )
    )
    mcp = FastMCP(
        "Aling Notion",
        instructions=(
            "使用者的私有 Notion 服务。写日记优先使用 write_diary；明日待办必须放在 content 中。"
            "任何全文替换必须显式确认，不能创建重复日期日记。"
        ),
        json_response=True,
        stateless_http=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "localhost",
                "localhost:*",
                "127.0.0.1",
                "127.0.0.1:*",
                settings.public_host,
                f"{settings.public_host}:*",
            ],
            allowed_origins=list(settings.allowed_origins),
        ),
    )

    async def invoke(method: str, **kwargs: Any) -> dict[str, Any]:
        client: NotionClient | None = None
        try:
            async with client_factory() as client:
                return await getattr(service, method)(client, **kwargs)
        except AppError as exc:
            result = exc.as_result()
            result["notion_request_ids"] = client.request_ids() if client is not None else []
            return result
        except Exception:
            logger.exception("MCP tool failed: %s", method)
            return {
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "服务内部错误；没有把密钥或请求内容写入返回值",
                    "retryable": False,
                    "details": {},
                },
                "warnings": [],
                "notion_request_ids": client.request_ids() if client is not None else [],
            }

    @mcp.tool(description="一步写入使用者的日记属性与完整正文；明日待办属于 content。")
    async def write_diary(
        content: str,
        date: str | None = None,
        mood: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        sweet_moments: str | None = None,
        place: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        return await invoke(
            "write_diary",
            content=content,
            date=date,
            mood=mood,
            title=title,
            summary=summary,
            sweet_moments=sweet_moments,
            place=place,
        )

    @mcp.tool(description="全文搜索已授权的日记和记忆页面，支持正文命中摘要。")
    async def search_memory(
        query: str,
        scope: str = "all",
        database_id: str | None = None,
        limit: int = 10,
        include_content: bool = False,
    ) -> dict[str, Any]:
        return await invoke(
            "search_memory",
            query=query,
            scope=scope,
            database_id=database_id,
            limit=limit,
            include_content=include_content,
        )

    @mcp.tool(description="通过页面 ID 或 Notion URL 读取页面属性与完整正文。")
    async def read_page(page: str, format: str = "markdown") -> dict[str, Any]:
        return await invoke("read_page", page=page, format=format)

    @mcp.tool(description="按上海自然日读取最近 N 天的日记列表和正文。")
    async def fetch_recent_diary(days: int = 7, include_content: bool = True) -> dict[str, Any]:
        return await invoke("fetch_recent_diary", days=days, include_content=include_content)

    @mcp.tool(description="在任意已授权 Page 或 Data Source 下创建页面并写入 Markdown 正文。")
    async def create_page(
        parent: str,
        title: str,
        properties: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        return await invoke("create_page", parent=parent, title=title, properties=properties, content=content)

    @mcp.tool(description="修改页面属性、精确修改 Block，或经确认后替换全文。")
    async def update_page(
        page: str,
        properties: dict[str, Any] | None = None,
        content: str | None = None,
        content_mode: str = "none",
        block_edits: list[dict[str, Any]] | None = None,
        confirm_replace: bool = False,
        expected_last_edited_time: str | None = None,
    ) -> dict[str, Any]:
        return await invoke(
            "update_page",
            page=page,
            properties=properties,
            content=content,
            content_mode=content_mode,
            block_edits=block_edits,
            confirm_replace=confirm_replace,
            expected_last_edited_time=expected_last_edited_time,
        )

    @mcp.tool(description="查询任意已授权 Database 或 Data Source，支持筛选、排序与分页。")
    async def query_database(
        database: str,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        limit: int = 50,
        cursor: str | None = None,
        include_content: bool = False,
    ) -> dict[str, Any]:
        return await invoke(
            "query_database",
            database=database,
            filter=filter,
            sorts=sorts,
            limit=limit,
            cursor=cursor,
            include_content=include_content,
        )

    @mcp.tool(description="向已有页面末尾追加 Markdown 内容，不覆盖原正文。")
    async def append_content(page: str, content: str) -> dict[str, Any]:
        return await invoke("append_content", page=page, content=content)

    return mcp


def create_app(
    settings: Settings | None = None,
    *,
    service: ToolService | None = None,
    client_factory: ClientFactory | None = None,
) -> PrivateMCPMiddleware:
    settings = settings or Settings.from_env()
    mcp = create_mcp(settings, service=service, client_factory=client_factory)
    return PrivateMCPMiddleware(
        mcp.streamable_http_app(),
        access_token=settings.mcp_access_token,
        public_host=settings.public_host,
        allowed_origins=settings.allowed_origins,
        unauthenticated_proxy_networks=settings.claude_unauthenticated_cidrs,
        allow_unauthenticated=settings.allow_unauthenticated,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
