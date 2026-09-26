from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_search_path() -> Path:
    if os.name == "nt":
        return Path("F:/Codex/data/notion-mcp/search.db")
    return Path("/var/lib/notion-mcp/search.db")


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"无效布尔环境变量值: {value!r}")


@dataclass(frozen=True, slots=True)
class Settings:
    notion_token: str
    mcp_access_token: str
    notion_version: str = "2026-03-11"
    diary_data_source_id: str = ""
    timezone: str = "Asia/Shanghai"
    host: str = "127.0.0.1"
    port: int = 8091
    public_host: str = "localhost"
    allowed_origins: tuple[str, ...] = ()
    claude_unauthenticated_cidrs: tuple[str, ...] = ("160.79.104.0/21",)
    allow_unauthenticated: bool = False
    search_db_path: Path = Path("F:/Codex/data/notion-mcp/search.db")
    search_refresh_limit: int = 200
    request_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "Settings":
        notion_token = os.getenv("NOTION_TOKEN", "").strip()
        mcp_access_token = os.getenv("MCP_ACCESS_TOKEN", "").strip()
        if not notion_token:
            raise RuntimeError("缺少环境变量 NOTION_TOKEN")
        if not mcp_access_token:
            raise RuntimeError("缺少环境变量 MCP_ACCESS_TOKEN")
        if notion_token == mcp_access_token:
            raise RuntimeError("NOTION_TOKEN 与 MCP_ACCESS_TOKEN 必须使用不同密钥")
        diary_data_source_id = os.getenv("DIARY_DATA_SOURCE_ID", "").strip()
        if not diary_data_source_id:
            raise RuntimeError("缺少环境变量 DIARY_DATA_SOURCE_ID")

        public_host = os.getenv("NOTION_MCP_PUBLIC_HOST", "localhost").strip()
        origins = _csv(os.getenv("NOTION_MCP_ALLOWED_ORIGINS", ""))
        return cls(
            notion_token=notion_token,
            mcp_access_token=mcp_access_token,
            notion_version=os.getenv("NOTION_VERSION", "2026-03-11").strip(),
            diary_data_source_id=diary_data_source_id,
            timezone=os.getenv("TZ", "Asia/Shanghai").strip(),
            host=os.getenv("NOTION_MCP_HOST", "127.0.0.1").strip(),
            port=int(os.getenv("NOTION_MCP_PORT", "8091")),
            public_host=public_host,
            allowed_origins=origins,
            claude_unauthenticated_cidrs=_csv(
                os.getenv("CLAUDE_MCP_UNAUTHENTICATED_CIDRS", "160.79.104.0/21")
            ),
            allow_unauthenticated=_bool(os.getenv("MCP_ALLOW_UNAUTHENTICATED", "false")),
            search_db_path=Path(os.getenv("SEARCH_DB_PATH", str(_default_search_path()))),
            search_refresh_limit=int(os.getenv("SEARCH_REFRESH_LIMIT", "200")),
            request_timeout_seconds=float(os.getenv("NOTION_REQUEST_TIMEOUT", "30")),
        )
