#!/usr/bin/env python3
from __future__ import annotations

import httpx


URL = "https://notion.example.com/mcp"
HEADERS = {"Accept": "application/json, text/event-stream"}


def rpc(client: httpx.Client, request_id: int, method: str, params: dict) -> dict:
    response = client.post(
        URL,
        headers=HEADERS,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    with httpx.Client(timeout=60) as client:
        initialized = rpc(
            client,
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "public-noauth-verifier", "version": "1.0"},
            },
        )
        if initialized["result"]["serverInfo"]["name"] != "Aling Notion":
            raise RuntimeError("Unexpected MCP server identity")

        tools = rpc(client, 2, "tools/list", {})["result"]["tools"]
        if len(tools) != 8:
            raise RuntimeError(f"Expected 8 tools, got {len(tools)}")

        recent = rpc(
            client,
            3,
            "tools/call",
            {"name": "fetch_recent_diary", "arguments": {"days": 1}},
        )
        if recent.get("result", {}).get("isError"):
            raise RuntimeError("Public read-only diary check failed")

        root_status = client.get("https://notion.example.com/").status_code
        sse_status = client.get("https://notion.example.com/sse").status_code
        mcp_get_status = client.get(URL).status_code
        if (root_status, sse_status, mcp_get_status) != (404, 404, 405):
            raise RuntimeError(
                f"Unexpected path statuses: root={root_status}, sse={sse_status}, mcp_get={mcp_get_status}"
            )

    print("PUBLIC_NOAUTH_OK initialize=200 tools=8 diary_read=ok")
    print(f"PATHS_OK root={root_status} sse={sse_status} mcp_get={mcp_get_status}")


if __name__ == "__main__":
    main()
