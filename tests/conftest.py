import json
from pathlib import Path
import pytest


SAMPLE_MESSAGES = [
    {
        "type": "user",
        "sessionId": "test-session-001",
        "cwd": "/home/user/my-project",
        "gitBranch": "main",
        "version": "2.1.72",
        "message": {"role": "user", "content": "Fix the login bug"},
        "timestamp": "2026-03-10T10:30:00.000Z",
        "uuid": "msg-001",
        "parentUuid": None,
    },
    {
        "type": "assistant",
        "sessionId": "test-session-001",
        "cwd": "/home/user/my-project",
        "gitBranch": "main",
        "version": "2.1.72",
        "message": {
            "model": "claude-opus-4-6",
            "role": "assistant",
            "content": [{"type": "text", "text": "I'll fix the login bug."}],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
        "timestamp": "2026-03-10T10:31:00.000Z",
        "uuid": "msg-002",
        "parentUuid": "msg-001",
    },
    {
        "type": "assistant",
        "sessionId": "test-session-001",
        "cwd": "/home/user/my-project",
        "gitBranch": "main",
        "version": "2.1.72",
        "message": {
            "model": "claude-opus-4-6",
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool-001",
                    "name": "Edit",
                    "input": {"file_path": "/home/user/my-project/src/login.py"},
                },
                {"type": "text", "text": "Fixed it."},
            ],
            "usage": {"input_tokens": 200, "output_tokens": 80,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        },
        "timestamp": "2026-03-10T10:35:00.000Z",
        "uuid": "msg-003",
        "parentUuid": "msg-002",
    },
    {
        "type": "progress",
        "sessionId": "test-session-001",
        "data": {"type": "hook_progress"},
        "timestamp": "2026-03-10T10:30:00.000Z",
        "uuid": "prog-001",
    },
    {
        "type": "system",
        "sessionId": "test-session-001",
        "slug": "tool_result",
        "timestamp": "2026-03-10T10:32:00.000Z",
        "uuid": "sys-001",
    },
]


@pytest.fixture
def sample_claude_session(tmp_path) -> Path:
    """Create a realistic Claude Code session directory structure."""
    project_dir = tmp_path / ".claude" / "projects" / "-home-user-my-project"
    project_dir.mkdir(parents=True)
    session_file = project_dir / "test-session-001.jsonl"
    with open(session_file, "w") as f:
        for msg in SAMPLE_MESSAGES:
            f.write(json.dumps(msg) + "\n")
    return tmp_path


@pytest.fixture
def sample_claude_session_with_ai_title(tmp_path) -> Path:
    """Same as sample_claude_session, but the jsonl also contains two ai-title
    records — the most recent one being the canonical title."""
    project_dir = tmp_path / ".claude" / "projects" / "-home-user-my-project"
    project_dir.mkdir(parents=True)
    session_file = project_dir / "test-session-001.jsonl"
    extra = [
        {"type": "ai-title", "aiTitle": "Older title", "sessionId": "test-session-001"},
        *SAMPLE_MESSAGES,
        {"type": "ai-title", "aiTitle": "Newest title", "sessionId": "test-session-001"},
    ]
    with open(session_file, "w", encoding="utf-8") as f:
        for msg in extra:
            f.write(json.dumps(msg) + "\n")
    return tmp_path
