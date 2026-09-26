#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


EXPECTED_TOOLS = {
    "write_diary",
    "search_memory",
    "read_page",
    "fetch_recent_diary",
    "create_page",
    "update_page",
    "query_database",
    "append_content",
}


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


def rpc(url: str, token: str, request_id: int, method: str, params: dict) -> dict:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    ).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read(300).decode("utf-8", errors="replace")
        raise RuntimeError(f"MCP HTTP {exc.code}: {body}") from exc


def main() -> None:
    env = load_env("/etc/notion-mcp.env")
    token = env["MCP_ACCESS_TOKEN"]
    url = os.environ.get("MCP_VERIFY_URL", "http://127.0.0.1:8091/mcp")

    initialized = rpc(
        url,
        token,
        1,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "server-verifier", "version": "1.0"},
        },
    )
    if initialized.get("result", {}).get("serverInfo", {}).get("name") != "Aling Notion":
        raise RuntimeError("Unexpected MCP server identity")

    listed = rpc(url, token, 2, "tools/list", {})
    tools = listed.get("result", {}).get("tools", [])
    names = {tool["name"] for tool in tools}
    if names != EXPECTED_TOOLS:
        raise RuntimeError(f"Tool mismatch: {sorted(names)}")

    recent = rpc(
        url,
        token,
        3,
        "tools/call",
        {"name": "fetch_recent_diary", "arguments": {"days": 1}},
    )
    if "error" in recent or recent.get("result", {}).get("isError"):
        raise RuntimeError("Read-only fetch_recent_diary call failed")

    print(f"TOOLS_OK count={len(names)} names={','.join(sorted(names))}")
    print("NOTION_READ_OK tool=fetch_recent_diary days=1")
    print(f"ENDPOINT_OK url={url}")


if __name__ == "__main__":
    main()
