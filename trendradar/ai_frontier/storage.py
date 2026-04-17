"""AI 前沿独立 SQLite 存储

专用数据库 `output/ai_frontier.db`，与主 RSS/热榜数据完全解耦。
核心表：ai_items，以 (source, url) 作为唯一键。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from trendradar.ai_frontier.sources.base import AIItem
from trendradar.utils.logging import log

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_name TEXT,
    title TEXT NOT NULL,
    title_translated TEXT DEFAULT '',
    url TEXT NOT NULL,
    published_at TEXT,
    score INTEGER DEFAULT 0,
    author TEXT,
    summary TEXT,
    tags TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(source, url)
);
CREATE INDEX IF NOT EXISTS idx_ai_source ON ai_items(source);
CREATE INDEX IF NOT EXISTS idx_ai_published ON ai_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_score ON ai_items(score DESC);
CREATE INDEX IF NOT EXISTS idx_ai_first_seen ON ai_items(first_seen);
"""


class AIFrontierStorage:
    """AI 前沿独立 SQLite 存储后端"""

    def __init__(self, db_path: str | Path = "output/ai_frontier.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(SCHEMA)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "AIFrontierStorage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ─────────────────────────────────────────────────────────────
    # 写入：upsert 返回 (new_items, updated_items)
    # ─────────────────────────────────────────────────────────────
    def upsert_items(self, items: Iterable[AIItem]) -> tuple[list[AIItem], list[AIItem]]:
        """插入或更新条目。

        返回：
            (new_items, updated_items)
            new_items：首次出现的条目（first_seen == last_seen，被标记 is_new=True）
            updated_items：已存在的条目（更新 last_seen、score）
        """
        conn = self._get_conn()
        cur = conn.cursor()

        now = datetime.now(tz=timezone.utc).isoformat()
        new_items: list[AIItem] = []
        updated_items: list[AIItem] = []

        for item in items:
            cur.execute(
                "SELECT id, first_seen FROM ai_items WHERE source = ? AND url = ?",
                (item.source, item.url),
            )
            row = cur.fetchone()

            tags_json = json.dumps(item.tags or [], ensure_ascii=False)
            pub_str = item.published_at.isoformat() if item.published_at else None

            if row is None:
                cur.execute(
                    """
                    INSERT INTO ai_items (
                        source, source_name, title, title_translated, url,
                        published_at, score, author, summary, tags,
                        first_seen, last_seen
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.source,
                        item.source_name,
                        item.title,
                        item.title_translated,
                        item.url,
                        pub_str,
                        item.score,
                        item.author,
                        item.summary,
                        tags_json,
                        now,
                        now,
                    ),
                )
                item.is_new = True
                new_items.append(item)
            else:
                cur.execute(
                    """
                    UPDATE ai_items SET
                        last_seen = ?,
                        score = ?,
                        title_translated = CASE WHEN ? != '' THEN ? ELSE title_translated END
                    WHERE id = ?
                    """,
                    (now, item.score, item.title_translated, item.title_translated, row["id"]),
                )
                item.is_new = False
                updated_items.append(item)

        conn.commit()
        log.info(f"DB 写入：新增 {len(new_items)}，更新 {len(updated_items)}")
        return new_items, updated_items

    # ─────────────────────────────────────────────────────────────
    # 查询
    # ─────────────────────────────────────────────────────────────
    def get_new_since(self, since_iso: str) -> list[AIItem]:
        """查询 first_seen >= since_iso 的条目（用于渲染本次推送）"""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT source, source_name, title, title_translated, url,
                   published_at, score, author, summary, tags, first_seen, last_seen
            FROM ai_items
            WHERE first_seen >= ?
            ORDER BY score DESC, published_at DESC
            """,
            (since_iso,),
        )
        return [self._row_to_item(r, is_new=True) for r in cur.fetchall()]

    def get_recent(self, limit: int = 100) -> list[AIItem]:
        """查询最近 last_seen 的条目"""
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT source, source_name, title, title_translated, url,
                   published_at, score, author, summary, tags, first_seen, last_seen
            FROM ai_items
            ORDER BY last_seen DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_item(r) for r in cur.fetchall()]

    def count(self) -> int:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ai_items")
        return cur.fetchone()[0]

    @staticmethod
    def _row_to_item(row: sqlite3.Row, is_new: bool = False) -> AIItem:
        pub_dt: datetime | None = None
        pub_str = row["published_at"]
        if pub_str:
            try:
                pub_dt = datetime.fromisoformat(pub_str)
            except ValueError:
                pub_dt = None

        try:
            tags = json.loads(row["tags"] or "[]")
        except (json.JSONDecodeError, TypeError):
            tags = []

        return AIItem(
            source=row["source"],
            source_name=row["source_name"] or "",
            title=row["title"],
            url=row["url"],
            published_at=pub_dt,
            score=row["score"] or 0,
            author=row["author"] or "",
            summary=row["summary"] or "",
            tags=tags,
            title_translated=row["title_translated"] or "",
            is_new=is_new,
        )
