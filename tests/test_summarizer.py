from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from session_zoom.models import Session, Message
from session_zoom.summarizer import (
    generate_summary, build_prompt, detect_provider,
)


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
    assert len(prompt) < 100_000


# --- API provider ---

@patch("anthropic.Anthropic")
def test_generate_summary_via_api(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Fixed XSS vulnerability in login page")]
    )

    result = generate_summary(_make_session(), provider="api", api_key="test-key")
    assert result == "Fixed XSS vulnerability in login page"
    mock_client.messages.create.assert_called_once()


# --- Claude Code CLI provider ---

@patch("subprocess.run")
def test_generate_summary_via_claude_code(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="Fixed XSS vulnerability in login page",
        stderr="",
    )

    result = generate_summary(_make_session(), provider="claude-code")
    assert result == "Fixed XSS vulnerability in login page"

    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--no-session-persistence" in cmd
    assert call_args[1]["input"]  # prompt passed via stdin


@patch("subprocess.run")
def test_generate_summary_via_claude_code_with_model(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="Summary", stderr="")

    generate_summary(_make_session(), provider="claude-code", model="haiku")
    cmd = mock_run.call_args[0][0]
    assert "--model" in cmd
    assert "haiku" in cmd


# --- Codex CLI provider ---

@patch("subprocess.run")
def test_generate_summary_via_codex(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="Fixed XSS vulnerability",
        stderr="",
    )

    result = generate_summary(_make_session(), provider="codex")
    assert result == "Fixed XSS vulnerability"

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "codex"
    assert "-q" in cmd


# --- Auto-detection ---

@patch("shutil.which")
def test_detect_provider_claude(mock_which):
    mock_which.side_effect = lambda x: "/usr/bin/claude" if x == "claude" else None
    assert detect_provider() == "claude-code"


@patch("shutil.which")
def test_detect_provider_codex(mock_which):
    mock_which.side_effect = lambda x: "/usr/bin/codex" if x == "codex" else None
    assert detect_provider() == "codex"


@patch("shutil.which", return_value=None)
def test_detect_provider_none(mock_which):
    assert detect_provider() is None


@patch("subprocess.run")
@patch("shutil.which", return_value="/usr/bin/claude")
def test_generate_summary_auto_uses_cli(mock_which, mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="Summary", stderr="")

    result = generate_summary(_make_session(), provider="auto")
    assert result == "Summary"
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "claude"


@patch("anthropic.Anthropic")
def test_generate_summary_auto_prefers_api_key(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="API Summary")]
    )

    result = generate_summary(_make_session(), provider="auto", api_key="test-key")
    assert result == "API Summary"
