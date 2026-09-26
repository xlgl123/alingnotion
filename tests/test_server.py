from pathlib import Path

import pytest
from starlette.testclient import TestClient

from notion_mcp.server import create_app, create_mcp
from notion_mcp.settings import Settings


class DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class DummyService:
    async def read_page(self, client, *, page: str, format: str = "markdown"):
        return {"ok": True, "data": {"id": page, "format": format}, "warnings": [], "notion_request_ids": []}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        notion_token="notion-test-token",
        mcp_access_token="mcp-test-token",
        public_host="notion.test",
        allowed_origins=("https://notion.test",),
        search_db_path=tmp_path / "search.db",
    )


@pytest.mark.asyncio
async def test_exactly_eight_tools_are_exposed(settings: Settings) -> None:
    mcp = create_mcp(settings)
    tools = await mcp.list_tools()
    assert [tool.name for tool in tools] == [
        "write_diary",
        "search_memory",
        "read_page",
        "fetch_recent_diary",
        "create_page",
        "update_page",
        "query_database",
        "append_content",
    ]
    write_schema = next(tool.inputSchema for tool in tools if tool.name == "write_diary")
    assert "tomorrow_todos" not in write_schema.get("properties", {})
    assert "content" in write_schema.get("required", [])


def test_http_security_and_single_endpoint(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.post("/mcp", headers={"host": "notion.test"}, json={}).status_code == 401
        assert client.get("/mcp", headers={"host": "notion.test"}).status_code == 405
        assert client.get("/sse", headers={"host": "notion.test"}).status_code == 404
        assert client.post(
            "/mcp",
            headers={"host": "evil.test", "authorization": "Bearer mcp-test-token"},
            json={},
        ).status_code == 421
        assert client.post(
            "/mcp",
            headers={
                "host": "notion.test",
                "origin": "https://evil.test",
                "authorization": "Bearer mcp-test-token",
            },
            json={},
        ).status_code == 403


def test_claude_network_can_connect_without_token_only_through_loopback_proxy(settings: Settings) -> None:
    app = create_app(settings, service=DummyService(), client_factory=DummyClient)
    headers = {
        "host": "notion.test",
        "cf-connecting-ip": "160.79.104.42",
        "accept": "application/json, text/event-stream",
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "claude", "version": "1"},
        },
    }

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post("/mcp", headers=headers, json=payload)
        assert response.status_code == 200

    untrusted_app = create_app(settings, service=DummyService(), client_factory=DummyClient)
    with TestClient(untrusted_app, client=("203.0.113.9", 50000)) as client:
        response = client.post("/mcp", headers=headers, json=payload)
        assert response.status_code == 401


def test_non_claude_network_still_requires_token_through_loopback_proxy(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.post(
            "/mcp",
            headers={"host": "notion.test", "cf-connecting-ip": "203.0.113.9"},
            json={},
        )
        assert response.status_code == 401


def test_global_unauthenticated_mode_allows_public_initialize(settings: Settings) -> None:
    public_settings = Settings(
        notion_token=settings.notion_token,
        mcp_access_token=settings.mcp_access_token,
        public_host=settings.public_host,
        allowed_origins=settings.allowed_origins,
        claude_unauthenticated_cidrs=(),
        allow_unauthenticated=True,
        search_db_path=settings.search_db_path,
    )
    app = create_app(public_settings, service=DummyService(), client_factory=DummyClient)
    with TestClient(app, client=("203.0.113.9", 50000)) as client:
        response = client.post(
            "/mcp",
            headers={"host": "notion.test", "accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "public-client", "version": "1"},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "Aling Notion"


def test_streamable_http_initialize_and_tools_list(settings: Settings) -> None:
    app = create_app(settings, service=DummyService(), client_factory=DummyClient)
    headers = {
        "host": "notion.test",
        "origin": "https://notion.test",
        "authorization": "Bearer mcp-test-token",
        "accept": "application/json, text/event-stream",
    }
    with TestClient(app) as client:
        initialize = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1"},
                },
            },
        )
        assert initialize.status_code == 200
        assert initialize.json()["result"]["serverInfo"]["name"] == "Aling Notion"

        tools = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools.status_code == 200
        assert [item["name"] for item in tools.json()["result"]["tools"]] == [
            "write_diary",
            "search_memory",
            "read_page",
            "fetch_recent_diary",
            "create_page",
            "update_page",
            "query_database",
            "append_content",
        ]

        called = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "read_page", "arguments": {"page": "page-test"}},
            },
        )
        assert called.status_code == 200
        assert called.json()["result"]["structuredContent"]["data"]["id"] == "page-test"
