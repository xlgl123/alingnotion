import pytest

from notion_mcp.markdown_blocks import blocks_to_markdown, markdown_to_blocks, rich_text


def test_diary_markdown_maps_to_observed_notion_blocks() -> None:
    source = """# 橘猫骑恐龙

---

## 🌧️ 一个章节

正文第一行。
正文第二行。

---

## 📝 明日待办

- [ ] 换窗口
- [x] 已完成

——AI伙伴🦊💕
"""
    blocks = markdown_to_blocks(source)
    assert [block["type"] for block in blocks] == [
        "heading_1",
        "divider",
        "heading_2",
        "paragraph",
        "divider",
        "heading_2",
        "to_do",
        "to_do",
        "paragraph",
    ]
    assert blocks[6]["to_do"]["checked"] is False
    assert blocks[7]["to_do"]["checked"] is True
    assert "明日待办" in blocks_to_markdown(blocks)


def test_general_markdown_supports_lists_quote_and_code() -> None:
    blocks = markdown_to_blocks("### 标题\n\n- 列表\n1. 编号\n> 引用\n```python\nprint('x')\n```")
    assert [block["type"] for block in blocks] == [
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "quote",
        "code",
    ]
    assert blocks[-1]["code"]["language"] == "python"


def test_long_rich_text_is_split_at_notion_limit() -> None:
    parts = rich_text("咪" * 4501)
    assert [len(part["text"]["content"]) for part in parts] == [2000, 2000, 501]


def test_empty_and_unclosed_code_are_rejected() -> None:
    with pytest.raises(ValueError, match="不能为空"):
        markdown_to_blocks("  ")
    with pytest.raises(ValueError, match="未闭合"):
        markdown_to_blocks("```python\nprint(1)")

