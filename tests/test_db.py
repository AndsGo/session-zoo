from datetime import datetime, timezone
from pathlib import Path
from session_zoom.db import SessionDB


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
