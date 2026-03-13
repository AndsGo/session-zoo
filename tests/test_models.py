from datetime import datetime, timezone
from pathlib import Path
from session_zoo.models import Session, Message


def test_message_creation():
    msg = Message(
        role="user",
        content="Fix the bug",
        timestamp=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
        tool_calls=[],
        token_usage=None,
    )
    assert msg.role == "user"
    assert msg.content == "Fix the bug"


def test_session_creation():
    msg = Message(
        role="user",
        content="Hello",
        timestamp=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
        tool_calls=[],
        token_usage=None,
    )
    session = Session(
        id="abc123",
        tool="claude-code",
        project="my-project",
        source_path=Path("/home/user/.claude/projects/abc/123.jsonl"),
        started_at=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
        ended_at=datetime(2026, 3, 10, 11, 45, tzinfo=timezone.utc),
        model="claude-opus-4-6",
        total_tokens=52340,
        messages=[msg],
        git_branch="fix/xss",
        cwd="/home/user/my-project",
    )
    assert session.id == "abc123"
    assert session.tool == "claude-code"
    assert session.message_count == 1
    assert session.duration_minutes == 75


def test_session_duration_none_when_missing_end():
    session = Session(
        id="abc",
        tool="claude-code",
        project="test",
        source_path=Path("/tmp/test.jsonl"),
        started_at=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc),
        ended_at=None,
        model="claude-opus-4-6",
        total_tokens=0,
        messages=[],
        git_branch=None,
        cwd=None,
    )
    assert session.duration_minutes is None
    assert session.message_count == 0
