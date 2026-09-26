from pathlib import Path

from notion_mcp.search_index import IndexedPage, SearchIndex


def test_chinese_substring_search_and_scope(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    index.upsert(
        IndexedPage(
            page_id="page-1",
            title="2026年7月19日",
            properties_text="心情: 开心",
            content="正文里记录了困困鸭终于到了。",
            url="https://notion/page-1",
            parent_id="diary",
            last_edited_time="2026-07-19T18:00:00Z",
            diary_date="2026-07-19",
        )
    )
    index.upsert(
        IndexedPage(
            page_id="page-2",
            title="其他页面",
            properties_text="",
            content="困困鸭在别的库",
            url="https://notion/page-2",
            parent_id="other",
            last_edited_time="2026-07-20T18:00:00Z",
        )
    )

    all_results = index.search("困困鸭", limit=10)
    diary_results = index.search("困困鸭", limit=10, parent_id="diary")
    assert [item["page_id"] for item in all_results] == ["page-2", "page-1"]
    assert [item["page_id"] for item in diary_results] == ["page-1"]
    assert diary_results[0]["match_location"] == "content"
    assert "困困鸭" in diary_results[0]["snippet"]


def test_upsert_replaces_stale_content(tmp_path: Path) -> None:
    index = SearchIndex(tmp_path / "search.db")
    page = IndexedPage("p", "旧标题", "", "旧内容", "u", "d", "1")
    index.upsert(page)
    page.title = "新标题"
    page.content = "新内容"
    page.last_edited_time = "2"
    index.upsert(page)
    assert index.search("旧内容") == []
    assert index.search("新内容")[0]["title"] == "新标题"


def test_connections_are_closed_after_each_operation(tmp_path: Path) -> None:
    path = tmp_path / "closable.db"
    index = SearchIndex(path)
    index.upsert(IndexedPage("p", "标题", "", "内容", "u", "d", "1"))
    assert index.count() == 1
    path.unlink()
    assert not path.exists()
