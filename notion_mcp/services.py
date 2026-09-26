from __future__ import annotations

import asyncio
from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .audit import record as audit_record
from .errors import AppError, invalid_argument, ok_result
from .ids import normalize_notion_id
from .markdown_blocks import blocks_to_markdown, markdown_to_blocks, rich_text
from .notion_client import NotionClient
from .properties import encode_properties, page_title, properties_text, public_properties
from .search_index import IndexedPage, SearchIndex
from .settings import Settings


DIARY_MOODS = ("开心", "感动", "兴奋", "温柔", "想念")


def _parent_id(page: dict[str, Any]) -> str:
    parent = page.get("parent") or {}
    for key in ("data_source_id", "database_id", "page_id", "workspace"):
        value = parent.get(key)
        if value:
            return str(value)
    return ""


def _diary_date(page: dict[str, Any]) -> str | None:
    value = (page.get("properties") or {}).get("日期 1") or {}
    raw = value.get("date")
    return raw.get("start") if isinstance(raw, dict) else None


def _public_page(page: dict[str, Any], *, content: str | None = None, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {
        "id": page.get("id"),
        "url": page.get("url"),
        "title": page_title(page),
        "parent": page.get("parent"),
        "properties": public_properties(page.get("properties") or {}),
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
        "in_trash": bool(page.get("in_trash", False)),
    }
    if content is not None:
        output["content"] = content
    if blocks is not None:
        output["blocks"] = blocks
    return output


class ToolService:
    def __init__(self, settings: Settings, search_index: SearchIndex | None = None) -> None:
        self.settings = settings
        self.search_index = search_index or SearchIndex(settings.search_db_path)

    async def _index_page(self, client: NotionClient, page: dict[str, Any], blocks: list[dict[str, Any]] | None = None) -> None:
        if blocks is None:
            blocks = await client.block_children(page["id"])
        indexed = IndexedPage(
            page_id=page["id"],
            title=page_title(page),
            properties_text=properties_text(page.get("properties") or {}),
            content=blocks_to_markdown(blocks),
            url=str(page.get("url") or ""),
            parent_id=_parent_id(page),
            last_edited_time=str(page.get("last_edited_time") or ""),
            diary_date=_diary_date(page),
        )
        await asyncio.to_thread(self.search_index.upsert, indexed)

    async def _resolve_data_source(self, client: NotionClient, value: str) -> tuple[dict[str, Any], list[str]]:
        kind, resource = await client.resolve_resource(value, ("data_source", "database"))
        warnings: list[str] = []
        if kind == "data_source":
            return resource, warnings
        sources = resource.get("data_sources") or []
        if len(sources) != 1:
            raise AppError(
                "INVALID_ARGUMENT",
                "该 Database 包含多个 Data Source，必须明确传入目标 Data Source ID",
                details={"data_sources": [{"id": item.get("id"), "name": item.get("name")} for item in sources]},
            )
        source = await client.retrieve_data_source(sources[0]["id"])
        warnings.append("输入是 Database 容器，已自动选择其中唯一的 Data Source")
        return source, warnings

    @staticmethod
    def _parse_date(value: str | None, timezone: str) -> date_type:
        if value is None:
            return datetime.now(ZoneInfo(timezone)).date()
        try:
            return date_type.fromisoformat(value)
        except ValueError as exc:
            raise invalid_argument("date 必须使用 YYYY-MM-DD 格式", date=value) from exc

    async def write_diary(
        self,
        client: NotionClient,
        *,
        content: str,
        date: str | None = None,
        mood: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        sweet_moments: str | None = None,
        place: Any = None,
    ) -> dict[str, Any]:
        if place is not None:
            raise AppError(
                "UNSUPPORTED_PROPERTY",
                "Notion 官方 API 2026-03-11 暂不支持写入 Place 属性；本次未创建页面",
            )
        diary_date = self._parse_date(date, self.settings.timezone)
        if mood is not None and mood not in DIARY_MOODS:
            raise invalid_argument("mood 必须使用日记库已有选项", allowed=list(DIARY_MOODS))
        try:
            blocks = markdown_to_blocks(content)
        except ValueError as exc:
            raise invalid_argument(str(exc)) from exc

        existing, _, _ = await client.query_data_source(
            self.settings.diary_data_source_id,
            filter_={"property": "日期 1", "date": {"equals": diary_date.isoformat()}},
            limit=2,
        )
        if existing:
            raise AppError(
                "DUPLICATE_DIARY",
                f"{diary_date.isoformat()} 已存在日记，未创建重复页面",
                details={"page_id": existing[0].get("id"), "url": existing[0].get("url")},
            )

        source = await client.retrieve_data_source(self.settings.diary_data_source_id)
        schema = source.get("properties") or {}
        values: dict[str, Any] = {
            "日期": title or f"{diary_date.year}年{diary_date.month}月{diary_date.day}日",
            "日期 1": diary_date.isoformat(),
        }
        if mood is not None:
            values["心情"] = mood
        if summary is not None:
            values["今天做了什么"] = summary
        if sweet_moments is not None:
            values["重要互动"] = sweet_moments
        properties = encode_properties(schema, values)

        page = await client.create_page(
            parent={"type": "data_source_id", "data_source_id": self.settings.diary_data_source_id},
            properties=properties,
        )
        try:
            appended = await client.append_blocks(page["id"], blocks)
        except AppError as exc:
            audit_record("write_diary_partial", page_id=page["id"], cause=exc.code)
            return {
                "ok": False,
                "error": {
                    "code": "PARTIAL_WRITE",
                    "message": "日记页面属性已创建，但正文写入未完成",
                    "retryable": exc.retryable,
                    "details": {
                        "page_id": page.get("id"),
                        "url": page.get("url"),
                        "cause": exc.code,
                    },
                },
                "warnings": ["请使用返回的 page_id 补写正文，不能重新创建同一天日记"],
                "notion_request_ids": client.request_ids(),
            }

        verified_page = await client.retrieve_page(page["id"])
        verified_blocks = await client.block_children(page["id"])
        warnings: list[str] = []
        if len(verified_blocks) != len(blocks):
            raise AppError(
                "PARTIAL_WRITE",
                "日记正文回验区块数量不一致",
                details={"expected": len(blocks), "actual": len(verified_blocks), "page_id": page["id"]},
            )
        try:
            await self._index_page(client, verified_page, verified_blocks)
        except Exception:
            warnings.append("日记已完整写入，但本地搜索索引刷新失败；下次搜索会重建")
        audit_record(
            "write_diary",
            page_id=page["id"],
            diary_date=diary_date.isoformat(),
            blocks_written=len(appended),
        )
        return ok_result(
            {
                "page_id": page["id"],
                "url": page.get("url"),
                "date": diary_date.isoformat(),
                "blocks_written": len(appended),
                "verified": True,
            },
            warnings=warnings,
            request_ids=client.request_ids(),
        )

    async def read_page(self, client: NotionClient, *, page: str, format: str = "markdown") -> dict[str, Any]:
        if format not in {"markdown", "structured"}:
            raise invalid_argument("format 只支持 markdown 或 structured")
        page_obj = await client.retrieve_page(page)
        blocks = await client.block_children(page_obj["id"])
        if format == "markdown":
            data = _public_page(page_obj, content=blocks_to_markdown(blocks))
        else:
            data = _public_page(page_obj, blocks=blocks)
        return ok_result(data, request_ids=client.request_ids())

    async def fetch_recent_diary(self, client: NotionClient, *, days: int = 7, include_content: bool = True) -> dict[str, Any]:
        if not 1 <= days <= 365:
            raise invalid_argument("days 必须在 1 到 365 之间")
        today = datetime.now(ZoneInfo(self.settings.timezone)).date()
        start = today - timedelta(days=days - 1)
        pages, _, _ = await client.query_data_source(
            self.settings.diary_data_source_id,
            filter_={"property": "日期 1", "date": {"on_or_after": start.isoformat()}},
            sorts=[{"property": "日期 1", "direction": "descending"}],
            limit=min(days * 3, 500),
        )
        output: list[dict[str, Any]] = []
        for page in pages:
            if include_content:
                blocks = await client.block_children(page["id"])
                output.append(_public_page(page, content=blocks_to_markdown(blocks)))
            else:
                output.append(_public_page(page))
        return ok_result(
            {"days": days, "start_date": start.isoformat(), "end_date": today.isoformat(), "count": len(output), "items": output},
            request_ids=client.request_ids(),
        )

    async def create_page(
        self,
        client: NotionClient,
        *,
        parent: str,
        title: str,
        properties: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        if not title.strip():
            raise invalid_argument("title 不能为空")
        blocks: list[dict[str, Any]] = []
        if content is not None:
            try:
                blocks = markdown_to_blocks(content)
            except ValueError as exc:
                raise invalid_argument(str(exc)) from exc

        kind, resource = await client.resolve_resource(parent)
        warnings: list[str] = []
        values = dict(properties or {})
        if kind == "page":
            if values:
                raise AppError("SCHEMA_MISMATCH", "普通 Page 下的子页面只支持 title 属性")
            parent_body = {"type": "page_id", "page_id": resource["id"]}
            encoded = {"title": {"type": "title", "title": rich_text(title)}}
        else:
            if kind == "database":
                sources = resource.get("data_sources") or []
                if len(sources) != 1:
                    raise AppError(
                        "INVALID_ARGUMENT",
                        "该 Database 包含多个 Data Source，必须直接传入目标 Data Source ID",
                        details={"data_sources": sources},
                    )
                resource = await client.retrieve_data_source(sources[0]["id"])
                warnings.append("已自动选择 Database 中唯一的 Data Source")
            schema = resource.get("properties") or {}
            title_names = [name for name, prop in schema.items() if prop.get("type") == "title"]
            if not title_names:
                raise AppError("SCHEMA_MISMATCH", "目标 Data Source 没有 title 字段")
            values.setdefault(title_names[0], title)
            encoded = encode_properties(schema, values)
            parent_body = {"type": "data_source_id", "data_source_id": resource["id"]}

        page_obj = await client.create_page(parent=parent_body, properties=encoded)
        try:
            appended = await client.append_blocks(page_obj["id"], blocks) if blocks else []
        except AppError as exc:
            audit_record("create_page_partial", page_id=page_obj["id"], cause=exc.code)
            return {
                "ok": False,
                "error": {
                    "code": "PARTIAL_WRITE",
                    "message": "页面已创建，但正文写入未完成",
                    "retryable": exc.retryable,
                    "details": {"page_id": page_obj["id"], "url": page_obj.get("url"), "cause": exc.code},
                },
                "warnings": warnings,
                "notion_request_ids": client.request_ids(),
            }
        verified = await client.retrieve_page(page_obj["id"])
        verified_blocks = await client.block_children(page_obj["id"])
        try:
            await self._index_page(client, verified, verified_blocks)
        except Exception:
            warnings.append("页面已创建，但本地搜索索引刷新失败")
        audit_record("create_page", page_id=page_obj["id"], blocks_written=len(appended))
        return ok_result(
            {"page_id": page_obj["id"], "url": page_obj.get("url"), "blocks_written": len(appended)},
            warnings=warnings,
            request_ids=client.request_ids(),
        )

    async def append_content(self, client: NotionClient, *, page: str, content: str) -> dict[str, Any]:
        try:
            blocks = markdown_to_blocks(content)
        except ValueError as exc:
            raise invalid_argument(str(exc)) from exc
        page_obj = await client.retrieve_page(page)
        appended = await client.append_blocks(page_obj["id"], blocks)
        final_page = await client.retrieve_page(page_obj["id"])
        final_blocks = await client.block_children(page_obj["id"])
        warnings: list[str] = []
        try:
            await self._index_page(client, final_page, final_blocks)
        except Exception:
            warnings.append("内容已追加，但本地搜索索引刷新失败")
        audit_record("append_content", page_id=page_obj["id"], blocks_appended=len(appended))
        return ok_result(
            {"page_id": page_obj["id"], "url": page_obj.get("url"), "blocks_appended": len(appended)},
            warnings=warnings,
            request_ids=client.request_ids(),
        )

    async def update_page(
        self,
        client: NotionClient,
        *,
        page: str,
        properties: dict[str, Any] | None = None,
        content: str | None = None,
        content_mode: str = "none",
        block_edits: list[dict[str, Any]] | None = None,
        confirm_replace: bool = False,
        expected_last_edited_time: str | None = None,
    ) -> dict[str, Any]:
        if content_mode not in {"none", "replace"}:
            raise invalid_argument("content_mode 只支持 none 或 replace")
        if content_mode == "replace" and not confirm_replace:
            raise AppError("INVALID_ARGUMENT", "全文替换必须显式设置 confirm_replace=true")
        if content_mode == "replace" and content is None:
            raise invalid_argument("全文替换时 content 不能为空")
        if content_mode == "none" and content is not None:
            raise invalid_argument("传入 content 时必须设置 content_mode=replace；追加内容请使用 append_content")
        if content_mode == "replace" and block_edits:
            raise invalid_argument("全文替换不能与 block_edits 同时执行")

        replacement_blocks: list[dict[str, Any]] | None = None
        if content_mode == "replace":
            try:
                replacement_blocks = markdown_to_blocks(content or "")
            except ValueError as exc:
                raise invalid_argument(str(exc)) from exc

        initial = await client.retrieve_page(page)
        initial_edit_time = str(initial.get("last_edited_time") or "")
        if expected_last_edited_time and expected_last_edited_time != initial_edit_time:
            raise AppError(
                "EDIT_CONFLICT",
                "页面在调用前已被修改，拒绝覆盖",
                details={"expected": expected_last_edited_time, "actual": initial_edit_time},
            )

        encoded_properties: dict[str, Any] = {}
        if properties:
            parent = initial.get("parent") or {}
            if parent.get("type") == "data_source_id":
                source = await client.retrieve_data_source(parent["data_source_id"])
                encoded_properties = encode_properties(source.get("properties") or {}, properties)
            else:
                if set(properties) != {"title"}:
                    raise AppError("SCHEMA_MISMATCH", "普通 Page 只支持修改 title 属性")
                encoded_properties = {"title": {"type": "title", "title": rich_text(str(properties["title"]))}}

        actions: list[str] = []
        try:
            if replacement_blocks is not None:
                current = await client.retrieve_page(initial["id"])
                if str(current.get("last_edited_time") or "") != initial_edit_time:
                    raise AppError("EDIT_CONFLICT", "页面在准备替换正文时被其他操作修改，已停止")
                await client.update_page(initial["id"], erase_content=True)
                actions.append("erased_old_content")
                await client.append_blocks(initial["id"], replacement_blocks)
                actions.append("wrote_new_content")
            if encoded_properties:
                await client.update_page(initial["id"], properties=encoded_properties)
                actions.append("updated_properties")
            for edit in block_edits or []:
                block_id = edit.get("block_id")
                if not block_id:
                    raise invalid_argument("每个 block_edits 项都必须包含 block_id")
                if "text" not in edit and "checked" not in edit:
                    raise invalid_argument("block_edits 至少包含 text 或 checked")
                await client.update_block(block_id, text=edit.get("text"), checked=edit.get("checked"))
                actions.append(f"updated_block:{normalize_notion_id(block_id)}")
        except AppError as exc:
            if actions:
                audit_record(
                    "update_page_partial",
                    page_id=initial["id"],
                    actions=",".join(actions),
                    cause=exc.code,
                )
                return {
                    "ok": False,
                    "error": {
                        "code": "PARTIAL_WRITE",
                        "message": "页面修改只完成了一部分",
                        "retryable": exc.retryable,
                        "details": {"page_id": initial["id"], "completed_actions": actions, "cause": exc.code},
                    },
                    "warnings": [],
                    "notion_request_ids": client.request_ids(),
                }
            raise

        final_page = await client.retrieve_page(initial["id"])
        final_blocks = await client.block_children(initial["id"])
        warnings: list[str] = []
        try:
            await self._index_page(client, final_page, final_blocks)
        except Exception:
            warnings.append("页面修改已完成，但本地搜索索引刷新失败")
        audit_record("update_page", page_id=initial["id"], actions=",".join(actions))
        return ok_result(
            {
                "page_id": initial["id"],
                "url": final_page.get("url"),
                "actions": actions,
                "last_edited_time": final_page.get("last_edited_time"),
            },
            warnings=warnings,
            request_ids=client.request_ids(),
        )

    async def query_database(
        self,
        client: NotionClient,
        *,
        database: str,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        limit: int = 50,
        cursor: str | None = None,
        include_content: bool = False,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise invalid_argument("limit 必须在 1 到 500 之间")
        source, warnings = await self._resolve_data_source(client, database)
        pages, next_cursor, has_more = await client.query_data_source(
            source["id"], filter_=filter, sorts=sorts, limit=limit, cursor=cursor
        )
        items: list[dict[str, Any]] = []
        for page in pages:
            if include_content:
                blocks = await client.block_children(page["id"])
                items.append(_public_page(page, content=blocks_to_markdown(blocks)))
            else:
                items.append(_public_page(page))
        schema = {
            name: {"id": prop.get("id"), "type": prop.get("type"), "description": prop.get("description")}
            for name, prop in (source.get("properties") or {}).items()
        }
        return ok_result(
            {
                "data_source_id": source["id"],
                "schema": schema,
                "count": len(items),
                "items": items,
                "next_cursor": next_cursor,
                "has_more": has_more,
            },
            warnings=warnings,
            request_ids=client.request_ids(),
        )

    async def _refresh_search_index(
        self,
        client: NotionClient,
        *,
        scope: str,
        database_id: str | None,
    ) -> list[str]:
        warnings: list[str] = []
        parent_filter: str | None = None
        if scope == "diary":
            pages, _, has_more = await client.query_data_source(
                self.settings.diary_data_source_id,
                sorts=[{"property": "日期 1", "direction": "descending"}],
                limit=self.settings.search_refresh_limit,
            )
            parent_filter = self.settings.diary_data_source_id
        elif scope == "database":
            if not database_id:
                raise invalid_argument("scope=database 时必须传 database_id")
            source, source_warnings = await self._resolve_data_source(client, database_id)
            warnings.extend(source_warnings)
            pages, _, has_more = await client.query_data_source(
                source["id"],
                sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
                limit=self.settings.search_refresh_limit,
            )
            parent_filter = source["id"]
        else:
            pages, has_more = await client.search_pages(limit=self.settings.search_refresh_limit)

        await asyncio.to_thread(self.search_index.initialize)
        semaphore = asyncio.Semaphore(4)
        index_lock = asyncio.Lock()

        async def refresh(page_stub: dict[str, Any]) -> None:
            page_id = page_stub.get("id")
            last_edited = str(page_stub.get("last_edited_time") or "")
            cached = await asyncio.to_thread(self.search_index.last_edited_time, page_id)
            if cached and cached == last_edited:
                return
            async with semaphore:
                page = page_stub if page_stub.get("properties") else await client.retrieve_page(page_id)
                blocks = await client.block_children(page_id)
            # Notion reads stay concurrent; SQLite writes are serialized to avoid
            # intermittent database-is-locked gaps during a refresh.
            async with index_lock:
                await self._index_page(client, page, blocks)

        results = await asyncio.gather(*(refresh(page) for page in pages), return_exceptions=True)
        failed = sum(1 for item in results if isinstance(item, Exception))
        if failed:
            warnings.append(f"有 {failed} 个页面因权限或临时错误未能刷新索引")
        if has_more:
            warnings.append(
                f"可访问页面超过单次刷新上限 {self.settings.search_refresh_limit}；本次结果可能不包含尚未建立索引的旧页面"
            )
        if parent_filter:
            warnings.append(f"搜索范围限定为 Data Source {parent_filter}")
        return warnings

    async def search_memory(
        self,
        client: NotionClient,
        *,
        query: str,
        scope: str = "all",
        database_id: str | None = None,
        limit: int = 10,
        include_content: bool = False,
    ) -> dict[str, Any]:
        if not query.strip():
            raise invalid_argument("query 不能为空")
        if scope not in {"all", "diary", "database"}:
            raise invalid_argument("scope 只支持 all、diary 或 database")
        if not 1 <= limit <= 50:
            raise invalid_argument("limit 必须在 1 到 50 之间")
        warnings = await self._refresh_search_index(client, scope=scope, database_id=database_id)
        parent_id: str | None = None
        if scope == "diary":
            parent_id = self.settings.diary_data_source_id
        elif scope == "database" and database_id:
            source, _ = await self._resolve_data_source(client, database_id)
            parent_id = source["id"]
        items = await asyncio.to_thread(
            self.search_index.search, query, limit=limit, parent_id=parent_id
        )
        if not include_content:
            for item in items:
                item.pop("content", None)
        return ok_result(
            {"query": query, "scope": scope, "count": len(items), "items": items},
            warnings=warnings,
            request_ids=client.request_ids(),
        )
