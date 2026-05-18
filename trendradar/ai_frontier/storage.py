"""AI 前沿独立 SQLite 存储

专用数据库 `output/ai_frontier.db`，与主 RSS/热榜数据完全解耦。
核心表：ai_items，以 (source, url) 作为唯一键。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

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
            self._conn = sqlite3.connect(self.db_path, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            # 性能调优：WAL 并发读写 + 异步提交 + 内存临时表
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA temp_store = MEMORY")
            self._conn.execute("PRAGMA cache_size = -20000")  # ~20MB
        return self._conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(SCHEMA)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> AIFrontierStorage:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ─────────────────────────────────────────────────────────────
    # 写入：upsert 返回 (new_items, updated_items)
    # ─────────────────────────────────────────────────────────────
    def upsert_items(self, items: Iterable[AIItem]) -> tuple[list[AIItem], list[AIItem]]:
        """插入或更新条目（批量模式）。

        性能优化：
        - 单次批量 SELECT 查询已存在的 key 集合（避免 N 次查询）
        - 分别用 executemany 批量 INSERT / UPDATE
        - 单事务包裹全部写入

        返回：
            (new_items, updated_items)
            new_items：首次出现的条目（被标记 is_new=True）
            updated_items：已存在的条目（last_seen/score 被刷新）
        """
        items_list = list(items)
        if not items_list:
            return [], []

        conn = self._get_conn()
        cur = conn.cursor()

        # 1) 批量查询已存在的 (source, url) —— 用临时表避免 IN 参数过多
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS _lookup (source TEXT, url TEXT)")
        cur.execute("DELETE FROM _lookup")
        cur.executemany(
            "INSERT INTO _lookup (source, url) VALUES (?, ?)",
            [(it.source, it.url) for it in items_list],
        )
        cur.execute(
            """
            SELECT a.source, a.url FROM ai_items a
            INNER JOIN _lookup l ON a.source = l.source AND a.url = l.url
            """
        )
        existing: set[tuple[str, str]] = {(r[0], r[1]) for r in cur.fetchall()}

        now = datetime.now(tz=timezone.utc).isoformat()
        new_items: list[AIItem] = []
        updated_items: list[AIItem] = []
        insert_rows: list[tuple] = []
        update_rows: list[tuple] = []

        for item in items_list:
            tags_json = json.dumps(item.tags or [], ensure_ascii=False)
            pub_str = item.published_at.isoformat() if item.published_at else None
            key = (item.source, item.url)

            if key in existing:
                item.is_new = False
                updated_items.append(item)
                update_rows.append(
                    (
                        now,
                        item.score,
                        item.title_translated,
                        item.title_translated,
                        item.source,
                        item.url,
                    )
                )
            else:
                item.is_new = True
                new_items.append(item)
                insert_rows.append(
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
                    )
                )

        # 2) 单事务批量写入
        try:
            cur.execute("BEGIN")
            if insert_rows:
                cur.executemany(
                    """
                    INSERT INTO ai_items (
                        source, source_name, title, title_translated, url,
                        published_at, score, author, summary, tags,
                        first_seen, last_seen
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    insert_rows,
                )
            if update_rows:
                cur.executemany(
                    """
                    UPDATE ai_items SET
                        last_seen = ?,
                        score = ?,
                        title_translated = CASE WHEN ? != '' THEN ? ELSE title_translated END
                    WHERE source = ? AND url = ?
                    """,
                    update_rows,
                )
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

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
