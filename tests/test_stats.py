"""Tests for per-model cache usage stats: adapter aggregation, DB storage, CLI."""
import json
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from session_zoo.adapters.claude_code import ClaudeCodeAdapter
from session_zoo.cli import app
from session_zoo.db import SessionDB

runner = CliRunner()


def _assistant(msg_id, model, inp, cache_read, cache_creation, out, uuid,
               sidechain=False):
    return {
        "type": "assistant",
        "sessionId": "s-cache",
        "isSidechain": sidechain,
        "cwd": "/home/user/proj",
        "message": {
            "id": msg_id,
            "model": model,
            "role": "assistant",
            "content": [{"type": "text", "text": "ok"}],
            "usage": {
                "input_tokens": inp,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
                "output_tokens": out,
            },
        },
        "timestamp": "2026-06-11T10:00:00.000Z",
        "uuid": uuid,
    }


CACHE_RECORDS = [
    {
        "type": "user",
        "sessionId": "s-cache",
        "cwd": "/home/user/proj",
        "message": {"role": "user", "content": "hi"},
        "timestamp": "2026-06-11T09:59:00.000Z",
        "uuid": "u-1",
    },
    # One assistant message split into two records (same message.id, same
    # usage object) — must be counted exactly once.
    _assistant("msg_A", "claude-fable-5", 100, 900, 50, 40, "a-1"),
    _assistant("msg_A", "claude-fable-5", 100, 900, 50, 40, "a-2"),
    # A second model on a sidechain (subagent) — real API usage, included.
    _assistant("msg_B", "claude-haiku-4-5", 10, 0, 30, 5, "a-3", sidechain=True),
    # Synthetic placeholder message — excluded from per-model stats.
    _assistant("msg_C", "<synthetic>", 1, 2, 3, 4, "a-4"),
]


@pytest.fixture
def cache_session_file(tmp_path) -> Path:
    f = tmp_path / "s-cache.jsonl"
    with open(f, "w", encoding="utf-8") as fh:
        for r in CACHE_RECORDS:
            fh.write(json.dumps(r) + "\n")
    return f


def test_parse_aggregates_usage_per_model(cache_session_file):
    session = ClaudeCodeAdapter().parse(cache_session_file)
    assert session.model_usage["claude-fable-5"] == {
        "input": 100, "cache_read": 900, "cache_creation": 50, "output": 40,
    }
    assert session.model_usage["claude-haiku-4-5"] == {
        "input": 10, "cache_read": 0, "cache_creation": 30, "output": 5,
    }


def test_parse_excludes_synthetic_model(cache_session_file):
    session = ClaudeCodeAdapter().parse(cache_session_file)
    assert "<synthetic>" not in session.model_usage


def test_parse_dedupes_total_tokens_by_message_id(cache_session_file):
    session = ClaudeCodeAdapter().parse(cache_session_file)
    # msg_A once: 100+900+50+40 = 1090; msg_B: 10+0+30+5 = 45;
    # msg_C (synthetic) still counts toward totals: 1+2+3+4 = 10.
    assert session.total_tokens == 1090 + 45 + 10


def test_parse_records_without_message_id_each_count(sample_claude_session):
    # conftest fixture records carry no message.id → no dedup, totals unchanged.
    path = (sample_claude_session / ".claude" / "projects"
            / "-home-user-my-project" / "test-session-001.jsonl")
    session = ClaudeCodeAdapter().parse(path)
    assert session.total_tokens == 430  # 100+50 + 200+80
    assert session.model_usage["claude-opus-4-6"] == {
        "input": 300, "cache_read": 0, "cache_creation": 0, "output": 130,
    }


# ---------- DB ----------

@pytest.fixture
def db(tmp_path):
    d = SessionDB(tmp_path / "index.db")
    d.init()
    return d


def _add_session(db, id, project="proj-a", tool="claude-code",
                 started="2026-06-01T10:00:00+00:00"):
    db.upsert_session(
        id=id, tool=tool, project=project, source_path=f"/tmp/{id}.jsonl",
        started_at=datetime.fromisoformat(started), ended_at=None,
        model="claude-fable-5", total_tokens=0, message_count=0,
    )


def test_replace_model_usage_is_idempotent(db):
    _add_session(db, "s1")
    db.replace_model_usage("s1", {
        "claude-fable-5": {"input": 100, "cache_read": 900, "cache_creation": 50, "output": 40},
    })
    db.replace_model_usage("s1", {
        "claude-fable-5": {"input": 200, "cache_read": 800, "cache_creation": 0, "output": 10},
    })
    rows = db.get_model_usage("s1")
    assert rows == [{
        "model": "claude-fable-5", "input_tokens": 200, "cache_read_tokens": 800,
        "cache_creation_tokens": 0, "output_tokens": 10,
    }]


def test_aggregate_model_usage_groups_and_filters(db):
    _add_session(db, "s1", project="proj-a")
    _add_session(db, "s2", project="proj-b")
    db.replace_model_usage("s1", {
        "claude-fable-5": {"input": 100, "cache_read": 900, "cache_creation": 0, "output": 40},
    })
    db.replace_model_usage("s2", {
        "claude-fable-5": {"input": 50, "cache_read": 100, "cache_creation": 0, "output": 20},
        "claude-haiku-4-5": {"input": 10, "cache_read": 0, "cache_creation": 0, "output": 5},
    })
    by_model = {r["model"]: r for r in db.aggregate_model_usage()}
    assert by_model["claude-fable-5"]["sessions"] == 2
    assert by_model["claude-fable-5"]["input_tokens"] == 150
    assert by_model["claude-fable-5"]["cache_read_tokens"] == 1000
    assert by_model["claude-haiku-4-5"]["sessions"] == 1

    rows_a = db.aggregate_model_usage(project="proj-a")
    assert len(rows_a) == 1
    assert rows_a[0]["input_tokens"] == 100


def test_model_usage_cascade_delete(db):
    _add_session(db, "s1")
    db.replace_model_usage("s1", {
        "claude-fable-5": {"input": 1, "cache_read": 0, "cache_creation": 0, "output": 1},
    })
    db.delete_session("s1")
    assert db.get_model_usage("s1") == []


# ---------- CLI ----------

from session_zoo.cli import _format_hit_rate


def test_format_hit_rate():
    assert _format_hit_rate({
        "input_tokens": 100, "cache_read_tokens": 900, "cache_creation_tokens": 0,
    }) == "90.0%"


def test_format_hit_rate_zero_denominator():
    assert _format_hit_rate({
        "input_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0,
    }) == "?"


@pytest.fixture
def cache_claude_env(tmp_path, cache_session_file):
    """A fake ~/.claude + config dir housing the cache fixture session."""
    claude_dir = tmp_path / ".claude"
    proj = claude_dir / "projects" / "-home-user-proj"
    proj.mkdir(parents=True)
    shutil.copy2(cache_session_file, proj / "s-cache.jsonl")
    config_dir = tmp_path / "sz-config"
    return config_dir, claude_dir


def test_stats_command_global_and_session(cache_claude_env):
    config_dir, claude_dir = cache_claude_env
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        assert runner.invoke(app, ["init", "--skip-skills", "--skip-hooks"]).exit_code == 0
        assert runner.invoke(app, ["import"]).exit_code == 0

        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0, result.stdout
        # Rich may truncate cell values; assert on stable prefixes.
        assert "claude-fa" in result.stdout
        assert "85.7%" in result.stdout  # 900 / (100+900+50)

        result = runner.invoke(app, ["stats", "s-cache"])
        assert result.exit_code == 0, result.stdout
        assert "claude-ha" in result.stdout


def test_stats_backfill(cache_claude_env):
    config_dir, claude_dir = cache_claude_env
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        assert runner.invoke(app, ["init", "--skip-skills", "--skip-hooks"]).exit_code == 0
        assert runner.invoke(app, ["import"]).exit_code == 0

        # Simulate a pre-upgrade DB: usage rows missing.
        db = SessionDB(config_dir / "index.db")
        db.init()
        db.replace_model_usage("s-cache", {})
        assert db.get_model_usage("s-cache") == []

        result = runner.invoke(app, ["stats", "--backfill"])
        assert result.exit_code == 0, result.stdout
        rows = db.get_model_usage("s-cache")
        assert {r["model"] for r in rows} == {"claude-fable-5", "claude-haiku-4-5"}


# ---------- sync meta.json / reindex ----------

BASE_META = {
    "started_at": "2026-06-11T10:00:00+00:00",
    "ended_at": "2026-06-11T10:05:00+00:00",
    "model": "claude-fable-5",
    "total_tokens": 1145,
    "message_count": 4,
}


def _make_repo_entry(repo_dir, session_id, records, meta):
    raw_dir = repo_dir / "raw" / "claude-code" / "proj"
    raw_dir.mkdir(parents=True, exist_ok=True)
    jsonl = raw_dir / f"{session_id}.jsonl"
    with open(jsonl, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    (raw_dir / f"{session_id}.meta.json").write_text(
        json.dumps(meta), encoding="utf-8")


def test_reindex_restores_model_usage_from_meta(tmp_path):
    config_dir = tmp_path / "sz-config"
    repo_dir = config_dir / "repo"
    meta = dict(BASE_META, model_usage=[{
        "model": "claude-fable-5", "input_tokens": 100, "cache_read_tokens": 900,
        "cache_creation_tokens": 50, "output_tokens": 40,
    }])
    _make_repo_entry(repo_dir, "s-meta", CACHE_RECORDS, meta)

    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=tmp_path / ".claude"):
        assert runner.invoke(app, ["init", "--skip-skills", "--skip-hooks"]).exit_code == 0
        result = runner.invoke(app, ["reindex"])
        assert result.exit_code == 0, result.stdout

    db = SessionDB(config_dir / "index.db")
    db.init()
    rows = db.get_model_usage("s-meta")
    assert rows == [{
        "model": "claude-fable-5", "input_tokens": 100, "cache_read_tokens": 900,
        "cache_creation_tokens": 50, "output_tokens": 40,
    }]


def test_reindex_falls_back_to_jsonl_when_meta_lacks_usage(tmp_path):
    config_dir = tmp_path / "sz-config"
    repo_dir = config_dir / "repo"
    # Old-format meta: no model_usage key → reindex re-parses the JSONL.
    _make_repo_entry(repo_dir, "s-old", CACHE_RECORDS, dict(BASE_META))

    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=tmp_path / ".claude"):
        assert runner.invoke(app, ["init", "--skip-skills", "--skip-hooks"]).exit_code == 0
        result = runner.invoke(app, ["reindex"])
        assert result.exit_code == 0, result.stdout

    db = SessionDB(config_dir / "index.db")
    db.init()
    rows = db.get_model_usage("s-old")
    assert {r["model"] for r in rows} == {"claude-fable-5", "claude-haiku-4-5"}
