from datetime import datetime, timezone
from pathlib import Path
from session_zoon.models import Session, Message
from session_zoon.renderer import render_session_markdown


def _make_session() -> Session:
    return Session(
        id="abc123",
        tool="claude-code",
        project="my-project",
        source_path=Path("/tmp/abc.jsonl"),
        started_at=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
        ended_at=datetime(2026, 3, 10, 11, 45, tzinfo=timezone.utc),
        model="claude-opus-4-6",
        total_tokens=52340,
        messages=[
            Message(role="user", content="Fix the login bug",
                    timestamp=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
                    tool_calls=[]),
            Message(role="assistant", content="I'll fix it.",
                    timestamp=datetime(2026, 3, 10, 10, 31, tzinfo=timezone.utc),
                    tool_calls=[{"name": "Edit", "input": {"file_path": "src/login.py"}}],
                    token_usage={"input": 100, "output": 50}),
        ],
        git_branch="fix/login",
        cwd="/home/user/my-project",
    )


def test_render_contains_metadata():
    md = render_session_markdown(_make_session())
    assert "abc123" in md
    assert "claude-code" in md
    assert "claude-opus-4-6" in md
    assert "my-project" in md
    assert "fix/login" in md
    assert "52,340" in md


def test_render_contains_summary_when_provided():
    md = render_session_markdown(_make_session(), summary="Fixed XSS vulnerability")
    assert "Fixed XSS vulnerability" in md


def test_render_contains_conversation():
    md = render_session_markdown(_make_session())
    assert "Fix the login bug" in md
    assert "I'll fix it." in md


def test_render_contains_files():
    md = render_session_markdown(_make_session())
    assert "src/login.py" in md


def test_render_with_tags():
    md = render_session_markdown(_make_session(), tags=["bugfix", "security"])
    assert "`bugfix`" in md
    assert "`security`" in md
