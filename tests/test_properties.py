import pytest

from notion_mcp.errors import AppError
from notion_mcp.properties import encode_properties, public_properties


SCHEMA = {
    "日期": {"type": "title"},
    "日期 1": {"type": "date"},
    "心情": {"type": "select"},
    "今天做了什么": {"type": "rich_text"},
    "Place": {"type": "place"},
    "创建时间": {"type": "created_time"},
}


def test_encode_friendly_values_using_schema() -> None:
    encoded = encode_properties(
        SCHEMA,
        {
            "日期": "2026年7月21日",
            "日期 1": "2026-07-21",
            "心情": "开心",
            "今天做了什么": "完成 MCP",
        },
    )
    assert encoded["日期"]["title"][0]["text"]["content"] == "2026年7月21日"
    assert encoded["日期 1"]["date"]["start"] == "2026-07-21"
    assert encoded["心情"] == {"select": {"name": "开心"}}


def test_place_write_is_explicitly_rejected() -> None:
    with pytest.raises(AppError) as error:
        encode_properties(SCHEMA, {"Place": "深圳"})
    assert error.value.code == "UNSUPPORTED_PROPERTY"


def test_unknown_and_readonly_properties_are_rejected() -> None:
    with pytest.raises(AppError, match="不存在字段"):
        encode_properties(SCHEMA, {"不存在": "x"})
    with pytest.raises(AppError, match="只读"):
        encode_properties(SCHEMA, {"创建时间": "x"})


def test_public_properties_flattens_values() -> None:
    result = public_properties(
        {
            "心情": {"type": "select", "select": {"name": "温柔"}},
            "日期 1": {"type": "date", "date": {"start": "2026-07-21"}},
        }
    )
    assert result == {"心情": "温柔", "日期 1": {"start": "2026-07-21"}}

