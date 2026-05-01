import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SessionDB:
    def __init__(self, path: Path):
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def init(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                tool TEXT NOT NULL,
                project TEXT NOT NULL,
                source_path TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                model TEXT,
                total_tokens INTEGER,
                message_count INTEGER,
                summary TEXT,
                sync_status TEXT DEFAULT 'pending',
                synced_at TEXT,
                title TEXT,
                title_source TEXT
            );
            CREATE TABLE IF NOT EXISTS tags (
                session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                PRIMARY KEY (session_id, tag)
            );
        """)
        # Idempotent migrations for upgrading existing DBs
        for sql in (
            "ALTER TABLE sessions ADD COLUMN title TEXT",
            "ALTER TABLE sessions ADD COLUMN title_source TEXT",
        ):
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.commit()

    def upsert_session(self, *, id: str, tool: str, project: str,
                        source_path: str, started_at: datetime | None,
                        ended_at: datetime | None, model: str,
                        total_tokens: int, message_count: int) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO sessions (id, tool, project, source_path, started_at,
                   ended_at, model, total_tokens, message_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   tool=excluded.tool, project=excluded.project,
                   source_path=excluded.source_path,
                   started_at=excluded.started_at, ended_at=excluded.ended_at,
                   model=excluded.model, total_tokens=excluded.total_tokens,
                   message_count=excluded.message_count""",
            (id, tool, project, source_path,
             started_at.isoformat() if started_at else None,
             ended_at.isoformat() if ended_at else None,
             model, total_tokens, message_count),
        )
        conn.commit()

    def get_session(self, id: str) -> dict | None:
        conn = self._get_conn()
        # Try exact match first
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (id,)).fetchone()
        if row:
            return dict(row)
        # Fall back to prefix match
        rows = conn.execute(
            "SELECT * FROM sessions WHERE id LIKE ?", (id + "%",)
        ).fetchall()
        if len(rows) == 1:
            return dict(rows[0])
        return None  # 0 or multiple matches

    def find_sessions_by_prefix(self, prefix: str) -> list[dict]:
        """Return all sessions matching an ID prefix."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM sessions WHERE id LIKE ?", (prefix + "%",)
        ).fetchall()
        return [dict(r) for r in rows]

    def list_sessions(self, *, project: str | None = None,
                      tag: str | None = None,
                      tool: str | None = None,
                      since: str | None = None,
                      status: str | None = None,
                      no_summary: bool = False) -> list[dict]:
        conn = self._get_conn()
        query = "SELECT DISTINCT s.* FROM sessions s"
        conditions = []
        params: list = []

        if tag:
            query += " JOIN tags t ON s.id = t.session_id"
            conditions.append("t.tag = ?")
            params.append(tag)
        if project:
            conditions.append("s.project = ?")
            params.append(project)
        if tool:
            conditions.append("s.tool = ?")
            params.append(tool)
        if since:
            conditions.append("s.started_at >= ?")
            params.append(since)
        if status:
            conditions.append("s.sync_status = ?")
            params.append(status)
        if no_summary:
            conditions.append("s.summary IS NULL")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY s.started_at DESC"

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    _TITLE_PRIORITY: dict[str | None, int] = {
        "manual": 1,
        "summary": 2,
        "ai-title": 3,
        "first-message": 4,
        None: 5,
    }

    def update_summary(self, id: str, summary: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE sessions SET summary = ?, sync_status = 'modified' WHERE id = ?",
            (summary, id),
        )
        conn.commit()

    def update_title(self, id: str, title: str, source: str | None) -> bool:
        """Write title only if `source` has equal-or-higher priority than the
        existing title_source. Returns True if written, False if blocked.
        Empty/whitespace title is rejected.
        """
        if not title or not title.strip():
            return False
        if source is None or source not in self._TITLE_PRIORITY:
            raise ValueError(f"unknown title source: {source!r}")

        conn = self._get_conn()
        row = conn.execute(
            "SELECT title_source FROM sessions WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return False  # session not found

        existing_source = row["title_source"]
        if self._TITLE_PRIORITY[source] > self._TITLE_PRIORITY[existing_source]:
            return False  # incoming has lower priority

        conn.execute(
            "UPDATE sessions SET title = ?, title_source = ? WHERE id = ?",
            (title.strip(), source, id),
        )
        conn.commit()
        return True

    def set_title_raw(self, id: str, title: str | None, source: str | None) -> None:
        """Direct write, no priority check. Reserved for reindex-from-meta."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE sessions SET title = ?, title_source = ? WHERE id = ?",
            (title, source, id),
        )
        conn.commit()

    def clear_title(self, id: str) -> None:
        """Reset both title and title_source to NULL."""
        self.set_title_raw(id, None, None)

    def update_sync_status(self, id: str, status: str) -> None:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat() if status == "synced" else None
        conn.execute(
            "UPDATE sessions SET sync_status = ?, synced_at = ? WHERE id = ?",
            (status, now, id),
        )
        conn.commit()

    def add_tags(self, session_id: str, tags: list[str]) -> None:
        conn = self._get_conn()
        for tag in tags:
            conn.execute(
                "INSERT OR IGNORE INTO tags (session_id, tag) VALUES (?, ?)",
                (session_id, tag),
            )
        conn.commit()

    def remove_tag(self, session_id: str, tag: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM tags WHERE session_id = ? AND tag = ?",
            (session_id, tag),
        )
        conn.commit()

    def get_tags(self, session_id: str) -> list[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT tag FROM tags WHERE session_id = ? ORDER BY tag",
            (session_id,),
        ).fetchall()
        return [r["tag"] for r in rows]

    def list_all_tags(self) -> list[tuple[str, int]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC, tag",
        ).fetchall()
        return [(r["tag"], r["cnt"]) for r in rows]

    def delete_session(self, id: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM sessions WHERE id = ?", (id,))
        conn.commit()

    def session_exists(self, id: str) -> bool:
        return self.get_session(id) is not None

    def resolve_id(self, id: str) -> str | None:
        """Resolve a (possibly prefix) ID to the full session ID."""
        session = self.get_session(id)
        return session["id"] if session else None
