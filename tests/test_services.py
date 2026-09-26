from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from notion_mcp.errors import AppError
from notion_mcp.search_index import SearchIndex
from notion_mcp.services import ToolService
from notion_mcp.settings import Settings


DIARY_ID = "11111111-2222-4333-8444-555555555555"
PAGE_ID = "3a225f77-b313-8121-98ac-e263c004766e"


def schema() -> dict[str, Any]:
    return {
        "日期": {"id": "title", "type": "title"},
        "日期 1": {"id": "date", "type": "date"},
        "心情": {"id": "mood", "type": "select"},
        "今天做了什么": {"id": "summary", "type": "rich_text"},
        "重要互动": {"id": "sweet", "type": "rich_text"},
        "Place": {"id": "place", "type": "place"},
    }


def make_page(page_id: str = PAGE_ID, *, content_title: str = "2026年7月21日") -> dict[str, Any]:
    return {
        "object": "page",
        "id": page_id,
        "url": f"https://notion.so/{page_id}",
        "parent": {"type": "data_source_id", "data_source_id": DIARY_ID},
        "created_time": "2026-07-21T00:00:00Z",
        "last_edited_time": "2026-07-21T00:01:00Z",
        "properties": {
            "日期": {"type": "title", "title": [{"plain_text": content_title}]},
            "日期 1": {"type": "date", "date": {"start": "2026-07-21"}},
            "心情": {"type": "select", "select": {"name": "开心"}},
        },
    }


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.duplicate_pages: list[dict[str, Any]] = []
        self.query_pages: list[dict[str, Any]] = []
        self.page = make_page()
        self.blocks: list[dict[str, Any]] = []
        self.search_stubs: list[dict[str, Any]] = []

    @staticmethod
    def request_ids() -> list[str]:
        return ["req-test"]

    async def retrieve_data_source(self, value: str) -> dict[str, Any]:
        self.calls.append(("retrieve_data_source", value))
        return {"object": "data_source", "id": DIARY_ID, "properties": schema()}

    async def query_data_source(self, value: str, **kwargs: Any) -> tuple[list[dict[str, Any]], None, bool]:
        self.calls.append(("query_data_source", value, kwargs))
        if kwargs.get("filter_") and kwargs["filter_"].get("date"):
            return self.duplicate_pages, None, False
        return self.query_pages, None, False

    async def create_page(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_page", kwargs))
        return self.page

    async def append_blocks(self, page: str, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.calls.append(("append_blocks", page, blocks))
        self.blocks.extend(blocks)
        return blocks

    async def retrieve_page(self, page: str) -> dict[str, Any]:
        self.calls.append(("retrieve_page", page))
        return self.page

    async def block_children(self, page: str) -> list[dict[str, Any]]:
        self.calls.append(("block_children", page))
        return self.blocks

    async def search_pages(self, **_: Any) -> tuple[list[dict[str, Any]], bool]:
        return self.search_stubs, False

    async def resolve_resource(self, value: str, allowed: tuple[str, ...] = ("data_source", "database", "page")) -> tuple[str, dict[str, Any]]:
        self.calls.append(("resolve_resource", value, allowed))
        return "data_source", {"object": "data_source", "id": DIARY_ID, "properties": schema()}

    async def update_page(self, page: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("update_page", page, kwargs))
        self.page["last_edited_time"] = "2026-07-21T00:02:00Z"
        if kwargs.get("erase_content"):
            self.blocks = []
        return self.page

    async def update_block(self, block: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("update_block", block, kwargs))
        return {"id": block}


class PartialAppendClient(FakeClient):
    async def append_blocks(self, page: str, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise AppError("NOTION_UNAVAILABLE", "network", retryable=True)


@pytest.fixture
def service(tmp_path: Path) -> ToolService:
    settings = Settings(
        notion_token="notion-secret",
        mcp_access_token="mcp-secret",
        search_db_path=tmp_path / "search.db",
        search_refresh_limit=20,
    )
    return ToolService(settings, SearchIndex(settings.search_db_path))


@pytest.mark.asyncio
async def test_write_diary_writes_properties_and_todos_inside_content(service: ToolService) -> None:
    client = FakeClient()
    result = await service.write_diary(
        client,
        date="2026-07-21",
        mood="开心",
        summary="完成本地服务",
        sweet_moments="一起检查方案",
        content="# 今日\n\n---\n\n## 📝 明日待办\n\n- [ ] 继续测试\n\n——AI伙伴",
    )
    assert result["ok"] is True
    create_call = next(call for call in client.calls if call[0] == "create_page")
    body = create_call[1]
    assert body["parent"] == {"type": "data_source_id", "data_source_id": DIARY_ID}
    assert body["properties"]["日期"]["title"][0]["text"]["content"] == "2026年7月21日"
    assert any(block["type"] == "to_do" for block in client.blocks)
    assert result["data"]["verified"] is True


@pytest.mark.asyncio
async def test_write_diary_refuses_duplicate_and_invalid_mood(service: ToolService) -> None:
    client = FakeClient()
    client.duplicate_pages = [make_page()]
    with pytest.raises(AppError) as duplicate:
        await service.write_diary(client, content="# 日记", date="2026-07-21")
    assert duplicate.value.code == "DUPLICATE_DIARY"
    assert not any(call[0] == "create_page" for call in client.calls)

    with pytest.raises(AppError) as mood:
        await service.write_diary(FakeClient(), content="# 日记", mood="暴躁")
    assert mood.value.code == "INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_write_diary_rejects_place_before_creating_page(service: ToolService) -> None:
    client = FakeClient()
    with pytest.raises(AppError) as error:
        await service.write_diary(client, content="# 日记", place="深圳")
    assert error.value.code == "UNSUPPORTED_PROPERTY"
    assert client.calls == []


@pytest.mark.asyncio
async def test_partial_diary_write_is_reported_honestly(service: ToolService) -> None:
    result = await service.write_diary(PartialAppendClient(), content="# 日记", date="2026-07-21")
    assert result["ok"] is False
    assert result["error"]["code"] == "PARTIAL_WRITE"
    assert result["error"]["details"]["page_id"] == PAGE_ID


@pytest.mark.asyncio
async def test_fetch_recent_diary_uses_date_property_and_sort(service: ToolService) -> None:
    client = FakeClient()
    client.query_pages = [make_page()]
    result = await service.fetch_recent_diary(client, days=7, include_content=False)
    assert result["ok"] is True
    query = next(call for call in client.calls if call[0] == "query_data_source")
    assert query[2]["filter_"]["property"] == "日期 1"
    assert query[2]["sorts"] == [{"property": "日期 1", "direction": "descending"}]


@pytest.mark.asyncio
async def test_read_page_outputs_markdown(service: ToolService) -> None:
    client = FakeClient()
    client.blocks = [{"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "标题"}]}}]
    result = await service.read_page(client, page=PAGE_ID)
    assert result["data"]["content"] == "# 标题"
    assert result["data"]["properties"]["心情"] == "开心"


@pytest.mark.asyncio
async def test_replace_requires_confirmation_and_detects_conflict(service: ToolService) -> None:
    client = FakeClient()
    with pytest.raises(AppError, match="confirm_replace"):
        await service.update_page(client, page=PAGE_ID, content="# 新内容", content_mode="replace")
    with pytest.raises(AppError) as conflict:
        await service.update_page(
            client,
            page=PAGE_ID,
            content="# 新内容",
            content_mode="replace",
            confirm_replace=True,
            expected_last_edited_time="old",
        )
    assert conflict.value.code == "EDIT_CONFLICT"


@pytest.mark.asyncio
async def test_replace_erases_then_writes_and_reindexes(service: ToolService) -> None:
    client = FakeClient()
    client.blocks = [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "旧"}]}}]
    result = await service.update_page(
        client,
        page=PAGE_ID,
        content="# 新内容",
        content_mode="replace",
        confirm_replace=True,
    )
    assert result["ok"] is True
    assert result["data"]["actions"][:2] == ["erased_old_content", "wrote_new_content"]
    assert client.blocks[0]["type"] == "heading_1"


@pytest.mark.asyncio
async def test_search_memory_finds_chinese_body_text(service: ToolService) -> None:
    client = FakeClient()
    client.search_stubs = [make_page()]
    client.blocks = [
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "正文中有困困鸭"}]}}
    ]
    result = await service.search_memory(client, query="困困鸭", include_content=False)
    assert result["ok"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["items"][0]["page_id"] == PAGE_ID
    assert "content" not in result["data"]["items"][0]


@pytest.mark.asyncio
async def test_query_database_returns_schema_and_items(service: ToolService) -> None:
    client = FakeClient()
    client.query_pages = [make_page()]
    result = await service.query_database(client, database=DIARY_ID)
    assert result["ok"] is True
    assert result["data"]["data_source_id"] == DIARY_ID
    assert result["data"]["schema"]["日期"]["type"] == "title"

