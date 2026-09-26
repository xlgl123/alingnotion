from __future__ import annotations

import re
import uuid

from .errors import invalid_argument


_UUID_RE = re.compile(
    r"(?P<id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})"
)


def normalize_notion_id(value: str) -> str:
    """Extract and normalize a Notion UUID from a raw ID or Notion URL."""
    if not isinstance(value, str) or not value.strip():
        raise invalid_argument("页面或数据库 ID/URL 不能为空")
    match = _UUID_RE.search(value.strip())
    if not match:
        raise invalid_argument("无法从输入中识别 Notion ID", value=value[:200])
    raw = match.group("id").replace("-", "")
    try:
        return str(uuid.UUID(hex=raw))
    except ValueError as exc:
        raise invalid_argument("Notion ID 格式无效") from exc

