import pytest

from notion_mcp.errors import AppError
from notion_mcp.ids import normalize_notion_id


ID = "3a225f77-b313-8121-98ac-e263c004766e"


@pytest.mark.parametrize(
    "value",
    [
        ID,
        ID.replace("-", ""),
        f"https://www.notion.so/workspace/2026-7-19-{ID.replace('-', '')}?v=abc",
        f"https://app.notion.com/p/anything-{ID.replace('-', '')}",
    ],
)
def test_normalize_notion_id(value: str) -> None:
    assert normalize_notion_id(value) == ID


def test_invalid_id_is_rejected() -> None:
    with pytest.raises(AppError) as error:
        normalize_notion_id("https://notion.so/no-id")
    assert error.value.code == "INVALID_ARGUMENT"

