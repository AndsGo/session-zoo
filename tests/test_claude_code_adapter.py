from datetime import datetime, timezone
from pathlib import Path

from session_zoo.adapters.claude_code import ClaudeCodeAdapter
from session_zoo.models import Session


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
    # 使用 PurePosixPath 格式比较，避免 Windows 反斜杠问题
    assert restore_path.as_posix().endswith(
        ".claude/projects/-home-user-my-project/test-session-001.jsonl"
    )


def test_encode_project_path_posix(tmp_path):
    adapter = ClaudeCodeAdapter(claude_dir=tmp_path)
    assert adapter._encode_project_path("/home/user/my-project") == "-home-user-my-project"


def test_encode_project_path_windows(tmp_path):
    # 回归测试：Windows 盘符冒号必须替换为 "-"，而不是删除。
    # Claude Code 真正的目录名是 "D--work-session-zoo"（双横线来自 ":\"），
    # 旧实现会生成 "-D-work-session-zoo"，导致 /resume 找不到 restore 出来的会话。
    adapter = ClaudeCodeAdapter(claude_dir=tmp_path)
    assert adapter._encode_project_path("D:\\work\\session-zoo") == "D--work-session-zoo"
    assert adapter._encode_project_path("C:\\Users\\Admin\\proj") == "C--Users-Admin-proj"


def test_get_restore_path_windows_cwd(tmp_path):
    # 回归测试：cwd 为 Windows 路径时，restore 应该写到 Claude Code 实际扫描的目录，
    # 即 ~/.claude/projects/D--work-session-zoo/<id>.jsonl
    adapter = ClaudeCodeAdapter(claude_dir=tmp_path / ".claude")
    session = Session(
        id="abc123",
        tool="claude-code",
        project="session-zoo",
        source_path=Path("ignored.jsonl"),
        started_at=None,
        ended_at=None,
        model="",
        total_tokens=0,
        cwd="D:\\work\\session-zoo",
    )
    restore_path = adapter.get_restore_path(session)
    assert restore_path.as_posix().endswith(
        ".claude/projects/D--work-session-zoo/abc123.jsonl"
    )


def test_extract_native_title_returns_ai_title(sample_claude_session_with_ai_title):
    adapter = ClaudeCodeAdapter(
        claude_dir=sample_claude_session_with_ai_title / ".claude"
    )
    paths = adapter.discover()
    title = adapter.extract_native_title(paths[0])
    # Must return the LAST ai-title record, not the first.
    assert title == "Newest title"


def test_extract_native_title_returns_none_when_absent(sample_claude_session):
    adapter = ClaudeCodeAdapter(
        claude_dir=sample_claude_session / ".claude"
    )
    paths = adapter.discover()
    assert adapter.extract_native_title(paths[0]) is None


def test_extract_native_title_handles_corrupted_lines(tmp_path):
    """Single bad line should not abort scanning."""
    project_dir = tmp_path / ".claude" / "projects" / "-x-y"
    project_dir.mkdir(parents=True)
    f = project_dir / "abc.jsonl"
    f.write_text(
        '{"type":"user","message":{"role":"user","content":"hi"}}\n'
        'NOT JSON AT ALL\n'
        '{"type":"ai-title","aiTitle":"After bad line","sessionId":"abc"}\n',
        encoding="utf-8",
    )
    adapter = ClaudeCodeAdapter(claude_dir=tmp_path / ".claude")
    assert adapter.extract_native_title(f) == "After bad line"
