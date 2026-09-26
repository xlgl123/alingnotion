from __future__ import annotations

from notion_mcp.settings import Settings


def test_from_env_does_not_trust_public_networks_by_default(monkeypatch) -> None:
    monkeypatch.setenv("NOTION_TOKEN", "notion-test-token")
    monkeypatch.setenv("MCP_ACCESS_TOKEN", "mcp-test-token")
    monkeypatch.setenv("DIARY_DATA_SOURCE_ID", "diary-data-source")
    monkeypatch.delenv("CLAUDE_MCP_UNAUTHENTICATED_CIDRS", raising=False)

    settings = Settings.from_env()

    assert settings.claude_unauthenticated_cidrs == ()
    assert settings.allow_unauthenticated is False


def test_from_env_accepts_explicit_proxy_networks(monkeypatch) -> None:
    monkeypatch.setenv("NOTION_TOKEN", "notion-test-token")
    monkeypatch.setenv("MCP_ACCESS_TOKEN", "mcp-test-token")
    monkeypatch.setenv("DIARY_DATA_SOURCE_ID", "diary-data-source")
    monkeypatch.setenv(
        "CLAUDE_MCP_UNAUTHENTICATED_CIDRS",
        "192.0.2.0/24,2001:db8::/32",
    )

    settings = Settings.from_env()

    assert settings.claude_unauthenticated_cidrs == (
        "192.0.2.0/24",
        "2001:db8::/32",
    )
