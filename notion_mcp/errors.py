from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    def as_result(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "details": self.details,
            },
            "warnings": [],
        }


@dataclass(slots=True)
class NotionAPIError(AppError):
    status: int = 0
    notion_code: str | None = None
    request_id: str | None = None


def invalid_argument(message: str, **details: Any) -> AppError:
    return AppError("INVALID_ARGUMENT", message, details=details)


def ok_result(data: Any, *, warnings: list[str] | None = None, request_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "data": data,
        "warnings": warnings or [],
        "notion_request_ids": request_ids or [],
    }

