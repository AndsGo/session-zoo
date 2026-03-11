# Session Zoon Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `zoom` CLI that imports Claude Code sessions into a local SQLite index, generates AI summaries, and syncs everything to GitHub with cross-device restore support.

**Architecture:** Local SQLite index + Adapter pattern. GitHub repo is source of truth (raw JSONL + meta.json + Markdown summaries). SQLite is a rebuildable local cache. `~/.claude/` files can be restored from GitHub for `/resume` support.

**Tech Stack:** Python 3.12+, Typer (CLI), SQLite (stdlib), Anthropic SDK (AI summaries), subprocess git, tomllib/tomli_w (config)

---

## File Structure

```
session-zoon/
├── pyproject.toml                    # Package config, entry point, dependencies
├── src/session_zoon/
│   ├── __init__.py                   # Version string
│   ├── cli.py                        # Typer app, all command definitions
│   ├── config.py                     # Config read/write (~/.session-zoon/config.toml)
│   ├── db.py                         # SQLite index: create tables, CRUD sessions/tags
│   ├── models.py                     # Session, Message dataclasses
│   ├── summarizer.py                 # AI summary generation via Anthropic API
│   ├── renderer.py                   # Markdown rendering from Session + summary
│   ├── sync.py                       # Git operations: clone, commit, push, pull
│   └── adapters/
│       ├── __init__.py               # AdapterRegistry, get_adapter()
│       └── claude_code.py            # Claude Code: discover, parse, get_restore_path
└── tests/
    ├── conftest.py                   # Shared fixtures (tmp dirs, sample JSONL)
    ├── test_models.py
    ├── test_config.py
    ├── test_db.py
    ├── test_claude_code_adapter.py
    ├── test_renderer.py
    ├── test_summarizer.py
    ├── test_sync.py
    └── test_cli.py
```

---

## Chunk 1: Project Bootstrap + Data Models + Config

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/session_zoon/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "session-zoon"
version = "0.1.0"
description = "AI development session recorder — save and sync sessions to GitHub"
requires-python = ">=3.12"
dependencies = [
    "typer>=0.15.0",
    "anthropic>=0.52.0",
    "rich>=13.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-tmp-files>=0.0.2",
]

[project.scripts]
zoom = "session_zoon.cli:app"
```

- [ ] **Step 2: Create __init__.py**

```python
__version__ = "0.1.0"
```

- [ ] **Step 3: Install in dev mode**

Run: `cd /home/openclaw/work/tools/session_zoon && pip install -e ".[dev]"`
Expected: Successfully installed session-zoon

- [ ] **Step 4: Verify entry point**

Run: `zoom --help`
Expected: Error about missing cli module (expected — we haven't created it yet)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/session_zoon/__init__.py
git commit -m "feat: project scaffold with pyproject.toml"
```

### Task 2: Data Models

**Files:**
- Create: `src/session_zoon/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test for Session and Message models**

```python
# tests/test_models.py
from datetime import datetime, timezone
from pathlib import Path
from session_zoon.models import Session, Message


def test_message_creation():
    msg = Message(
        role="user",
        content="Fix the bug",
        timestamp=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
        tool_calls=[],
        token_usage=None,
    )
    assert msg.role == "user"
    assert msg.content == "Fix the bug"


def test_session_creation():
    msg = Message(
        role="user",
        content="Hello",
        timestamp=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
        tool_calls=[],
        token_usage=None,
    )
    session = Session(
        id="abc123",
        tool="claude-code",
        project="my-project",
        source_path=Path("/home/user/.claude/projects/abc/123.jsonl"),
        started_at=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
        ended_at=datetime(2026, 3, 10, 11, 45, tzinfo=timezone.utc),
        model="claude-opus-4-6",
        total_tokens=52340,
        messages=[msg],
        git_branch="fix/xss",
        cwd="/home/user/my-project",
    )
    assert session.id == "abc123"
    assert session.tool == "claude-code"
    assert session.message_count == 1
    assert session.duration_minutes == 75


def test_session_duration_none_when_missing_end():
    session = Session(
        id="abc",
        tool="claude-code",
        project="test",
        source_path=Path("/tmp/test.jsonl"),
        started_at=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc),
        ended_at=None,
        model="claude-opus-4-6",
        total_tokens=0,
        messages=[],
        git_branch=None,
        cwd=None,
    )
    assert session.duration_minutes is None
    assert session.message_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement models**

```python
# src/session_zoon/models.py
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Message:
    role: str
    content: str
    timestamp: datetime
    tool_calls: list[dict] = field(default_factory=list)
    token_usage: dict | None = None


@dataclass
class Session:
    id: str
    tool: str
    project: str
    source_path: Path
    started_at: datetime
    ended_at: datetime | None
    model: str
    total_tokens: int
    messages: list[Message] = field(default_factory=list)
    git_branch: str | None = None
    cwd: str | None = None

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def duration_minutes(self) -> int | None:
        if self.ended_at is None or self.started_at is None:
            return None
        delta = self.ended_at - self.started_at
        return int(delta.total_seconds() / 60)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_models.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/session_zoon/models.py tests/test_models.py
git commit -m "feat: add Session and Message data models"
```

### Task 3: Config Management

**Files:**
- Create: `src/session_zoon/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
from pathlib import Path
from session_zoon.config import Config, load_config, save_config


def test_default_config():
    cfg = Config()
    assert cfg.repo is None
    assert cfg.ai_key is None
    assert cfg.ai_model == "claude-haiku-4-5-20251001"


def test_save_and_load_config(tmp_path):
    config_path = tmp_path / "config.toml"
    cfg = Config(repo="https://github.com/user/sessions.git", ai_model="claude-haiku-4-5-20251001")
    save_config(cfg, config_path)

    loaded = load_config(config_path)
    assert loaded.repo == "https://github.com/user/sessions.git"
    assert loaded.ai_model == "claude-haiku-4-5-20251001"
    assert loaded.ai_key is None


def test_load_missing_config_returns_default(tmp_path):
    config_path = tmp_path / "nonexistent.toml"
    cfg = load_config(config_path)
    assert cfg.repo is None


def test_config_dir_default():
    cfg = Config()
    assert cfg.config_dir == Path.home() / ".session-zoon"
    assert cfg.db_path == Path.home() / ".session-zoon" / "index.db"
    assert cfg.config_file == Path.home() / ".session-zoon" / "config.toml"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement config**

```python
# src/session_zoon/config.py
from dataclasses import dataclass, field
from pathlib import Path
import tomllib


@dataclass
class Config:
    repo: str | None = None
    ai_key: str | None = None
    ai_model: str = "claude-haiku-4-5-20251001"
    config_dir: Path = field(default_factory=lambda: Path.home() / ".session-zoon")

    @property
    def db_path(self) -> Path:
        return self.config_dir / "index.db"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def repo_dir(self) -> Path:
        return self.config_dir / "repo"


def load_config(path: Path | None = None) -> Config:
    if path is None:
        path = Config().config_file
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Config(
        repo=data.get("repo"),
        ai_key=data.get("ai_key"),
        ai_model=data.get("ai_model", "claude-haiku-4-5-20251001"),
    )


def save_config(cfg: Config, path: Path | None = None) -> None:
    if path is None:
        path = cfg.config_file
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if cfg.repo:
        lines.append(f'repo = "{cfg.repo}"')
    if cfg.ai_key:
        lines.append(f'ai_key = "{cfg.ai_key}"')
    lines.append(f'ai_model = "{cfg.ai_model}"')
    path.write_text("\n".join(lines) + "\n")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_config.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/session_zoon/config.py tests/test_config.py
git commit -m "feat: add config management with TOML persistence"
```

---

## Chunk 2: SQLite Index + Claude Code Adapter

### Task 4: SQLite Database Layer

**Files:**
- Create: `src/session_zoon/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db.py
from datetime import datetime, timezone
from pathlib import Path
from session_zoon.db import SessionDB


def _make_db(tmp_path) -> SessionDB:
    return SessionDB(tmp_path / "test.db")


def test_create_tables(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    assert db.path.exists()


def test_upsert_and_get_session(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="abc123",
        tool="claude-code",
        project="my-project",
        source_path="/home/user/.claude/projects/abc/123.jsonl",
        started_at=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
        ended_at=datetime(2026, 3, 10, 11, 45, tzinfo=timezone.utc),
        model="claude-opus-4-6",
        total_tokens=52340,
        message_count=28,
    )
    row = db.get_session("abc123")
    assert row is not None
    assert row["tool"] == "claude-code"
    assert row["project"] == "my-project"
    assert row["total_tokens"] == 52340
    assert row["sync_status"] == "pending"


def test_list_sessions_filters(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    for i, proj in enumerate(["proj-a", "proj-a", "proj-b"]):
        db.upsert_session(
            id=f"s{i}",
            tool="claude-code",
            project=proj,
            source_path=f"/tmp/{i}.jsonl",
            started_at=datetime(2026, 3, 10 + i, 10, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 3, 10 + i, 11, 0, tzinfo=timezone.utc),
            model="claude-opus-4-6",
            total_tokens=1000 * i,
            message_count=10,
        )
    assert len(db.list_sessions()) == 3
    assert len(db.list_sessions(project="proj-a")) == 2
    assert len(db.list_sessions(project="proj-b")) == 1


def test_tags(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="s1", tool="claude-code", project="p",
        source_path="/tmp/s1.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    db.add_tags("s1", ["bugfix", "security"])
    assert db.get_tags("s1") == ["bugfix", "security"]

    db.remove_tag("s1", "bugfix")
    assert db.get_tags("s1") == ["security"]


def test_update_summary(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="s1", tool="claude-code", project="p",
        source_path="/tmp/s1.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    db.update_summary("s1", "Fixed XSS vulnerability")
    row = db.get_session("s1")
    assert row["summary"] == "Fixed XSS vulnerability"


def test_update_sync_status(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="s1", tool="claude-code", project="p",
        source_path="/tmp/s1.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    assert db.get_session("s1")["sync_status"] == "pending"
    db.update_sync_status("s1", "synced")
    assert db.get_session("s1")["sync_status"] == "synced"


def test_delete_session(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="s1", tool="claude-code", project="p",
        source_path="/tmp/s1.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    db.add_tags("s1", ["tag1"])
    db.delete_session("s1")
    assert db.get_session("s1") is None
    assert db.get_tags("s1") == []


def test_list_sessions_by_tag(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    for i in range(3):
        db.upsert_session(
            id=f"s{i}", tool="claude-code", project="p",
            source_path=f"/tmp/{i}.jsonl",
            started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
            ended_at=None, model="m", total_tokens=0, message_count=0,
        )
    db.add_tags("s0", ["bugfix"])
    db.add_tags("s1", ["bugfix", "feature"])
    assert len(db.list_sessions(tag="bugfix")) == 2
    assert len(db.list_sessions(tag="feature")) == 1


def test_list_all_tags(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    db.upsert_session(
        id="s1", tool="claude-code", project="p",
        source_path="/tmp/s1.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    db.upsert_session(
        id="s2", tool="claude-code", project="p",
        source_path="/tmp/s2.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )
    db.add_tags("s1", ["bugfix", "security"])
    db.add_tags("s2", ["bugfix"])
    tags = db.list_all_tags()
    assert tags == [("bugfix", 2), ("security", 1)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement db.py**

```python
# src/session_zoon/db.py
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class SessionDB:
    def __init__(self, path: Path):
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def init(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                tool TEXT NOT NULL,
                project TEXT NOT NULL,
                source_path TEXT NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                model TEXT,
                total_tokens INTEGER,
                message_count INTEGER,
                summary TEXT,
                sync_status TEXT DEFAULT 'pending',
                synced_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tags (
                session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                PRIMARY KEY (session_id, tag)
            );
        """)

    def upsert_session(self, *, id: str, tool: str, project: str,
                        source_path: str, started_at: datetime | None,
                        ended_at: datetime | None, model: str,
                        total_tokens: int, message_count: int) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO sessions (id, tool, project, source_path, started_at,
                   ended_at, model, total_tokens, message_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   tool=excluded.tool, project=excluded.project,
                   source_path=excluded.source_path,
                   started_at=excluded.started_at, ended_at=excluded.ended_at,
                   model=excluded.model, total_tokens=excluded.total_tokens,
                   message_count=excluded.message_count""",
            (id, tool, project, source_path,
             started_at.isoformat() if started_at else None,
             ended_at.isoformat() if ended_at else None,
             model, total_tokens, message_count),
        )
        conn.commit()

    def get_session(self, id: str) -> dict | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (id,)).fetchone()
        return dict(row) if row else None

    def list_sessions(self, *, project: str | None = None,
                      tag: str | None = None,
                      tool: str | None = None,
                      since: str | None = None,
                      status: str | None = None,
                      no_summary: bool = False) -> list[dict]:
        conn = self._get_conn()
        query = "SELECT DISTINCT s.* FROM sessions s"
        conditions = []
        params: list = []

        if tag:
            query += " JOIN tags t ON s.id = t.session_id"
            conditions.append("t.tag = ?")
            params.append(tag)
        if project:
            conditions.append("s.project = ?")
            params.append(project)
        if tool:
            conditions.append("s.tool = ?")
            params.append(tool)
        if since:
            conditions.append("s.started_at >= ?")
            params.append(since)
        if status:
            conditions.append("s.sync_status = ?")
            params.append(status)
        if no_summary:
            conditions.append("s.summary IS NULL")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY s.started_at DESC"

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def update_summary(self, id: str, summary: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE sessions SET summary = ?, sync_status = 'modified' WHERE id = ?",
            (summary, id),
        )
        conn.commit()

    def update_sync_status(self, id: str, status: str) -> None:
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat() if status == "synced" else None
        conn.execute(
            "UPDATE sessions SET sync_status = ?, synced_at = ? WHERE id = ?",
            (status, now, id),
        )
        conn.commit()

    def add_tags(self, session_id: str, tags: list[str]) -> None:
        conn = self._get_conn()
        for tag in tags:
            conn.execute(
                "INSERT OR IGNORE INTO tags (session_id, tag) VALUES (?, ?)",
                (session_id, tag),
            )
        conn.commit()

    def remove_tag(self, session_id: str, tag: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM tags WHERE session_id = ? AND tag = ?",
            (session_id, tag),
        )
        conn.commit()

    def get_tags(self, session_id: str) -> list[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT tag FROM tags WHERE session_id = ? ORDER BY tag",
            (session_id,),
        ).fetchall()
        return [r["tag"] for r in rows]

    def list_all_tags(self) -> list[tuple[str, int]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT tag, COUNT(*) as cnt FROM tags GROUP BY tag ORDER BY cnt DESC, tag",
        ).fetchall()
        return [(r["tag"], r["cnt"]) for r in rows]

    def delete_session(self, id: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM sessions WHERE id = ?", (id,))
        conn.commit()

    def session_exists(self, id: str) -> bool:
        return self.get_session(id) is not None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_db.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/session_zoon/db.py tests/test_db.py
git commit -m "feat: add SQLite database layer for session indexing"
```

### Task 5: Claude Code Adapter

**Files:**
- Create: `src/session_zoon/adapters/__init__.py`
- Create: `src/session_zoon/adapters/claude_code.py`
- Create: `tests/conftest.py`
- Create: `tests/test_claude_code_adapter.py`

- [ ] **Step 1: Create test fixtures with sample JSONL data**

This fixture creates a realistic Claude Code JSONL file based on the actual format observed in `~/.claude/projects/`:

```python
# tests/conftest.py
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
```

- [ ] **Step 2: Write failing tests for adapter**

```python
# tests/test_claude_code_adapter.py
from datetime import datetime, timezone
from session_zoon.adapters.claude_code import ClaudeCodeAdapter


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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_claude_code_adapter.py -v`
Expected: FAIL — ImportError

- [ ] **Step 4: Implement adapter registry**

```python
# src/session_zoon/adapters/__init__.py
from session_zoon.adapters.claude_code import ClaudeCodeAdapter

_ADAPTERS = {
    "claude-code": ClaudeCodeAdapter,
}


def get_adapter(name: str, **kwargs):
    cls = _ADAPTERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown adapter: {name}. Available: {list(_ADAPTERS.keys())}")
    return cls(**kwargs)


def list_adapters() -> list[str]:
    return list(_ADAPTERS.keys())
```

- [ ] **Step 5: Implement Claude Code adapter**

```python
# src/session_zoon/adapters/claude_code.py
import json
from datetime import datetime, timezone
from pathlib import Path

from session_zoon.models import Message, Session


class ClaudeCodeAdapter:
    name = "claude-code"

    def __init__(self, claude_dir: Path | None = None):
        self.claude_dir = claude_dir or Path.home() / ".claude"

    def discover(self, *, since: datetime | None = None,
                 project: str | None = None) -> list[Path]:
        projects_dir = self.claude_dir / "projects"
        if not projects_dir.exists():
            return []

        paths = []
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            if project and not self._match_project(project_dir.name, project):
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                if since and self._get_file_start_time(jsonl_file):
                    start = self._get_file_start_time(jsonl_file)
                    if start and start < since:
                        continue
                paths.append(jsonl_file)
        return sorted(paths)

    def parse(self, path: Path) -> Session:
        lines = path.read_text().strip().split("\n")
        records = [json.loads(line) for line in lines if line.strip()]

        session_id = None
        model = None
        git_branch = None
        cwd = None
        messages: list[Message] = []
        total_input = 0
        total_output = 0
        timestamps: list[datetime] = []

        for record in records:
            rec_type = record.get("type")
            ts_str = record.get("timestamp")
            if ts_str:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                timestamps.append(ts)

            if session_id is None:
                session_id = record.get("sessionId")
            if git_branch is None:
                git_branch = record.get("gitBranch")
            if cwd is None:
                cwd = record.get("cwd")

            if rec_type not in ("user", "assistant"):
                continue

            msg_data = record.get("message", {})
            role = msg_data.get("role", rec_type)
            content_raw = msg_data.get("content", "")

            # Extract text content
            if isinstance(content_raw, list):
                text_parts = [
                    c.get("text", "") for c in content_raw
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                content = "\n".join(text_parts)
            else:
                content = str(content_raw)

            # Extract tool calls
            tool_calls = []
            if isinstance(content_raw, list):
                for c in content_raw:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        tool_calls.append({
                            "id": c.get("id"),
                            "name": c.get("name"),
                            "input": c.get("input", {}),
                        })

            # Extract token usage
            usage = msg_data.get("usage")
            token_usage = None
            if usage:
                inp = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                out = usage.get("output_tokens", 0)
                total_input += inp
                total_output += out
                token_usage = {"input": inp, "output": out}

            # Extract model
            if model is None and msg_data.get("model"):
                model = msg_data["model"]

            messages.append(Message(
                role=role,
                content=content,
                timestamp=ts if ts_str else datetime.now(timezone.utc),
                tool_calls=tool_calls,
                token_usage=token_usage,
            ))

        # Derive project name from directory
        project_name = self._extract_project_name(path)

        return Session(
            id=session_id or path.stem,
            tool="claude-code",
            project=project_name,
            source_path=path,
            started_at=min(timestamps) if timestamps else None,
            ended_at=max(timestamps) if timestamps else None,
            model=model or "unknown",
            total_tokens=total_input + total_output,
            messages=messages,
            git_branch=git_branch if git_branch != "HEAD" else None,
            cwd=cwd,
        )

    def get_restore_path(self, session: Session) -> Path:
        encoded = self._encode_project_path(session.cwd or f"/unknown/{session.project}")
        return self.claude_dir / "projects" / encoded / f"{session.id}.jsonl"

    def _extract_project_name(self, path: Path) -> str:
        """Extract project name from the encoded directory name.
        Uses cwd from first JSONL record if available, otherwise
        takes the last path component from the encoded dir name."""
        dir_name = path.parent.name  # e.g., "-home-user-my-project"
        # Decode: "-home-user-my-project" → "/home/user/my-project"
        decoded = "/" + dir_name.lstrip("-").replace("-", "/")
        return Path(decoded).name  # "my-project"

    def _encode_project_path(self, cwd: str) -> str:
        # Claude Code encodes "/home/user/project" as "-home-user-project"
        return "-" + cwd.strip("/").replace("/", "-")

    def _match_project(self, dir_name: str, project: str) -> bool:
        return project.lower() in dir_name.lower()

    def _get_file_start_time(self, path: Path) -> datetime | None:
        try:
            with open(path) as f:
                first_line = f.readline()
            record = json.loads(first_line)
            ts_str = record.get("timestamp")
            if ts_str:
                return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (json.JSONDecodeError, OSError):
            pass
        return None
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_claude_code_adapter.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add src/session_zoon/adapters/ tests/conftest.py tests/test_claude_code_adapter.py
git commit -m "feat: add Claude Code adapter with discover/parse/restore"
```

---

## Chunk 3: Markdown Renderer + AI Summarizer

### Task 6: Markdown Renderer

**Files:**
- Create: `src/session_zoon/renderer.py`
- Create: `tests/test_renderer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_renderer.py
from datetime import datetime, timezone
from pathlib import Path
from session_zoon.models import Session, Message
from session_zoon.renderer import render_session_markdown


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
                    tool_calls=[{"name": "Edit", "input": {"file_path": "src/login.py"}}],
                    token_usage={"input": 100, "output": 50}),
        ],
        git_branch="fix/login",
        cwd="/home/user/my-project",
    )


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


def test_render_contains_conversation():
    md = render_session_markdown(_make_session())
    assert "Fix the login bug" in md
    assert "I'll fix it." in md


def test_render_contains_files():
    md = render_session_markdown(_make_session())
    assert "src/login.py" in md


def test_render_with_tags():
    md = render_session_markdown(_make_session(), tags=["bugfix", "security"])
    assert "`bugfix`" in md
    assert "`security`" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_renderer.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement renderer**

```python
# src/session_zoon/renderer.py
from session_zoon.models import Session


def render_session_markdown(session: Session, *,
                            summary: str | None = None,
                            tags: list[str] | None = None) -> str:
    lines: list[str] = []

    # Title
    title = summary.split("\n")[0] if summary else f"Session {session.id[:8]}"
    lines.append(f"# {title}")
    lines.append("")

    # Metadata table
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Session ID | {session.id} |")
    lines.append(f"| Tool | {session.tool} |")
    lines.append(f"| Model | {session.model} |")
    lines.append(f"| Project | {session.project} |")
    if session.git_branch:
        lines.append(f"| Branch | {session.git_branch} |")

    # Time
    if session.started_at and session.ended_at:
        start = session.started_at.strftime("%Y-%m-%d %H:%M")
        end = session.ended_at.strftime("%H:%M")
        duration = session.duration_minutes
        dur_str = f"{duration}m" if duration and duration < 60 else f"{duration // 60}h{duration % 60}m" if duration else ""
        lines.append(f"| Time | {start} → {end} ({dur_str}) |")
    elif session.started_at:
        lines.append(f"| Time | {session.started_at.strftime('%Y-%m-%d %H:%M')} |")

    lines.append(f"| Tokens | {session.total_tokens:,} |")
    lines.append(f"| Messages | {session.message_count} |")

    if tags:
        tag_str = " ".join(f"`{t}`" for t in tags)
        lines.append(f"| Tags | {tag_str} |")

    lines.append("")

    # Summary
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # Files touched (from tool calls)
    files = _extract_files(session)
    if files:
        lines.append("## Files")
        lines.append("")
        for f in files:
            lines.append(f"- {f}")
        lines.append("")

    # Conversation
    lines.append("## Conversation")
    lines.append("")
    for msg in session.messages:
        role = "User" if msg.role == "user" else "Assistant"
        content = msg.content.strip()
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"> **{role}:** {content}")
        lines.append(">")
    lines.append("")

    return "\n".join(lines)


def _extract_files(session: Session) -> list[str]:
    files = set()
    for msg in session.messages:
        for tc in msg.tool_calls:
            inp = tc.get("input", {})
            for key in ("file_path", "path", "filePath"):
                if key in inp:
                    files.add(inp[key])
    return sorted(files)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_renderer.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/session_zoon/renderer.py tests/test_renderer.py
git commit -m "feat: add Markdown renderer for session summaries"
```

### Task 7: AI Summarizer

**Files:**
- Create: `src/session_zoon/summarizer.py`
- Create: `tests/test_summarizer.py`

- [ ] **Step 1: Write failing tests (with mocked API)**

```python
# tests/test_summarizer.py
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from session_zoon.models import Session, Message
from session_zoon.summarizer import generate_summary, build_prompt


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
                timestamp=datetime(2026, 3, 10, 10, i, tzinfo=timezone.utc),
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


@patch("session_zoon.summarizer.anthropic")
def test_generate_summary(mock_anthropic):
    mock_client = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Fixed XSS vulnerability in login page")]
    )

    result = generate_summary(_make_session(), api_key="test-key")
    assert result == "Fixed XSS vulnerability in login page"
    mock_client.messages.create.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_summarizer.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement summarizer**

```python
# src/session_zoon/summarizer.py
import anthropic

from session_zoon.models import Session

MAX_PROMPT_CHARS = 80_000


def build_prompt(session: Session) -> str:
    lines = [
        f"Project: {session.project}",
        f"Tool: {session.tool}",
        f"Model: {session.model}",
        f"Branch: {session.git_branch or 'N/A'}",
        f"Duration: {session.duration_minutes or '?'} minutes",
        "",
        "Conversation:",
    ]

    char_count = sum(len(l) for l in lines)
    for msg in session.messages:
        role = "User" if msg.role == "user" else "Assistant"
        content = msg.content.strip()
        entry = f"\n[{role}]: {content}"

        if msg.tool_calls:
            tools = ", ".join(tc.get("name", "?") for tc in msg.tool_calls)
            files = ", ".join(
                tc.get("input", {}).get("file_path", "")
                for tc in msg.tool_calls
                if tc.get("input", {}).get("file_path")
            )
            entry += f"\n  Tools: {tools}"
            if files:
                entry += f"\n  Files: {files}"

        if char_count + len(entry) > MAX_PROMPT_CHARS:
            lines.append("\n... (truncated)")
            break
        lines.append(entry)
        char_count += len(entry)

    return "\n".join(lines)


SYSTEM_PROMPT = """You are summarizing an AI-assisted development session.
Generate a concise summary with these sections:
1. A one-line title (what was accomplished)
2. A brief summary paragraph (2-3 sentences)
3. Key decisions made during the session
4. Keep it factual and concise. Write in the same language as the conversation."""


def generate_summary(session: Session, *,
                     api_key: str,
                     model: str = "claude-haiku-4-5-20251001") -> str:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(session)

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_summarizer.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/session_zoon/summarizer.py tests/test_summarizer.py
git commit -m "feat: add AI summarizer with Anthropic API"
```

---

## Chunk 4: Git Sync + CLI Commands

### Task 8: Git Sync Module

**Files:**
- Create: `src/session_zoon/sync.py`
- Create: `tests/test_sync.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sync.py
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from session_zoon.sync import (
    init_repo, copy_raw_session, write_meta_json,
    write_session_markdown, commit_and_push, pull_repo,
    list_raw_sessions,
)


def _init_bare_remote(tmp_path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True)
    return remote


def _init_local_repo(tmp_path, remote: Path) -> Path:
    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", str(remote), str(repo)], capture_output=True)
    # Need at least one commit for push to work
    (repo / ".gitkeep").touch()
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "push"], cwd=str(repo), capture_output=True)
    return repo


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sync.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement sync.py**

```python
# src/session_zoon/sync.py
import json
import shutil
import subprocess
from pathlib import Path


def init_repo(repo_dir: Path, remote_url: str) -> None:
    if repo_dir.exists():
        return
    subprocess.run(
        ["git", "clone", remote_url, str(repo_dir)],
        check=True, capture_output=True, text=True,
    )


def pull_repo(repo_dir: Path) -> None:
    subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=str(repo_dir), check=True, capture_output=True, text=True,
    )


def copy_raw_session(*, repo_dir: Path, source_path: Path,
                     tool: str, project: str, session_id: str) -> Path:
    dest_dir = repo_dir / "raw" / tool / project
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{session_id}.jsonl"
    shutil.copy2(str(source_path), str(dest))
    return dest


def write_meta_json(*, repo_dir: Path, tool: str, project: str,
                    session_id: str, meta: dict) -> Path:
    dest_dir = repo_dir / "raw" / tool / project
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{session_id}.meta.json"
    dest.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return dest


def write_session_markdown(*, repo_dir: Path, project: str, date: str,
                           tool: str, session_id: str, content: str) -> Path:
    dest_dir = repo_dir / "sessions" / project / date / tool
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{session_id}.md"
    dest.write_text(content)
    return dest


def commit_and_push(repo_dir: Path, message: str) -> bool:
    subprocess.run(["git", "add", "-A"], cwd=str(repo_dir),
                   check=True, capture_output=True)
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_dir), capture_output=True, text=True,
    )
    if not result.stdout.strip():
        return False  # Nothing to commit
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(repo_dir), check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "push"],
        cwd=str(repo_dir), check=True, capture_output=True, text=True,
    )
    return True


def list_raw_sessions(repo_dir: Path) -> list[dict]:
    raw_dir = repo_dir / "raw"
    if not raw_dir.exists():
        return []

    sessions = []
    for jsonl_file in raw_dir.rglob("*.jsonl"):
        parts = jsonl_file.relative_to(raw_dir).parts
        if len(parts) < 3:
            continue
        tool, project = parts[0], parts[1]
        session_id = jsonl_file.stem
        meta_path = jsonl_file.with_suffix(".meta.json")
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())

        sessions.append({
            "session_id": session_id,
            "tool": tool,
            "project": project,
            "jsonl_path": jsonl_file,
            "meta": meta,
        })
    return sorted(sessions, key=lambda s: s["session_id"])
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_sync.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/session_zoon/sync.py tests/test_sync.py
git commit -m "feat: add git sync module for GitHub operations"
```

### Task 9: CLI Commands

**Files:**
- Create: `src/session_zoon/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for core CLI commands**

```python
# tests/test_cli.py
import json
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from session_zoon.cli import app

runner = CliRunner()


def test_init_creates_config_dir(tmp_path):
    with patch("session_zoon.cli._config_dir", return_value=tmp_path / ".session-zoon"):
        result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / ".session-zoon").exists()


def test_config_show(tmp_path):
    config_dir = tmp_path / ".session-zoon"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('repo = "https://github.com/user/repo.git"\n')
    with patch("session_zoon.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "github.com" in result.stdout


def test_config_set(tmp_path):
    config_dir = tmp_path / ".session-zoon"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("")
    with patch("session_zoon.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["config", "set", "repo", "https://github.com/user/repo.git"])
    assert result.exit_code == 0


def test_list_empty(tmp_path):
    config_dir = tmp_path / ".session-zoon"
    config_dir.mkdir()
    with patch("session_zoon.cli._config_dir", return_value=config_dir):
        with patch("session_zoon.cli._get_db") as mock_db:
            mock_db.return_value.list_sessions.return_value = []
            result = runner.invoke(app, ["list"])
    assert result.exit_code == 0


def test_import_finds_sessions(tmp_path, sample_claude_session):
    config_dir = tmp_path / "sz"
    config_dir.mkdir()
    with patch("session_zoon.cli._config_dir", return_value=config_dir), \
         patch("session_zoon.cli._claude_dir", return_value=sample_claude_session / ".claude"):
        result = runner.invoke(app, ["import"])
    assert result.exit_code == 0
    assert "1" in result.stdout  # Should mention 1 session imported
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: Implement CLI**

```python
# src/session_zoon/cli.py
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from session_zoon.config import Config, load_config, save_config
from session_zoon.db import SessionDB
from session_zoon.adapters import get_adapter, list_adapters
from session_zoon.renderer import render_session_markdown

app = typer.Typer(name="zoom", help="AI development session recorder")
config_app = typer.Typer(help="Manage configuration")
app.add_typer(config_app, name="config")
console = Console()


def _config_dir() -> Path:
    return Path.home() / ".session-zoon"


def _claude_dir() -> Path:
    return Path.home() / ".claude"


def _get_config() -> Config:
    cfg = load_config(_config_dir() / "config.toml")
    cfg.config_dir = _config_dir()
    return cfg


def _get_db() -> SessionDB:
    cfg = _get_config()
    db = SessionDB(cfg.db_path)
    db.init()
    return db


# ── Init ──

@app.command()
def init():
    """Initialize session-zoon configuration."""
    d = _config_dir()
    d.mkdir(parents=True, exist_ok=True)
    config_path = d / "config.toml"
    if not config_path.exists():
        save_config(Config(config_dir=d), config_path)
    db = SessionDB(d / "index.db")
    db.init()
    console.print(f"[green]Initialized session-zoon at {d}[/green]")


# ── Config ──

@config_app.command("show")
def config_show():
    """Show current configuration."""
    cfg = _get_config()
    console.print(f"Config dir: {cfg.config_dir}")
    console.print(f"Repo: {cfg.repo or '(not set)'}")
    console.print(f"AI model: {cfg.ai_model}")
    console.print(f"AI key: {'***' if cfg.ai_key else '(not set)'}")


@config_app.command("set")
def config_set(key: str, value: str):
    """Set a configuration value."""
    cfg = _get_config()
    if key == "repo":
        cfg.repo = value
    elif key == "ai-key":
        cfg.ai_key = value
    elif key == "ai-model":
        cfg.ai_model = value
    else:
        console.print(f"[red]Unknown key: {key}. Use: repo, ai-key, ai-model[/red]")
        raise typer.Exit(1)
    save_config(cfg, cfg.config_file)
    console.print(f"[green]Set {key} = {value if key != 'ai-key' else '***'}[/green]")


# ── Import ──

@app.command("import")
def import_sessions(
    tool: Optional[str] = typer.Option(None, help="Filter by tool"),
    project: Optional[str] = typer.Option(None, help="Filter by project"),
    since: Optional[str] = typer.Option(None, help="Only import after date (YYYY-MM-DD)"),
):
    """Import new sessions from AI dev tools."""
    db = _get_db()
    since_dt = datetime.fromisoformat(since) if since else None
    tools = [tool] if tool else list_adapters()
    total_imported = 0
    total_skipped = 0

    for tool_name in tools:
        adapter = get_adapter(tool_name, claude_dir=_claude_dir())
        paths = adapter.discover(since=since_dt, project=project)
        for path in paths:
            session = adapter.parse(path)
            if db.session_exists(session.id):
                total_skipped += 1
                continue
            db.upsert_session(
                id=session.id, tool=session.tool, project=session.project,
                source_path=str(session.source_path),
                started_at=session.started_at, ended_at=session.ended_at,
                model=session.model, total_tokens=session.total_tokens,
                message_count=session.message_count,
            )
            total_imported += 1

    console.print(f"[green]Imported: {total_imported}[/green] | Skipped: {total_skipped}")


# ── List ──

@app.command("list")
def list_sessions(
    project: Optional[str] = typer.Option(None, help="Filter by project"),
    tag: Optional[str] = typer.Option(None, help="Filter by tag"),
    tool: Optional[str] = typer.Option(None, help="Filter by tool"),
    since: Optional[str] = typer.Option(None, help="Filter by start date"),
    status: Optional[str] = typer.Option(None, help="Filter by sync status"),
    no_summary: bool = typer.Option(False, help="Only show sessions without summary"),
):
    """List indexed sessions."""
    db = _get_db()
    sessions = db.list_sessions(
        project=project, tag=tag, tool=tool,
        since=since, status=status, no_summary=no_summary,
    )
    if not sessions:
        console.print("No sessions found.")
        return

    table = Table()
    table.add_column("ID", style="cyan", max_width=12)
    table.add_column("Project")
    table.add_column("Tool")
    table.add_column("Date")
    table.add_column("Tokens", justify="right")
    table.add_column("Status")
    table.add_column("Summary", max_width=40)

    for s in sessions:
        date = s["started_at"][:10] if s["started_at"] else "?"
        table.add_row(
            s["id"][:12],
            s["project"],
            s["tool"],
            date,
            f"{s['total_tokens']:,}" if s["total_tokens"] else "?",
            s["sync_status"],
            (s["summary"] or "")[:40],
        )

    console.print(table)


# ── Show ──

@app.command("show")
def show_session(
    id: str = typer.Argument(help="Session ID (or prefix)"),
    raw: bool = typer.Option(False, help="Show raw JSONL"),
    markdown: bool = typer.Option(False, help="Show rendered Markdown"),
):
    """Show session details."""
    db = _get_db()
    session = db.get_session(id)
    if not session:
        console.print(f"[red]Session not found: {id}[/red]")
        raise typer.Exit(1)

    if raw:
        source = Path(session["source_path"])
        if source.exists():
            console.print(source.read_text())
        else:
            console.print(f"[red]Source file not found: {source}[/red]")
        return

    if markdown:
        adapter = get_adapter(session["tool"], claude_dir=_claude_dir())
        source = Path(session["source_path"])
        if source.exists():
            parsed = adapter.parse(source)
            tags = db.get_tags(id)
            md = render_session_markdown(parsed, summary=session.get("summary"), tags=tags)
            console.print(md)
        else:
            console.print(f"[red]Source file not found: {source}[/red]")
        return

    # Default: show metadata
    tags = db.get_tags(id)
    console.print(f"[bold]Session: {session['id']}[/bold]")
    console.print(f"Tool: {session['tool']}")
    console.print(f"Project: {session['project']}")
    console.print(f"Model: {session['model']}")
    console.print(f"Started: {session['started_at']}")
    console.print(f"Ended: {session['ended_at']}")
    console.print(f"Tokens: {session['total_tokens']:,}" if session['total_tokens'] else "Tokens: ?")
    console.print(f"Messages: {session['message_count']}")
    console.print(f"Sync: {session['sync_status']}")
    if tags:
        console.print(f"Tags: {', '.join(tags)}")
    if session.get("summary"):
        console.print(f"\n[bold]Summary:[/bold]\n{session['summary']}")


# ── Search ──

@app.command("search")
def search_sessions(query: str = typer.Argument(help="Search query")):
    """Search sessions by summary content. (v1: summary only, future: SQLite FTS5)"""
    db = _get_db()
    all_sessions = db.list_sessions()
    matches = [
        s for s in all_sessions
        if s.get("summary") and query.lower() in s["summary"].lower()
    ]
    if not matches:
        console.print("No matches found.")
        return

    for s in matches:
        console.print(f"[cyan]{s['id'][:12]}[/cyan] [{s['project']}] {s['summary'][:60]}")


# ── Tag ──

@app.command("tag")
def tag_session(
    id: str = typer.Argument(help="Session ID"),
    tags: list[str] = typer.Argument(default=None, help="Tags to add"),
    remove: Optional[str] = typer.Option(None, help="Tag to remove"),
):
    """Add or remove tags on a session."""
    db = _get_db()
    if not db.session_exists(id):
        console.print(f"[red]Session not found: {id}[/red]")
        raise typer.Exit(1)

    if remove:
        db.remove_tag(id, remove)
        console.print(f"[green]Removed tag '{remove}' from {id}[/green]")
    elif tags:
        db.add_tags(id, tags)
        console.print(f"[green]Added tags {tags} to {id}[/green]")

    current = db.get_tags(id)
    console.print(f"Current tags: {', '.join(current) if current else '(none)'}")


@app.command("tags")
def list_tags():
    """List all tags and their counts."""
    db = _get_db()
    tags = db.list_all_tags()
    if not tags:
        console.print("No tags found.")
        return
    for tag, count in tags:
        console.print(f"  {tag}: {count}")


# ── Delete ──

@app.command("delete")
def delete_session(
    id: str = typer.Argument(help="Session ID"),
    index_only: bool = typer.Option(False, help="Only remove from index"),
):
    """Delete a session."""
    db = _get_db()
    session = db.get_session(id)
    if not session:
        console.print(f"[red]Session not found: {id}[/red]")
        raise typer.Exit(1)

    confirm = typer.confirm(f"Delete session {id}?")
    if not confirm:
        return

    db.delete_session(id)
    console.print(f"[green]Deleted session {id} from index[/green]")

    if not index_only:
        console.print("[yellow]Note: Run 'zoom sync' to remove from GitHub repo[/yellow]")


# ── Summarize ──

@app.command("summarize")
def summarize(
    id: Optional[str] = typer.Argument(None, help="Session ID (omit for all)"),
    force: bool = typer.Option(False, help="Regenerate existing summaries"),
    model: Optional[str] = typer.Option(None, help="AI model to use"),
):
    """Generate AI summaries for sessions."""
    from session_zoon.summarizer import generate_summary

    cfg = _get_config()
    if not cfg.ai_key:
        console.print("[red]AI key not set. Run: zoom config set ai-key <key>[/red]")
        raise typer.Exit(1)

    db = _get_db()
    ai_model = model or cfg.ai_model

    if id:
        sessions = [db.get_session(id)]
        if not sessions[0]:
            console.print(f"[red]Session not found: {id}[/red]")
            raise typer.Exit(1)
    else:
        sessions = db.list_sessions(no_summary=not force)

    count = 0
    for s in sessions:
        if not force and s.get("summary"):
            continue

        adapter = get_adapter(s["tool"], claude_dir=_claude_dir())
        source = Path(s["source_path"])
        if not source.exists():
            console.print(f"[yellow]Skip {s['id'][:12]}: source file missing[/yellow]")
            continue

        parsed = adapter.parse(source)
        console.print(f"Summarizing {s['id'][:12]} ({s['project']})...", end=" ")
        summary = generate_summary(parsed, api_key=cfg.ai_key, model=ai_model)
        db.update_summary(s["id"], summary)
        console.print("[green]done[/green]")
        count += 1

    console.print(f"\n[green]Summarized {count} session(s)[/green]")


# ── Sync ──

@app.command("sync")
def sync(
    dry_run: bool = typer.Option(False, help="Preview changes without syncing"),
):
    """Sync sessions to GitHub."""
    from session_zoon import sync as sync_module

    cfg = _get_config()
    if not cfg.repo:
        console.print("[red]Repo not set. Run: zoom config set repo <url>[/red]")
        raise typer.Exit(1)

    db = _get_db()
    repo_dir = cfg.repo_dir

    # Clone or pull
    if not repo_dir.exists():
        console.print(f"Cloning {cfg.repo}...")
        sync_module.init_repo(repo_dir, cfg.repo)
    else:
        console.print("Pulling latest...")
        sync_module.pull_repo(repo_dir)

    # Find sessions to sync
    pending = db.list_sessions(status="pending") + db.list_sessions(status="modified")
    if not pending:
        console.print("Everything up to date.")
        return

    if dry_run:
        console.print(f"Would sync {len(pending)} session(s):")
        for s in pending:
            console.print(f"  {s['id'][:12]} ({s['project']}) [{s['sync_status']}]")
        return

    for s in pending:
        source = Path(s["source_path"])
        if not source.exists():
            console.print(f"[yellow]Skip {s['id'][:12]}: source missing[/yellow]")
            continue

        # Copy raw JSONL
        sync_module.copy_raw_session(
            repo_dir=repo_dir, source_path=source,
            tool=s["tool"], project=s["project"], session_id=s["id"],
        )

        # Write meta.json
        tags = db.get_tags(s["id"])
        meta = {
            "session_id": s["id"], "tool": s["tool"], "project": s["project"],
            "started_at": s["started_at"], "ended_at": s["ended_at"],
            "model": s["model"], "total_tokens": s["total_tokens"],
            "message_count": s["message_count"], "summary": s.get("summary"),
            "tags": tags, "source_path": s["source_path"],
            "cwd": parsed.cwd,
        }
        sync_module.write_meta_json(
            repo_dir=repo_dir, tool=s["tool"], project=s["project"],
            session_id=s["id"], meta=meta,
        )

        # Write Markdown summary
        adapter = get_adapter(s["tool"], claude_dir=_claude_dir())
        parsed = adapter.parse(source)
        md = render_session_markdown(parsed, summary=s.get("summary"), tags=tags)
        date = s["started_at"][:10] if s["started_at"] else "unknown"
        sync_module.write_session_markdown(
            repo_dir=repo_dir, project=s["project"], date=date,
            tool=s["tool"], session_id=s["id"], content=md,
        )

        db.update_sync_status(s["id"], "synced")
        console.print(f"  [green]Synced {s['id'][:12]}[/green]")

    # Commit and push
    committed = sync_module.commit_and_push(
        repo_dir, f"zoom: sync {len(pending)} session(s)",
    )
    if committed:
        console.print(f"\n[green]Pushed {len(pending)} session(s) to GitHub[/green]")


# ── Clone ──

@app.command("clone")
def clone():
    """Clone the session repo to local."""
    from session_zoon import sync as sync_module

    cfg = _get_config()
    if not cfg.repo:
        console.print("[red]Repo not set. Run: zoom config set repo <url>[/red]")
        raise typer.Exit(1)

    if cfg.repo_dir.exists():
        console.print("[yellow]Repo already exists locally. Use 'zoom sync' to update.[/yellow]")
        return

    console.print(f"Cloning {cfg.repo}...")
    sync_module.init_repo(cfg.repo_dir, cfg.repo)
    console.print("[green]Clone complete.[/green]")


# ── Reindex ──

@app.command("reindex")
def reindex():
    """Rebuild SQLite index from repo files."""
    import json
    from session_zoon import sync as sync_module

    cfg = _get_config()
    repo_dir = cfg.repo_dir
    if not repo_dir.exists():
        console.print("[red]Repo not found. Run 'zoom clone' first.[/red]")
        raise typer.Exit(1)

    db = _get_db()
    raw_sessions = sync_module.list_raw_sessions(repo_dir)
    count = 0

    for entry in raw_sessions:
        meta = entry["meta"]
        db.upsert_session(
            id=entry["session_id"],
            tool=entry["tool"],
            project=entry["project"],
            source_path=str(entry["jsonl_path"]),
            started_at=datetime.fromisoformat(meta["started_at"]) if meta.get("started_at") else None,
            ended_at=datetime.fromisoformat(meta["ended_at"]) if meta.get("ended_at") else None,
            model=meta.get("model", "unknown"),
            total_tokens=meta.get("total_tokens", 0),
            message_count=meta.get("message_count", 0),
        )
        if meta.get("summary"):
            db.update_summary(entry["session_id"], meta["summary"])
        if meta.get("tags"):
            db.add_tags(entry["session_id"], meta["tags"])
        db.update_sync_status(entry["session_id"], "synced")
        count += 1

    console.print(f"[green]Reindexed {count} session(s) from repo[/green]")


# ── Restore ──

@app.command("restore")
def restore(
    project: Optional[str] = typer.Option(None, help="Only restore specific project"),
    tool: Optional[str] = typer.Option(None, help="Only restore specific tool"),
):
    """Restore session files to tool directories (e.g. ~/.claude/) for /resume support."""
    from session_zoon import sync as sync_module

    cfg = _get_config()
    repo_dir = cfg.repo_dir
    if not repo_dir.exists():
        console.print("[red]Repo not found. Run 'zoom clone' first.[/red]")
        raise typer.Exit(1)

    raw_sessions = sync_module.list_raw_sessions(repo_dir)
    count = 0

    for entry in raw_sessions:
        if project and entry["project"] != project:
            continue
        if tool and entry["tool"] != tool:
            continue

        adapter = get_adapter(entry["tool"], claude_dir=_claude_dir())
        # Build a minimal session to get restore path
        meta = entry["meta"]
        from session_zoon.models import Session
        session = Session(
            id=entry["session_id"], tool=entry["tool"],
            project=entry["project"], source_path=entry["jsonl_path"],
            started_at=None, ended_at=None, model="", total_tokens=0,
            cwd=meta.get("cwd"),
        )

        dest = adapter.get_restore_path(session)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            import shutil
            shutil.copy2(str(entry["jsonl_path"]), str(dest))
            console.print(f"  Restored {entry['session_id'][:12]} → {dest}")
            count += 1

    console.print(f"\n[green]Restored {count} session(s)[/green]")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_cli.py -v`
Expected: 5 passed

- [ ] **Step 5: Run all tests to verify nothing is broken**

Run: `pytest tests/ -v`
Expected: All passed

- [ ] **Step 6: Commit**

```bash
git add src/session_zoon/cli.py tests/test_cli.py
git commit -m "feat: add full CLI with all zoom commands"
```

---

## Chunk 5: Integration Test + Polish

### Task 10: End-to-End Integration Test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_integration.py
"""End-to-end test: import → list → tag → show → summarize (mocked) → sync (local)"""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from session_zoon.cli import app

runner = CliRunner()


def test_full_workflow(sample_claude_session, tmp_path):
    config_dir = tmp_path / "sz-config"
    claude_dir = sample_claude_session / ".claude"

    # Set up a local bare git repo as "remote"
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True)

    with patch("session_zoon.cli._config_dir", return_value=config_dir), \
         patch("session_zoon.cli._claude_dir", return_value=claude_dir):

        # 1. Init
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0

        # 2. Config
        result = runner.invoke(app, ["config", "set", "repo", str(remote)])
        assert result.exit_code == 0

        # 3. Import
        result = runner.invoke(app, ["import"])
        assert result.exit_code == 0
        assert "1" in result.stdout

        # 4. List
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "my-project" in result.stdout

        # 5. Tag
        result = runner.invoke(app, ["tag", "test-session-001", "bugfix", "test"])
        assert result.exit_code == 0

        # 6. Show
        result = runner.invoke(app, ["show", "test-session-001"])
        assert result.exit_code == 0
        assert "claude-code" in result.stdout

        # 7. Summarize (mocked AI)
        result = runner.invoke(app, ["config", "set", "ai-key", "test-key"])
        with patch("session_zoon.summarizer.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = MagicMock(
                content=[MagicMock(text="Fixed login bug with XSS sanitization")]
            )
            result = runner.invoke(app, ["summarize", "test-session-001"])
            assert result.exit_code == 0
            assert "done" in result.stdout

        # 8. Sync (to local bare repo)
        # First, need to init the remote with an initial commit
        staging = tmp_path / "staging"
        subprocess.run(["git", "clone", str(remote), str(staging)], capture_output=True)
        (staging / ".gitkeep").touch()
        subprocess.run(["git", "add", "."], cwd=str(staging), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(staging), capture_output=True)
        subprocess.run(["git", "push"], cwd=str(staging), capture_output=True)

        result = runner.invoke(app, ["sync"])
        assert result.exit_code == 0

        # 9. Verify repo contents
        repo_dir = config_dir / "repo"
        assert (repo_dir / "raw" / "claude-code" / "my-project" / "test-session-001.jsonl").exists()
        assert (repo_dir / "raw" / "claude-code" / "my-project" / "test-session-001.meta.json").exists()

        meta = json.loads(
            (repo_dir / "raw" / "claude-code" / "my-project" / "test-session-001.meta.json").read_text()
        )
        assert meta["tags"] == ["bugfix", "test"]
        assert "XSS" in meta["summary"]
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_integration.py -v`
Expected: 1 passed

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add end-to-end integration test"
```

### Task 11: Manual Smoke Test

- [ ] **Step 1: Test with real data**

Run:
```bash
zoom init
zoom import
zoom list
zoom show <first-session-id>
```

Expected: Shows real sessions from `~/.claude/`

- [ ] **Step 2: Fix any issues found during smoke test**

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "fix: polish from smoke testing"
```
