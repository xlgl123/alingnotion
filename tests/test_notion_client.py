import asyncio
import json

import httpx
import pytest

from notion_mcp.errors import NotionAPIError
from notion_mcp.notion_client import NotionClient


PAGE_ID = "3a225f77-b313-8121-98ac-e263c004766e"


@pytest.mark.asyncio
async def test_block_children_handles_pagination_and_recursion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        cursor = request.url.params.get("start_cursor")
        if path.endswith(f"/{PAGE_ID}/children") and not cursor:
            return httpx.Response(
                200,
                json={
                    "results": [{"id": "11111111-1111-1111-1111-111111111111", "type": "paragraph", "paragraph": {"rich_text": []}, "has_children": True}],
                    "has_more": True,
                    "next_cursor": "next",
                },
                headers={"x-notion-request-id": "r1"},
            )
        if path.endswith("/11111111-1111-1111-1111-111111111111/children"):
            return httpx.Response(200, json={"results": [], "has_more": False}, headers={"x-notion-request-id": "r-child"})
        return httpx.Response(
            200,
            json={"results": [{"id": "22222222-2222-2222-2222-222222222222", "type": "divider", "divider": {}, "has_children": False}], "has_more": False},
            headers={"x-notion-request-id": "r2"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.notion.com") as http:
        notion = NotionClient("secret", http_client=http)
        async with notion as client:
            blocks = await client.block_children(PAGE_ID)
    assert len(blocks) == 2
    assert blocks[0]["children"] == []
    assert notion.request_ids() == ["r1", "r-child", "r2"]


@pytest.mark.asyncio
async def test_error_is_sanitized_and_does_not_echo_token() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"code": "restricted_resource", "message": "forbidden", "request_id": "req"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.notion.com") as http:
        async with NotionClient("super-secret-token", http_client=http) as client:
            with pytest.raises(NotionAPIError) as error:
                await client.retrieve_page(PAGE_ID)
    serialized = json.dumps(error.value.as_result(), ensure_ascii=False)
    assert error.value.code == "NOTION_FORBIDDEN"
    assert "super-secret-token" not in serialized


@pytest.mark.asyncio
async def test_append_batches_at_100_blocks() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sizes.append(len(body["children"]))
        return httpx.Response(200, json={"results": body["children"]})

    blocks = [{"object": "block", "type": "divider", "divider": {}} for _ in range(205)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.notion.com") as http:
        async with NotionClient("secret", http_client=http) as client:
            result = await client.append_blocks(PAGE_ID, blocks)
    assert sizes == [100, 100, 5]
    assert len(result) == 205


@pytest.mark.asyncio
async def test_concurrent_requests_keep_all_request_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json={"id": page_id, "properties": {}},
            headers={"x-notion-request-id": f"req-{page_id}"},
        )

    ids = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
    ]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.notion.com") as http:
        notion = NotionClient("secret", http_client=http)
        async with notion as client:
            await asyncio.gather(*(client.retrieve_page(page_id) for page_id in ids))
    assert set(notion.request_ids()) == {f"req-{page_id}" for page_id in ids}
