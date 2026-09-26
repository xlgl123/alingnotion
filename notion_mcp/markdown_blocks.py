from __future__ import annotations

import re
from typing import Any, Iterable


RICH_TEXT_CHUNK = 2000
MAX_RICH_TEXT_ITEMS = 100
MAX_BLOCK_TEXT = RICH_TEXT_CHUNK * MAX_RICH_TEXT_ITEMS


def rich_text(text: str) -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": {"content": text[index : index + RICH_TEXT_CHUNK]}}
        for index in range(0, len(text), RICH_TEXT_CHUNK)
    ]


def _text_blocks(block_type: str, text: str, **extra: Any) -> list[dict[str, Any]]:
    chunks = [text[index : index + MAX_BLOCK_TEXT] for index in range(0, len(text), MAX_BLOCK_TEXT)] or [""]
    return [
        {
            "object": "block",
            "type": block_type,
            block_type: {"rich_text": rich_text(chunk), **extra},
        }
        for chunk in chunks
    ]


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("content 不能为空")

    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[dict[str, Any]] = []
    paragraph: list[str] = []
    in_code = False
    code_language = "plain text"
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.extend(_text_blocks("paragraph", "\n".join(paragraph)))
            paragraph.clear()

    for line in lines:
        if in_code:
            if line.startswith("```"):
                code_text = "\n".join(code_lines)
                blocks.extend(_text_blocks("code", code_text, language=code_language or "plain text"))
                code_lines.clear()
                in_code = False
                code_language = "plain text"
            else:
                code_lines.append(line)
            continue

        if line.startswith("```"):
            flush_paragraph()
            in_code = True
            code_language = line[3:].strip() or "plain text"
            continue

        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue

        if re.fullmatch(r"-{3,}", stripped):
            flush_paragraph()
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            blocks.extend(_text_blocks(f"heading_{level}", heading.group(2).strip()))
            continue

        todo = re.match(r"^-\s+\[([ xX])\]\s+(.+)$", line)
        if todo:
            flush_paragraph()
            blocks.extend(
                _text_blocks("to_do", todo.group(2), checked=todo.group(1).lower() == "x")
            )
            continue

        bullet = re.match(r"^[-*+]\s+(.+)$", line)
        if bullet:
            flush_paragraph()
            blocks.extend(_text_blocks("bulleted_list_item", bullet.group(1)))
            continue

        numbered = re.match(r"^\d+[.)]\s+(.+)$", line)
        if numbered:
            flush_paragraph()
            blocks.extend(_text_blocks("numbered_list_item", numbered.group(1)))
            continue

        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            flush_paragraph()
            blocks.extend(_text_blocks("quote", quote.group(1)))
            continue

        paragraph.append(line)

    if in_code:
        raise ValueError("content 中存在未闭合的代码块")
    flush_paragraph()
    return blocks


def plain_text(rich_text_items: Iterable[dict[str, Any]] | None) -> str:
    if not rich_text_items:
        return ""
    return "".join(str(item.get("plain_text") or item.get("text", {}).get("content") or "") for item in rich_text_items)


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    rendered: list[str] = []
    for block in blocks:
        block_type = block.get("type", "unsupported")
        payload = block.get(block_type) or {}
        text = plain_text(payload.get("rich_text"))

        if block_type == "heading_1":
            rendered.append(f"# {text}")
        elif block_type == "heading_2":
            rendered.append(f"## {text}")
        elif block_type == "heading_3":
            rendered.append(f"### {text}")
        elif block_type == "divider":
            rendered.append("---")
        elif block_type == "to_do":
            rendered.append(f"- [{'x' if payload.get('checked') else ' '}] {text}")
        elif block_type == "bulleted_list_item":
            rendered.append(f"- {text}")
        elif block_type == "numbered_list_item":
            rendered.append(f"1. {text}")
        elif block_type == "quote":
            rendered.append(f"> {text}")
        elif block_type == "code":
            rendered.append(f"```{payload.get('language') or ''}\n{text}\n```")
        elif block_type == "paragraph":
            rendered.append(text)
        elif block_type == "child_page":
            rendered.append(f"## {payload.get('title', '')}")
        else:
            rendered.append(f"<!-- unsupported Notion block: {block_type} -->")

        children = block.get("children") or []
        if children:
            rendered.append(blocks_to_markdown(children))

    return "\n\n".join(part for part in rendered if part != "").strip()

