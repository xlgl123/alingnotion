#!/usr/bin/env python3
from __future__ import annotations

import json
from typing import Any

import httpx


MCP_URL = "https://notion.example.com/mcp"
TEST_DATE = "2099-12-31"
TEST_TITLE = "【测试】Notion MCP 真实写入验收"
TEST_MARKER = "Codex真实写入验收-20260722"


def load_env(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            result[key] = value
    return result


def rpc(client: httpx.Client, request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        MCP_URL,
        headers={"Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )
    response.raise_for_status()
    return response.json()


def tool_result(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result") or {}
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content") or []
    if content and isinstance(content[0], dict) and content[0].get("type") == "text":
        return json.loads(content[0]["text"])
    raise RuntimeError("MCP tool response did not contain structured data")


def plain_text(items: list[dict[str, Any]]) -> str:
    return "".join(str(item.get("plain_text") or "") for item in items)


def main() -> None:
    env = load_env("/etc/notion-mcp.env")
    notion_headers = {
        "Authorization": f"Bearer {env['NOTION_TOKEN']}",
        "Notion-Version": env.get("NOTION_VERSION", "2026-03-11"),
        "Content-Type": "application/json",
    }
    data_source_id = env["DIARY_DATA_SOURCE_ID"]
    page_id: str | None = None
    write_verified = False
    trash_verified = False

    with httpx.Client(timeout=60) as client:
        existing = client.post(
            f"https://api.notion.com/v1/data_sources/{data_source_id}/query",
            headers=notion_headers,
            json={"filter": {"property": "日期 1", "date": {"equals": TEST_DATE}}, "page_size": 2},
        )
        existing.raise_for_status()
        if existing.json().get("results"):
            raise RuntimeError(f"Test date {TEST_DATE} is already occupied; nothing was changed")

        try:
            write = tool_result(
                rpc(
                    client,
                    1,
                    "tools/call",
                    {
                        "name": "write_diary",
                        "arguments": {
                            "date": TEST_DATE,
                            "title": TEST_TITLE,
                            "mood": "开心",
                            "summary": f"{TEST_MARKER}：验证日记属性与正文写入",
                            "sweet_moments": "测试页面，验收完成后移入回收站",
                            "content": (
                                f"# {TEST_MARKER}\n\n"
                                "---\n\n"
                                "## 测试说明\n\n"
                                "这是一篇由精简版 Notion MCP 创建的真实写入验收页面。\n\n"
                                "## 明日待办\n\n"
                                "- [ ] 验证待办区块能够从 content 正确写入\n"
                            ),
                        },
                    },
                )
            )
            if not write.get("ok"):
                error = write.get("error") or {}
                if error.get("code") == "PARTIAL_WRITE":
                    page_id = (error.get("details") or {}).get("page_id")
                raise RuntimeError(f"write_diary failed with {error.get('code')}")

            data = write.get("data") or {}
            page_id = data.get("page_id")
            if not page_id or not data.get("verified") or int(data.get("blocks_written") or 0) < 5:
                raise RuntimeError("write_diary did not return a fully verified page")

            read = tool_result(
                rpc(
                    client,
                    2,
                    "tools/call",
                    {"name": "read_page", "arguments": {"page": page_id, "format": "markdown"}},
                )
            )
            content = str((read.get("data") or {}).get("content") or "")
            if TEST_MARKER not in content or "明日待办" not in content:
                raise RuntimeError("read_page did not return the expected test content")

            page_response = client.get(
                f"https://api.notion.com/v1/pages/{page_id}", headers=notion_headers
            )
            page_response.raise_for_status()
            page = page_response.json()
            properties = page.get("properties") or {}
            title = plain_text((properties.get("日期") or {}).get("title") or [])
            date_value = ((properties.get("日期 1") or {}).get("date") or {}).get("start")
            mood = ((properties.get("心情") or {}).get("select") or {}).get("name")
            summary = plain_text((properties.get("今天做了什么") or {}).get("rich_text") or [])
            if title != TEST_TITLE or date_value != TEST_DATE or mood != "开心" or TEST_MARKER not in summary:
                raise RuntimeError("Notion page properties did not match the write request")

            blocks_response = client.get(
                f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100",
                headers=notion_headers,
            )
            blocks_response.raise_for_status()
            block_types = {item.get("type") for item in blocks_response.json().get("results") or []}
            required_types = {"heading_1", "heading_2", "paragraph", "divider", "to_do"}
            if not required_types.issubset(block_types):
                raise RuntimeError(f"Missing expected Notion block types: {sorted(required_types - block_types)}")

            write_verified = True
        finally:
            if page_id:
                trashed = client.patch(
                    f"https://api.notion.com/v1/pages/{page_id}",
                    headers=notion_headers,
                    json={"in_trash": True},
                )
                trashed.raise_for_status()
                confirmed = client.get(
                    f"https://api.notion.com/v1/pages/{page_id}", headers=notion_headers
                )
                confirmed.raise_for_status()
                trash_verified = bool(confirmed.json().get("in_trash"))

    if not write_verified:
        raise RuntimeError("Real write verification did not complete")
    if not trash_verified:
        raise RuntimeError(f"Test page cleanup was not verified: page_id={page_id}")
    print("REAL_WRITE_OK properties=ok blocks=ok read_page=ok")
    print(f"TEST_PAGE_TRASHED_OK page_id={page_id}")


if __name__ == "__main__":
    main()
