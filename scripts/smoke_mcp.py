from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx


EXPECTED_TOOLS = [
    "write_diary",
    "search_memory",
    "read_page",
    "fetch_recent_diary",
    "create_page",
    "update_page",
    "query_database",
    "append_content",
]


def rpc(client: httpx.Client, url: str, headers: dict[str, str], request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        url,
        headers=headers,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"MCP {method} failed: {payload['error']}")
    return payload["result"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only smoke test for Aling Notion MCP")
    parser.add_argument("url", help="Full MCP URL, e.g. https://notion.example.com/mcp")
    args = parser.parse_args()
    token = os.getenv("MCP_ACCESS_TOKEN", "")
    if not token:
        print("Missing MCP_ACCESS_TOKEN environment variable", file=sys.stderr)
        return 2

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    report: dict[str, Any] = {}
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        unauthorized = client.post(args.url, json={})
        report["unauthorized_status"] = unauthorized.status_code
        if unauthorized.status_code != 401:
            raise RuntimeError(f"Expected 401 without token, got {unauthorized.status_code}")

        initialized = rpc(
            client,
            args.url,
            headers,
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "aling-smoke", "version": "1"},
            },
        )
        report["server_name"] = initialized["serverInfo"]["name"]
        tools = rpc(client, args.url, headers, 2, "tools/list", {})
        tool_names = [item["name"] for item in tools["tools"]]
        report["tools"] = tool_names
        if tool_names != EXPECTED_TOOLS:
            raise RuntimeError(f"Unexpected tool list: {tool_names}")

        page_id = os.getenv("READ_PAGE_ID")
        if page_id:
            read_result = rpc(
                client,
                args.url,
                headers,
                3,
                "tools/call",
                {"name": "read_page", "arguments": {"page": page_id, "format": "markdown"}},
            )
            structured = read_result.get("structuredContent") or {}
            report["read_page_ok"] = not read_result.get("isError", False) and structured.get("ok") is True
            if not report["read_page_ok"]:
                raise RuntimeError("read_page tool call did not return ok=true")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
