"""Tests for zoo import --quiet flag."""
import json
from pathlib import Path
from unittest.mock import patch
from typer.testing import CliRunner
from session_zoo.cli import app

runner = CliRunner()


def _make_session(tmp_path, session_id, cwd):
    project_dir = tmp_path / ".claude" / "projects" / "-home-user-myapp"
    project_dir.mkdir(parents=True, exist_ok=True)
    msgs = [
        {
            "type": "user", "sessionId": session_id,
            "cwd": cwd, "gitBranch": "main", "version": "2.1.72",
            "message": {"role": "user", "content": "hello"},
            "timestamp": "2026-03-10T10:00:00.000Z", "uuid": "u1",
        },
        {
            "type": "assistant", "sessionId": session_id,
            "cwd": cwd, "gitBranch": "main", "version": "2.1.72",
            "message": {
                "model": "claude-opus-4-6", "role": "assistant",
                "content": [{"type": "text", "text": "hi"}],
                "usage": {"input_tokens": 10, "output_tokens": 5,
                          "cache_creation_input_tokens": 0,
                          "cache_read_input_tokens": 0},
            },
            "timestamp": "2026-03-10T10:01:00.000Z", "uuid": "u2",
        },
    ]
    f = project_dir / f"{session_id}.jsonl"
    f.write_text("\n".join(json.dumps(m) for m in msgs) + "\n")
    return f


def _run(args, config_dir, claude_dir):
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        return runner.invoke(app, args)


def test_quiet_no_output_when_nothing_new(tmp_path):
    config_dir = tmp_path / "cfg"
    claude_dir = tmp_path / ".claude"
    _make_session(tmp_path, "s1", "/home/user/myapp")
    _run(["init"], config_dir, claude_dir)
    _run(["import"], config_dir, claude_dir)
    # Second import with --quiet: nothing new → no output
    result = _run(["import", "--quiet"], config_dir, claude_dir)
    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_quiet_shows_output_when_new_sessions(tmp_path):
    config_dir = tmp_path / "cfg"
    claude_dir = tmp_path / ".claude"
    _make_session(tmp_path, "s1", "/home/user/myapp")
    _run(["init"], config_dir, claude_dir)
    result = _run(["import", "--quiet"], config_dir, claude_dir)
    assert result.exit_code == 0
    assert "Imported: 1" in result.stdout


def test_normal_import_always_shows_output(tmp_path):
    config_dir = tmp_path / "cfg"
    claude_dir = tmp_path / ".claude"
    _make_session(tmp_path, "s1", "/home/user/myapp")
    _run(["init"], config_dir, claude_dir)
    _run(["import"], config_dir, claude_dir)
    # Without --quiet: always shows output
    result = _run(["import"], config_dir, claude_dir)
    assert "Imported: 0" in result.stdout
