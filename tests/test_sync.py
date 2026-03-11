import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from session_zoom.sync import (
    init_repo, copy_raw_session, write_meta_json,
    write_session_markdown, commit_and_push, pull_repo,
    list_raw_sessions,
)


def test_copy_raw_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = tmp_path / "source.jsonl"
    source.write_text('{"type":"user"}\n')

    dest = copy_raw_session(
        repo_dir=repo,
        source_path=source,
        tool="claude-code",
        project="my-project",
        session_id="abc123",
    )
    assert dest.exists()
    assert dest == repo / "raw" / "claude-code" / "my-project" / "abc123.jsonl"
    assert dest.read_text() == '{"type":"user"}\n'


def test_write_meta_json(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    meta = {
        "session_id": "abc123",
        "tool": "claude-code",
        "project": "my-project",
        "summary": "Fixed a bug",
        "tags": ["bugfix"],
    }
    path = write_meta_json(
        repo_dir=repo,
        tool="claude-code",
        project="my-project",
        session_id="abc123",
        meta=meta,
    )
    assert path.exists()
    assert path == repo / "raw" / "claude-code" / "my-project" / "abc123.meta.json"
    loaded = json.loads(path.read_text())
    assert loaded["summary"] == "Fixed a bug"


def test_write_session_markdown(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = write_session_markdown(
        repo_dir=repo,
        project="my-project",
        date="2026-03-10",
        tool="claude-code",
        session_id="abc123",
        content="# Test Summary\n\nContent here.",
    )
    assert path.exists()
    assert path == repo / "sessions" / "my-project" / "2026-03-10" / "claude-code" / "abc123.md"


def test_list_raw_sessions(tmp_path):
    repo = tmp_path / "repo"
    raw_dir = repo / "raw" / "claude-code" / "my-project"
    raw_dir.mkdir(parents=True)
    (raw_dir / "s1.jsonl").write_text("{}\n")
    (raw_dir / "s1.meta.json").write_text("{}")
    (raw_dir / "s2.jsonl").write_text("{}\n")

    sessions = list_raw_sessions(repo)
    assert len(sessions) == 2
    assert sessions[0]["session_id"] in ("s1", "s2")
