from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from session_zoom.models import Session, Message
from session_zoom.summarizer import generate_summary, build_prompt


def _make_session() -> Session:
    return Session(
        id="abc123", tool="claude-code", project="my-project",
        source_path=Path("/tmp/abc.jsonl"),
        started_at=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
        ended_at=datetime(2026, 3, 10, 11, 0, tzinfo=timezone.utc),
        model="claude-opus-4-6", total_tokens=5000,
        messages=[
            Message(role="user", content="Fix the login XSS bug",
                    timestamp=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
                    tool_calls=[]),
            Message(role="assistant", content="I found an XSS vulnerability in login.py",
                    timestamp=datetime(2026, 3, 10, 10, 31, tzinfo=timezone.utc),
                    tool_calls=[{"name": "Edit", "input": {"file_path": "src/login.py"}}]),
        ],
        git_branch="fix/xss", cwd="/home/user/project",
    )


def test_build_prompt_contains_conversation():
    prompt = build_prompt(_make_session())
    assert "Fix the login XSS bug" in prompt
    assert "XSS vulnerability" in prompt
    assert "src/login.py" in prompt


def test_build_prompt_truncates_long_sessions():
    msgs = [
        Message(role="user", content=f"Message {i}" * 100,
                timestamp=datetime(2026, 3, 10, 10 + i // 60, i % 60, tzinfo=timezone.utc),
                tool_calls=[])
        for i in range(100)
    ]
    session = Session(
        id="long", tool="claude-code", project="p",
        source_path=Path("/tmp/long.jsonl"),
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0,
        messages=msgs,
    )
    prompt = build_prompt(session)
    assert len(prompt) < 100_000  # Should be truncated


@patch("session_zoom.summarizer.anthropic")
def test_generate_summary(mock_anthropic):
    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Fixed XSS vulnerability in login page")]
    )

    result = generate_summary(_make_session(), api_key="test-key")
    assert result == "Fixed XSS vulnerability in login page"
    mock_client.messages.create.assert_called_once()
