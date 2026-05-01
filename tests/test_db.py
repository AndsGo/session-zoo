import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from session_zoo.db import SessionDB


def _make_db(tmp_path) -> SessionDB:
    return SessionDB(tmp_path / "test.db")


def test_create_tables(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    assert db.path.exists()


def test_upsert_and_get_session(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="abc123",
        tool="claude-code",
        project="my-project",
        source_path="/home/user/.claude/projects/abc/123.jsonl",
        started_at=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
        ended_at=datetime(2026, 3, 10, 11, 45, tzinfo=timezone.utc),
        model="claude-opus-4-6",
        total_tokens=52340,
        message_count=28,
    )
    row = db.get_session("abc123")
    assert row is not None
    assert row["tool"] == "claude-code"
    assert row["project"] == "my-project"
    assert row["total_tokens"] == 52340
    assert row["sync_status"] == "pending"


def test_list_sessions_filters(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    for i, proj in enumerate(["proj-a", "proj-a", "proj-b"]):
        db.upsert_session(
            id=f"s{i}",
            tool="claude-code",
            project=proj,
            source_path=f"/tmp/{i}.jsonl",
            started_at=datetime(2026, 3, 10 + i, 10, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 3, 10 + i, 11, 0, tzinfo=timezone.utc),
            model="claude-opus-4-6",
            total_tokens=1000 * i,
            message_count=10,
        )
    assert len(db.list_sessions()) == 3
    assert len(db.list_sessions(project="proj-a")) == 2
    assert len(db.list_sessions(project="proj-b")) == 1


def test_tags(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="s1", tool="claude-code", project="p",
        source_path="/tmp/s1.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    db.add_tags("s1", ["bugfix", "security"])
    assert db.get_tags("s1") == ["bugfix", "security"]

    db.remove_tag("s1", "bugfix")
    assert db.get_tags("s1") == ["security"]


def test_update_summary(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="s1", tool="claude-code", project="p",
        source_path="/tmp/s1.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    db.update_summary("s1", "Fixed XSS vulnerability")
    row = db.get_session("s1")
    assert row["summary"] == "Fixed XSS vulnerability"


def test_update_sync_status(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="s1", tool="claude-code", project="p",
        source_path="/tmp/s1.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    assert db.get_session("s1")["sync_status"] == "pending"
    db.update_sync_status("s1", "synced")
    assert db.get_session("s1")["sync_status"] == "synced"


def test_delete_session(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="s1", tool="claude-code", project="p",
        source_path="/tmp/s1.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    db.add_tags("s1", ["tag1"])
    db.delete_session("s1")
    assert db.get_session("s1") is None
    assert db.get_tags("s1") == []


def test_list_sessions_by_tag(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    for i in range(3):
        db.upsert_session(
            id=f"s{i}", tool="claude-code", project="p",
            source_path=f"/tmp/{i}.jsonl",
            started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
            ended_at=None, model="m", total_tokens=0, message_count=0,
        )
    db.add_tags("s0", ["bugfix"])
    db.add_tags("s1", ["bugfix", "feature"])
    assert len(db.list_sessions(tag="bugfix")) == 2
    assert len(db.list_sessions(tag="feature")) == 1


def test_list_all_tags(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="s1", tool="claude-code", project="p",
        source_path="/tmp/s1.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    db.upsert_session(
        id="s2", tool="claude-code", project="p",
        source_path="/tmp/s2.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    db.add_tags("s1", ["bugfix", "security"])
    db.add_tags("s2", ["bugfix"])
    tags = db.list_all_tags()
    assert tags == [("bugfix", 2), ("security", 1)]


def test_init_adds_title_columns_on_existing_db(tmp_path):
    """Simulate an old DB without title columns; init() should add them idempotently."""
    db_path = tmp_path / "old.db"
    # 1) Build a legacy schema (no title columns)
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE sessions (
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
            synced_at TEXT
        );
    """)
    conn.commit()
    conn.close()

    # 2) Run init() — should add the new columns without error
    db = SessionDB(db_path)
    db.init()
    db.init()  # second call must also be a no-op (idempotent)

    # 3) Verify columns exist via schema inspection
    conn = sqlite3.connect(str(db_path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    conn.close()
    assert "title" in cols
    assert "title_source" in cols


def _seed_session(db, sid="s1"):
    db.upsert_session(
        id=sid, tool="claude-code", project="p",
        source_path=f"/tmp/{sid}.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )


def test_update_title_writes_when_no_existing_title(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    assert db.update_title("s1", "First title", "ai-title") is True
    row = db.get_session("s1")
    assert row["title"] == "First title"
    assert row["title_source"] == "ai-title"


def test_update_title_priority_guard_blocks_lower(tmp_path):
    """manual (1) cannot be overwritten by summary (2)."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "Manual", "manual")
    assert db.update_title("s1", "Auto", "summary") is False
    row = db.get_session("s1")
    assert row["title"] == "Manual"
    assert row["title_source"] == "manual"


def test_update_title_priority_guard_allows_higher(tmp_path):
    """manual (1) can overwrite summary (2)."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "Auto", "summary")
    assert db.update_title("s1", "Manual", "manual") is True
    row = db.get_session("s1")
    assert row["title"] == "Manual"
    assert row["title_source"] == "manual"


def test_update_title_priority_first_message_to_ai_title(tmp_path):
    """ai-title (3) overwrites first-message (4)."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "ls", "first-message")
    assert db.update_title("s1", "Real title", "ai-title") is True
    row = db.get_session("s1")
    assert row["title_source"] == "ai-title"


def test_update_title_priority_ai_title_blocks_first_message(tmp_path):
    """first-message (4) cannot overwrite ai-title (3)."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "Real title", "ai-title")
    assert db.update_title("s1", "ls", "first-message") is False
    row = db.get_session("s1")
    assert row["title"] == "Real title"
    assert row["title_source"] == "ai-title"


def test_update_title_same_source_allowed_for_refresh(tmp_path):
    """Re-running summarize should refresh the summary-derived title."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "Old", "summary")
    assert db.update_title("s1", "New", "summary") is True
    row = db.get_session("s1")
    assert row["title"] == "New"


def test_update_title_rejects_empty(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    assert db.update_title("s1", "", "manual") is False
    assert db.update_title("s1", "   ", "manual") is False
    row = db.get_session("s1")
    assert row["title"] is None


def test_update_title_strips_whitespace_on_write(tmp_path):
    """Stored title should be the trimmed value when caller passes padded input."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    assert db.update_title("s1", "  Hello  ", "manual") is True
    row = db.get_session("s1")
    assert row["title"] == "Hello"


def test_set_title_raw_bypasses_guard(tmp_path):
    """reindex must be able to write a lower-priority source over higher."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "Manual", "manual")
    db.set_title_raw("s1", "Restored", "ai-title")
    row = db.get_session("s1")
    assert row["title"] == "Restored"
    assert row["title_source"] == "ai-title"


def test_set_title_raw_accepts_none(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "X", "manual")
    db.set_title_raw("s1", None, None)
    row = db.get_session("s1")
    assert row["title"] is None
    assert row["title_source"] is None


def test_clear_title_resets_both_columns(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "X", "manual")
    db.clear_title("s1")
    row = db.get_session("s1")
    assert row["title"] is None
    assert row["title_source"] is None
