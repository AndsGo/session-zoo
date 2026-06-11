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
