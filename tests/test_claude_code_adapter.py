from datetime import datetime, timezone
from session_zoom.adapters.claude_code import ClaudeCodeAdapter


def test_discover_finds_sessions(sample_claude_session):
    adapter = ClaudeCodeAdapter(
        claude_dir=sample_claude_session / ".claude"
    )
    paths = adapter.discover()
    assert len(paths) == 1
    assert paths[0].name == "test-session-001.jsonl"


def test_discover_filters_by_project(sample_claude_session):
    adapter = ClaudeCodeAdapter(
        claude_dir=sample_claude_session / ".claude"
    )
    paths = adapter.discover(project="my-project")
    assert len(paths) == 1

    paths = adapter.discover(project="other-project")
    assert len(paths) == 0


def test_parse_session(sample_claude_session):
    adapter = ClaudeCodeAdapter(
        claude_dir=sample_claude_session / ".claude"
    )
    paths = adapter.discover()
    session = adapter.parse(paths[0])

    assert session.id == "test-session-001"
    assert session.tool == "claude-code"
    assert session.project == "my-project"
    assert session.model == "claude-opus-4-6"
    assert session.git_branch == "main"
    assert session.cwd == "/home/user/my-project"
    assert session.started_at == datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc)
    assert session.ended_at == datetime(2026, 3, 10, 10, 35, tzinfo=timezone.utc)

    # Only user + assistant messages, not progress/system
    assert len(session.messages) == 3
    assert session.messages[0].role == "user"
    assert session.messages[0].content == "Fix the login bug"

    # Token totals
    assert session.total_tokens == 430  # 100+50 + 200+80

    # Tool calls extracted
    assert len(session.messages[2].tool_calls) == 1
    assert session.messages[2].tool_calls[0]["name"] == "Edit"


def test_get_restore_path(sample_claude_session):
    adapter = ClaudeCodeAdapter(
        claude_dir=sample_claude_session / ".claude"
    )
    paths = adapter.discover()
    session = adapter.parse(paths[0])
    restore_path = adapter.get_restore_path(session)
    assert str(restore_path).endswith(
        ".claude/projects/-home-user-my-project/test-session-001.jsonl"
    )
