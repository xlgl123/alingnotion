from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_defaults_do_not_embed_trusted_public_networks() -> None:
    files = (
        ROOT / "notion_mcp" / "settings.py",
        ROOT / ".env.example",
        ROOT / "deploy" / "notion-mcp.env.template",
        ROOT / "scripts" / "install_server.sh",
        ROOT / "scripts" / "deploy_claude_unauth.sh",
        ROOT / "scripts" / "verify_claude_unauth.sh",
    )

    for path in files:
        content = path.read_text(encoding="utf-8")
        assert "160.79.104.0/21" not in content
        assert "/home/ubuntu/" not in content


def test_global_unauthenticated_deploy_requires_explicit_confirmation() -> None:
    script = (ROOT / "scripts" / "deploy_global_unauth.sh").read_text(
        encoding="utf-8"
    )

    guard = 'CONFIRM_GLOBAL_UNAUTHENTICATED:-}'
    mutation = 'print "MCP_ALLOW_UNAUTHENTICATED=true"'
    assert guard in script
    assert script.index(guard) < script.index(mutation)
