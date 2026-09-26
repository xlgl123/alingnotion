from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class IndexedPage:
    page_id: str
    title: str
    properties_text: str
    content: str
    url: str
    parent_id: str
    last_edited_time: str
    diary_date: str | None = None


class SearchIndex:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def initialize(self) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pages (
                    page_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    properties_text TEXT NOT NULL,
                    content TEXT NOT NULL,
                    url TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    last_edited_time TEXT NOT NULL,
                    diary_date TEXT,
                    indexed_at TEXT NOT NULL
                )
                """
            )
            try:
                db.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(page_id UNINDEXED, title, properties_text, content)"
                )
            except sqlite3.OperationalError:
                # Substring fallback below remains fully functional without FTS5.
                pass

    def count(self) -> int:
        self.initialize()
        with closing(self._connect()) as db, db:
            return int(db.execute("SELECT COUNT(*) FROM pages").fetchone()[0])

    def last_edited_time(self, page_id: str) -> str | None:
        self.initialize()
        with closing(self._connect()) as db, db:
            row = db.execute("SELECT last_edited_time FROM pages WHERE page_id = ?", (page_id,)).fetchone()
            return str(row[0]) if row else None

    def upsert(self, page: IndexedPage) -> None:
        self.initialize()
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as db, db:
            db.execute(
                """
                INSERT INTO pages(page_id,title,properties_text,content,url,parent_id,last_edited_time,diary_date,indexed_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(page_id) DO UPDATE SET
                    title=excluded.title,
                    properties_text=excluded.properties_text,
                    content=excluded.content,
                    url=excluded.url,
                    parent_id=excluded.parent_id,
                    last_edited_time=excluded.last_edited_time,
                    diary_date=excluded.diary_date,
                    indexed_at=excluded.indexed_at
                """,
                (
                    page.page_id,
                    page.title,
                    page.properties_text,
                    page.content,
                    page.url,
                    page.parent_id,
                    page.last_edited_time,
                    page.diary_date,
                    now,
                ),
            )
            try:
                db.execute("DELETE FROM pages_fts WHERE page_id = ?", (page.page_id,))
                db.execute(
                    "INSERT INTO pages_fts(page_id,title,properties_text,content) VALUES(?,?,?,?)",
                    (page.page_id, page.title, page.properties_text, page.content),
                )
            except sqlite3.OperationalError:
                pass

    def search(self, query: str, *, limit: int = 10, parent_id: str | None = None) -> list[dict[str, Any]]:
        self.initialize()
        needle = query.casefold()
        where = "(instr(lower(title), lower(?)) > 0 OR instr(lower(properties_text), lower(?)) > 0 OR instr(lower(content), lower(?)) > 0)"
        params: list[Any] = [query, query, query]
        if parent_id:
            where += " AND parent_id = ?"
            params.append(parent_id)
        params.append(limit)
        with closing(self._connect()) as db, db:
            rows = db.execute(
                f"SELECT * FROM pages WHERE {where} ORDER BY last_edited_time DESC LIMIT ?", params
            ).fetchall()

        output: list[dict[str, Any]] = []
        for row in rows:
            haystacks = [
                ("title", row["title"]),
                ("properties", row["properties_text"]),
                ("content", row["content"]),
            ]
            location = "content"
            source = row["content"]
            position = -1
            for candidate_location, candidate in haystacks:
                candidate_position = candidate.casefold().find(needle)
                if candidate_position >= 0:
                    location, source, position = candidate_location, candidate, candidate_position
                    break
            start = max(position - 80, 0)
            end = min(position + len(query) + 120, len(source)) if position >= 0 else 200
            snippet = source[start:end]
            output.append(
                {
                    "page_id": row["page_id"],
                    "title": row["title"],
                    "url": row["url"],
                    "parent_id": row["parent_id"],
                    "date": row["diary_date"],
                    "last_edited_time": row["last_edited_time"],
                    "match_location": location,
                    "snippet": snippet,
                    "content": row["content"],
                }
            )
        return output
