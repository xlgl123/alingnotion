from __future__ import annotations

import json
from typing import Any

from .errors import AppError
from .markdown_blocks import plain_text, rich_text


READ_ONLY_TYPES = {
    "created_by",
    "created_time",
    "formula",
    "last_edited_by",
    "last_edited_time",
    "rollup",
    "unique_id",
}


def property_value(value: dict[str, Any]) -> Any:
    prop_type = value.get("type")
    raw = value.get(prop_type) if prop_type else None
    if prop_type in {"title", "rich_text"}:
        return plain_text(raw)
    if prop_type in {"select", "status"}:
        return raw.get("name") if isinstance(raw, dict) else None
    if prop_type == "multi_select":
        return [item.get("name") for item in raw or []]
    if prop_type == "date":
        return raw
    if prop_type in {"people", "relation"}:
        return [item.get("id") for item in raw or []]
    if prop_type == "files":
        return raw or []
    if prop_type == "place":
        return None
    return raw


def public_properties(properties: dict[str, Any]) -> dict[str, Any]:
    return {name: property_value(value) for name, value in properties.items()}


def page_title(page: dict[str, Any]) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return plain_text(prop.get("title"))
    title = page.get("title")
    if isinstance(title, list):
        return plain_text(title)
    return ""


def properties_text(properties: dict[str, Any]) -> str:
    values = public_properties(properties)
    return "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in values.items())


def encode_properties(schema: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for name, value in values.items():
        if name not in schema:
            raise AppError("SCHEMA_MISMATCH", f"目标 Data Source 不存在字段：{name}")
        prop_type = schema[name].get("type")
        if prop_type in READ_ONLY_TYPES:
            raise AppError("SCHEMA_MISMATCH", f"字段 {name}（{prop_type}）为只读属性")
        if prop_type == "place":
            raise AppError(
                "UNSUPPORTED_PROPERTY",
                f"Notion 官方 API 目前不支持写入 Place 字段：{name}",
            )
        if isinstance(value, dict) and prop_type in value:
            encoded[name] = value
            continue
        if prop_type == "title":
            encoded[name] = {"title": rich_text(str(value))}
        elif prop_type == "rich_text":
            encoded[name] = {"rich_text": rich_text(str(value))}
        elif prop_type in {"select", "status"}:
            encoded[name] = {prop_type: None if value is None else {"name": str(value)}}
        elif prop_type == "multi_select":
            encoded[name] = {"multi_select": [{"name": str(item)} for item in value or []]}
        elif prop_type == "date":
            encoded[name] = {"date": value if isinstance(value, dict) else {"start": str(value)}}
        elif prop_type in {"checkbox", "number", "url", "email", "phone_number"}:
            encoded[name] = {prop_type: value}
        elif prop_type in {"people", "relation"}:
            encoded[name] = {prop_type: [{"id": str(item)} for item in value or []]}
        elif prop_type == "files":
            if not isinstance(value, list):
                raise AppError("SCHEMA_MISMATCH", f"字段 {name} 的 files 值必须为数组")
            encoded[name] = {"files": value}
        elif prop_type == "verification":
            encoded[name] = {"verification": value}
        else:
            raise AppError("UNSUPPORTED_PROPERTY", f"暂不支持写入字段 {name}（{prop_type}）")
    return encoded

