from datetime import datetime, timezone
from pathlib import Path
from session_zoo.models import Session, Message
from session_zoo.renderer import render_session_markdown


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
                    tool_calls=[{"name": "Edit", "input": {"file_path": "/home/user/my-project/src/login.py"}}],
                    token_usage={"input": 100, "output": 50}),
        ],
        git_branch="fix/login",
        cwd="/home/user/my-project",
    )


# --- Title ---

def test_render_title_with_summary():
    md = render_session_markdown(_make_session(), summary="# Fixed XSS vulnerability\n\nDetails here")
    assert md.startswith("# Fixed XSS vulnerability\n")


def test_render_title_without_summary_uses_project_date():
    md = render_session_markdown(_make_session())
    assert "# my-project — 2026-03-10" in md


def test_render_title_no_summary_no_date():
    session = _make_session()
    session.started_at = None
    md = render_session_markdown(session)
    assert "# my-project — Session abc123" in md


# --- Metadata ---

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


def test_render_with_tags():
    md = render_session_markdown(_make_session(), tags=["bugfix", "security"])
    assert "`bugfix`" in md
    assert "`security`" in md


# --- Files Changed ---

def test_render_contains_files_as_relative():
    md = render_session_markdown(_make_session())
    assert "`src/login.py`" in md
    # Should NOT contain absolute path
    assert "/home/user/my-project/src/login.py" not in md


def test_render_filters_noise_files():
    session = _make_session()
    session.messages.append(
        Message(role="assistant", content="Reading plugin cache",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[
                    {"name": "Read", "input": {"file_path": "/home/user/.claude/plugins/cache/foo.md"}},
                    {"name": "Read", "input": {"file_path": "/home/user/.superpowers/brainstorm/bar.html"}},
                ])
    )
    md = render_session_markdown(session)
    assert ".claude/plugins" not in md
    assert ".superpowers/" not in md


def test_render_keeps_project_files():
    session = _make_session()
    session.messages.append(
        Message(role="assistant", content="Editing",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[
                    {"name": "Edit", "input": {"file_path": "/home/user/my-project/tests/test_foo.py"}},
                ])
    )
    md = render_session_markdown(session)
    assert "`tests/test_foo.py`" in md


# --- Conversation ---

def test_render_contains_conversation():
    md = render_session_markdown(_make_session())
    assert "Fix the login bug" in md
    assert "I'll fix it." in md


def test_render_skips_empty_messages():
    session = _make_session()
    session.messages.append(
        Message(role="assistant", content="",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[])
    )
    md = render_session_markdown(session)
    assert "> **Assistant:** \n" not in md


def test_render_skips_system_noise():
    session = _make_session()
    session.messages.append(
        Message(role="user",
                content="<local-command-caveat>Caveat: messages below</local-command-caveat>",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[])
    )
    session.messages.append(
        Message(role="user",
                content="<command-name>/plugin</command-name>\n<command-message>plugin</command-message>\n<command-args></command-args>",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[])
    )
    md = render_session_markdown(session)
    assert "local-command-caveat" not in md
    assert "/plugin" not in md


def test_render_skips_system_prompts():
    """Skill prompts leaked into user messages should be filtered."""
    session = _make_session()
    session.messages.append(
        Message(role="user",
                content="Base directory for this skill: /home/.claude/plugins/cache/superpowers/brainstorming\n\n# Brainstorming Ideas\nLong skill content...",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[])
    )
    session.messages.append(
        Message(role="user",
                content="superpowers:using-superpowers\n/superpowers:brainstorming\nActual user request",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[])
    )
    md = render_session_markdown(session)
    assert "Base directory for this skill" not in md
    assert "superpowers:using-superpowers" not in md


def test_render_strips_xml_tags_from_content():
    session = _make_session()
    session.messages.append(
        Message(role="user",
                content="<local-command-stdout>Bye!</local-command-stdout>",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[])
    )
    md = render_session_markdown(session)
    assert "local-command-stdout" not in md
    assert "Bye!" in md


# --- Tool call merging ---

def test_render_tool_only_assistant_message():
    session = _make_session()
    session.messages.append(
        Message(role="assistant", content="",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[{"name": "Read", "input": {"file_path": "foo.py"}},
                            {"name": "Edit", "input": {"file_path": "foo.py"}}])
    )
    md = render_session_markdown(session)
    assert "*[Used: Read, Edit]*" in md


def test_render_merges_consecutive_tool_calls():
    """Multiple consecutive tool-only messages should merge into one line."""
    session = _make_session()
    for _ in range(4):
        session.messages.append(
            Message(role="assistant", content="",
                    timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                    tool_calls=[{"name": "Bash", "input": {"command": "ls"}}])
        )
    md = render_session_markdown(session)
    assert "Bash ×4" in md
    # Should NOT have 4 separate tool lines
    assert md.count("[Used:") == 1


def test_render_merges_mixed_consecutive_tools():
    """Consecutive tool-only messages with different tools merge into one."""
    session = _make_session()
    session.messages.append(
        Message(role="assistant", content="",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[{"name": "Read", "input": {}}])
    )
    session.messages.append(
        Message(role="assistant", content="",
                timestamp=datetime(2026, 3, 10, 10, 33, tzinfo=timezone.utc),
                tool_calls=[{"name": "Read", "input": {}}])
    )
    session.messages.append(
        Message(role="assistant", content="",
                timestamp=datetime(2026, 3, 10, 10, 34, tzinfo=timezone.utc),
                tool_calls=[{"name": "Edit", "input": {}}])
    )
    md = render_session_markdown(session)
    assert "*[Used: Read ×2, Edit]*" in md


def test_render_tool_group_flushed_before_text():
    """Pending tool group should flush before the next text message."""
    session = _make_session()
    session.messages.append(
        Message(role="assistant", content="",
                timestamp=datetime(2026, 3, 10, 10, 32, tzinfo=timezone.utc),
                tool_calls=[{"name": "Bash", "input": {}}])
    )
    session.messages.append(
        Message(role="assistant", content="",
                timestamp=datetime(2026, 3, 10, 10, 33, tzinfo=timezone.utc),
                tool_calls=[{"name": "Bash", "input": {}}])
    )
    session.messages.append(
        Message(role="assistant", content="Build passed!",
                timestamp=datetime(2026, 3, 10, 10, 34, tzinfo=timezone.utc),
                tool_calls=[])
    )
    md = render_session_markdown(session)
    # Tool group should appear before "Build passed!"
    tool_pos = md.index("Bash ×2")
    text_pos = md.index("Build passed!")
    assert tool_pos < text_pos
