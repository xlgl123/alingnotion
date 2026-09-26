from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger("notion_mcp.audit")


def record(action: str, *, page_id: str, **metadata: Any) -> None:
    """Write a metadata-only audit event; never pass content or credentials."""
    safe = " ".join(f"{key}={value!r}" for key, value in sorted(metadata.items()))
    logger.info("action=%s page_id=%s %s", action, page_id, safe)

