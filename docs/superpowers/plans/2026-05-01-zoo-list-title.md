# Zoo List Title Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `title` column to `zoo list` with 4-level priority resolution (manual > summary > ai-title > first-message), plus a `zoo title` command for manual override and backfill.

**Architecture:** New `sessions.title` and `sessions.title_source` columns in SQLite, single `db.update_title` write entry with priority guard, adapter methods to extract Claude Code's native `aiTitle` from jsonl and the first user message as fallback, summarizer parser for the existing `**Title:**` markdown line, CLI integration into `import`/`summarize`/`sync`/`reindex`/`list`/`show` plus a new `title` command.

**Tech Stack:** Python 3.13, SQLite, Typer, Rich, pytest. Existing project uses TDD-style unit + integration tests.

**Spec:** `docs/superpowers/specs/2026-05-01-zoo-list-title-design.md`

---

## File Map

| File | Change |
|------|--------|
| `src/session_zoo/db.py` | + `init()` migration; + `update_title`, `set_title_raw`, `clear_title` |
| `src/session_zoo/adapters/claude_code.py` | + `extract_native_title`, `extract_first_message` |
| `src/session_zoo/summarizer.py` | + `parse_title_from_summary` |
| `src/session_zoo/cli.py` | + `title` command; modify `list`, `show`, `import`, `summarize`, `sync`, `reindex` |
| `tests/conftest.py` | + `sample_claude_session_with_ai_title` fixture |
| `tests/test_db.py` | + 4 tests |
| `tests/test_claude_code_adapter.py` | + 5 tests |
| `tests/test_summarizer.py` | + 3 tests |
| `tests/test_cli.py` | + 13 tests (title cmd, list, show, import, summarize, reindex) |
| `tests/test_e2e.py` | + 1 test (sync round-trip of title fields) |

---

## Task 1: DB schema migration (idempotent ALTER TABLE)

**Files:**
- Modify: `src/session_zoo/db.py:19-41` (the `init` method)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_db.py`:

```python
import sqlite3


def test_init_adds_title_columns_on_existing_db(tmp_path):
    """Simulate an old DB without title columns; init() should add them idempotently."""
    db_path = tmp_path / "old.db"
    # 1) Build a legacy schema (no title columns)
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE sessions (
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
    """)
    conn.commit()
    conn.close()

    # 2) Run init() — should add the new columns without error
    db = SessionDB(db_path)
    db.init()
    db.init()  # second call must also be a no-op (idempotent)

    # 3) Verify columns exist by inserting a row that uses them
    conn = sqlite3.connect(str(db_path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()}
    conn.close()
    assert "title" in cols
    assert "title_source" in cols
```

- [ ] **Step 2: Run test to verify it fails**

```
.venv/Scripts/python.exe -m pytest tests/test_db.py::test_init_adds_title_columns_on_existing_db -v
```

Expected: FAIL with assertion that `title` not in cols.

- [ ] **Step 3: Implement the migration**

In `src/session_zoo/db.py`, modify the `init` method to add the migration after the `executescript` block:

```python
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
            synced_at TEXT,
            title TEXT,
            title_source TEXT
        );
        CREATE TABLE IF NOT EXISTS tags (
            session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
            tag TEXT NOT NULL,
            PRIMARY KEY (session_id, tag)
        );
    """)
    # Idempotent migrations for upgrading existing DBs
    for sql in (
        "ALTER TABLE sessions ADD COLUMN title TEXT",
        "ALTER TABLE sessions ADD COLUMN title_source TEXT",
    ):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
```

Also add `import sqlite3` is already there (line 1) — no change to imports.

- [ ] **Step 4: Run tests to verify pass**

```
.venv/Scripts/python.exe -m pytest tests/test_db.py -v
```

Expected: all tests pass, including the new one.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/db.py tests/test_db.py
git commit -m "feat(db): add title and title_source columns with idempotent migration"
```

---

## Task 2: `db.update_title` with priority guard

**Files:**
- Modify: `src/session_zoo/db.py` (add new method after `update_summary`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_db.py`:

```python
def _seed_session(db, sid="s1"):
    db.upsert_session(
        id=sid, tool="claude-code", project="p",
        source_path=f"/tmp/{sid}.jsonl",
        started_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
        ended_at=None, model="m", total_tokens=0, message_count=0,
    )


def test_update_title_writes_when_no_existing_title(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    assert db.update_title("s1", "First title", "ai-title") is True
    row = db.get_session("s1")
    assert row["title"] == "First title"
    assert row["title_source"] == "ai-title"


def test_update_title_priority_guard_blocks_lower(tmp_path):
    """manual (1) cannot be overwritten by summary (2)."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "Manual", "manual")
    assert db.update_title("s1", "Auto", "summary") is False
    row = db.get_session("s1")
    assert row["title"] == "Manual"
    assert row["title_source"] == "manual"


def test_update_title_priority_guard_allows_higher(tmp_path):
    """summary (2) can overwrite manual? No — but manual can overwrite summary."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "Auto", "summary")
    assert db.update_title("s1", "Manual", "manual") is True
    row = db.get_session("s1")
    assert row["title"] == "Manual"
    assert row["title_source"] == "manual"


def test_update_title_priority_first_message_to_ai_title(tmp_path):
    """ai-title (3) overwrites first-message (4)."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "ls", "first-message")
    assert db.update_title("s1", "Real title", "ai-title") is True
    row = db.get_session("s1")
    assert row["title_source"] == "ai-title"


def test_update_title_priority_ai_title_blocks_first_message(tmp_path):
    """first-message (4) cannot overwrite ai-title (3)."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "Real title", "ai-title")
    assert db.update_title("s1", "ls", "first-message") is False
    row = db.get_session("s1")
    assert row["title"] == "Real title"
    assert row["title_source"] == "ai-title"


def test_update_title_same_source_allowed_for_refresh(tmp_path):
    """Re-running summarize should refresh the summary-derived title."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "Old", "summary")
    assert db.update_title("s1", "New", "summary") is True
    row = db.get_session("s1")
    assert row["title"] == "New"


def test_update_title_rejects_empty(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    assert db.update_title("s1", "", "manual") is False
    assert db.update_title("s1", "   ", "manual") is False
    row = db.get_session("s1")
    assert row["title"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_db.py -v -k update_title
```

Expected: FAIL — `update_title` not defined.

- [ ] **Step 3: Implement `update_title`**

Add to `src/session_zoo/db.py` (after `update_summary`):

```python
_TITLE_PRIORITY: dict[str | None, int] = {
    "manual": 1,
    "summary": 2,
    "ai-title": 3,
    "first-message": 4,
    None: 5,
}


def update_title(self, id: str, title: str, source: str) -> bool:
    """Write title only if `source` has equal-or-higher priority than the
    existing title_source. Returns True if written, False if blocked.
    Empty/whitespace title is rejected.
    """
    if not title or not title.strip():
        return False
    if source not in self._TITLE_PRIORITY or source is None:
        raise ValueError(f"unknown title source: {source!r}")

    conn = self._get_conn()
    row = conn.execute(
        "SELECT title_source FROM sessions WHERE id = ?", (id,)
    ).fetchone()
    if row is None:
        return False  # session not found

    existing_source = row["title_source"]
    if self._TITLE_PRIORITY[source] > self._TITLE_PRIORITY[existing_source]:
        return False  # incoming has lower priority

    conn.execute(
        "UPDATE sessions SET title = ?, title_source = ? WHERE id = ?",
        (title.strip(), source, id),
    )
    conn.commit()
    return True
```

Note `_TITLE_PRIORITY` is a class-level constant (defined inside the class body, not module-level).

- [ ] **Step 4: Run tests to verify pass**

```
.venv/Scripts/python.exe -m pytest tests/test_db.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/db.py tests/test_db.py
git commit -m "feat(db): add update_title with priority-guarded writes"
```

---

## Task 3: `db.set_title_raw` and `db.clear_title`

**Files:**
- Modify: `src/session_zoo/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_db.py`:

```python
def test_set_title_raw_bypasses_guard(tmp_path):
    """reindex must be able to write a lower-priority source over higher."""
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "Manual", "manual")
    db.set_title_raw("s1", "Restored", "ai-title")
    row = db.get_session("s1")
    assert row["title"] == "Restored"
    assert row["title_source"] == "ai-title"


def test_set_title_raw_accepts_none(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "X", "manual")
    db.set_title_raw("s1", None, None)
    row = db.get_session("s1")
    assert row["title"] is None
    assert row["title_source"] is None


def test_clear_title_resets_both_columns(tmp_path):
    db = _make_db(tmp_path)
    db.init()
    _seed_session(db)
    db.update_title("s1", "X", "manual")
    db.clear_title("s1")
    row = db.get_session("s1")
    assert row["title"] is None
    assert row["title_source"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_db.py -v -k "set_title_raw or clear_title"
```

Expected: FAIL — methods not defined.

- [ ] **Step 3: Implement methods**

Add to `src/session_zoo/db.py` (after `update_title`):

```python
def set_title_raw(self, id: str, title: str | None, source: str | None) -> None:
    """Direct write, no priority check. Reserved for reindex-from-meta."""
    conn = self._get_conn()
    conn.execute(
        "UPDATE sessions SET title = ?, title_source = ? WHERE id = ?",
        (title, source, id),
    )
    conn.commit()


def clear_title(self, id: str) -> None:
    """Reset both title and title_source to NULL."""
    self.set_title_raw(id, None, None)
```

- [ ] **Step 4: Run tests to verify pass**

```
.venv/Scripts/python.exe -m pytest tests/test_db.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/db.py tests/test_db.py
git commit -m "feat(db): add set_title_raw and clear_title"
```

---

## Task 4: `ClaudeCodeAdapter.extract_native_title` + ai-title fixture

**Files:**
- Modify: `tests/conftest.py` (new fixture)
- Modify: `src/session_zoo/adapters/claude_code.py`
- Test: `tests/test_claude_code_adapter.py`

- [ ] **Step 1: Add the new fixture**

Append to `tests/conftest.py`:

```python
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
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_claude_code_adapter.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py -v -k extract_native_title
```

Expected: FAIL — method not defined.

- [ ] **Step 4: Implement `extract_native_title`**

Add to `src/session_zoo/adapters/claude_code.py` (after `get_restore_path`):

```python
def extract_native_title(self, path: Path) -> str | None:
    """Return the most recent `aiTitle` from the jsonl, or None if absent.
    Claude Code may write multiple ai-title records as the conversation
    evolves; the last one is the canonical title.
    """
    latest: str | None = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "ai-title":
                    title = record.get("aiTitle")
                    if title:
                        latest = title
    except OSError:
        return None
    return latest
```

- [ ] **Step 5: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```
git add tests/conftest.py src/session_zoo/adapters/claude_code.py tests/test_claude_code_adapter.py
git commit -m "feat(adapter): extract native ai-title from Claude Code jsonl"
```

---

## Task 5: `ClaudeCodeAdapter.extract_first_message`

**Files:**
- Modify: `src/session_zoo/adapters/claude_code.py`
- Test: `tests/test_claude_code_adapter.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_code_adapter.py`:

```python
def test_extract_first_message_returns_first_user_text(sample_claude_session):
    adapter = ClaudeCodeAdapter(
        claude_dir=sample_claude_session / ".claude"
    )
    paths = adapter.discover()
    # Sample fixture's first user message is "Fix the login bug"
    assert adapter.extract_first_message(paths[0]) == "Fix the login bug"


def test_extract_first_message_collapses_whitespace_and_truncates(tmp_path):
    project_dir = tmp_path / ".claude" / "projects" / "-x-y"
    project_dir.mkdir(parents=True)
    f = project_dir / "abc.jsonl"
    long_text = "  hello\n\n   world  " + " padding" * 30
    f.write_text(
        json.dumps({
            "type": "user",
            "message": {"role": "user", "content": long_text},
        }) + "\n",
        encoding="utf-8",
    )
    adapter = ClaudeCodeAdapter(claude_dir=tmp_path / ".claude")
    out = adapter.extract_first_message(f)
    # Whitespace runs collapsed, leading/trailing stripped, ≤ 80 chars.
    assert "  " not in out
    assert "\n" not in out
    assert out.startswith("hello world")
    assert len(out) <= 80


def test_extract_first_message_handles_list_content(tmp_path):
    """user.message.content can be a list of {type:'text', text:...}."""
    project_dir = tmp_path / ".claude" / "projects" / "-x-y"
    project_dir.mkdir(parents=True)
    f = project_dir / "abc.jsonl"
    f.write_text(
        json.dumps({
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Hello from list"}],
            },
        }) + "\n",
        encoding="utf-8",
    )
    adapter = ClaudeCodeAdapter(claude_dir=tmp_path / ".claude")
    assert adapter.extract_first_message(f) == "Hello from list"


def test_extract_first_message_returns_none_when_no_user(tmp_path):
    project_dir = tmp_path / ".claude" / "projects" / "-x-y"
    project_dir.mkdir(parents=True)
    f = project_dir / "abc.jsonl"
    f.write_text(
        json.dumps({"type": "system", "slug": "x"}) + "\n",
        encoding="utf-8",
    )
    adapter = ClaudeCodeAdapter(claude_dir=tmp_path / ".claude")
    assert adapter.extract_first_message(f) is None


def test_extract_first_message_returns_none_for_empty_content(tmp_path):
    project_dir = tmp_path / ".claude" / "projects" / "-x-y"
    project_dir.mkdir(parents=True)
    f = project_dir / "abc.jsonl"
    f.write_text(
        json.dumps({
            "type": "user",
            "message": {"role": "user", "content": "   \n   "},
        }) + "\n",
        encoding="utf-8",
    )
    adapter = ClaudeCodeAdapter(claude_dir=tmp_path / ".claude")
    assert adapter.extract_first_message(f) is None
```

Also add `import json` (already imported at top) — no change.

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py -v -k extract_first_message
```

Expected: FAIL — method not defined.

- [ ] **Step 3: Implement `extract_first_message`**

Add to `src/session_zoo/adapters/claude_code.py` (after `extract_native_title`):

```python
import re

# (place this import at the top of the file alongside the other imports if not present)


def extract_first_message(self, path: Path) -> str | None:
    """Return the first user message's text, whitespace-collapsed and
    truncated to 80 chars. None if no user message or content is empty.
    """
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") != "user":
                    continue
                msg = record.get("message", {})
                content = msg.get("content", "")
                # Content may be string or list of {type, text}
                if isinstance(content, list):
                    parts = [
                        c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    ]
                    text = " ".join(parts)
                else:
                    text = str(content)
                # Collapse all whitespace runs to single spaces, strip ends.
                text = re.sub(r"\s+", " ", text).strip()
                if not text:
                    return None
                return text[:80]
    except OSError:
        return None
    return None
```

If `import re` isn't at the top of `claude_code.py`, add it next to `import json`.

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/test_claude_code_adapter.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/adapters/claude_code.py tests/test_claude_code_adapter.py
git commit -m "feat(adapter): extract first user message as fallback title"
```

---

## Task 6: `summarizer.parse_title_from_summary`

**Files:**
- Modify: `src/session_zoo/summarizer.py`
- Test: `tests/test_summarizer.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_summarizer.py`:

```python
from session_zoo.summarizer import parse_title_from_summary


def test_parse_title_from_summary_standard():
    summary = (
        "## Session Summary\n\n"
        "**Title:** Refactor auth middleware\n\n"
        "**Summary:** ...\n"
    )
    assert parse_title_from_summary(summary) == "Refactor auth middleware"


def test_parse_title_from_summary_chinese():
    summary = "**Title:** session-zoo Windows 兼容性修复\n\n**Summary:** ..."
    assert parse_title_from_summary(summary) == "session-zoo Windows 兼容性修复"


def test_parse_title_from_summary_returns_none_when_missing():
    assert parse_title_from_summary("just some random summary text") is None


def test_parse_title_from_summary_strips_trailing_whitespace():
    assert parse_title_from_summary("**Title:**   Hello   \n") == "Hello"


def test_parse_title_from_summary_returns_none_for_empty_value():
    assert parse_title_from_summary("**Title:**   \n") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_summarizer.py -v -k parse_title
```

Expected: FAIL — `parse_title_from_summary` not defined.

- [ ] **Step 3: Implement parser**

Add to `src/session_zoo/summarizer.py` (top-level function, near the bottom of the file):

```python
import re

_TITLE_RE = re.compile(r"^\s*\*\*Title:\*\*\s*(.+?)\s*$", re.MULTILINE)


def parse_title_from_summary(summary: str) -> str | None:
    """Extract the value after `**Title:**` from the AI-generated summary.
    Returns None if no Title line or the value is empty/whitespace.
    """
    if not summary:
        return None
    m = _TITLE_RE.search(summary)
    if not m:
        return None
    title = m.group(1).strip()
    return title or None
```

If `import re` isn't already at the top of `summarizer.py`, add it.

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/test_summarizer.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/summarizer.py tests/test_summarizer.py
git commit -m "feat(summarizer): add parse_title_from_summary helper"
```

---

## Task 7: `zoo title` command (show / set / reset)

**Files:**
- Modify: `src/session_zoo/cli.py` (add new command)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
# ─── title command ────────────────────────────────────────────────────────────

def test_title_show_when_unset(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["title", "test-session-001"])
    assert result.exit_code == 0
    assert "(untitled)" in result.stdout


def test_title_set_manual(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["title", "test-session-001", "My title"])
    assert result.exit_code == 0
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db"); db.init()
    row = db.get_session("test-session-001")
    assert row["title"] == "My title"
    assert row["title_source"] == "manual"


def test_title_reset_clears_both_fields(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db"); db.init()
    db.update_title("test-session-001", "X", "manual")
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["title", "test-session-001", "--reset"])
    assert result.exit_code == 0
    row = db.get_session("test-session-001")
    assert row["title"] is None
    assert row["title_source"] is None


def test_title_unknown_id_exits_nonzero(tmp_path):
    config_dir = _setup_config(tmp_path)
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["title", "nope"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k "title_show or title_set or title_reset or title_unknown"
```

Expected: FAIL — `title` command not registered.

- [ ] **Step 3: Implement the command**

Add to `src/session_zoo/cli.py` (after the existing `tag` command, before `delete`):

```python
@app.command("title")
def title_cmd(
    id: Optional[str] = typer.Argument(None, help="Session ID (or prefix). Omit with --backfill."),
    text: Optional[str] = typer.Argument(None, help="New title. Omit to display current."),
    reset: bool = typer.Option(False, "--reset", help="Clear title and source."),
    backfill: bool = typer.Option(False, "--backfill", help="Recompute titles for all sessions."),
):
    """Show, set, reset, or backfill a session's title."""
    db = _get_db()

    if backfill:
        # Implemented in Task 8
        from session_zoo.cli import _backfill_titles  # forward reference
        _backfill_titles(db)
        return

    if not id:
        console.print("[red]Provide an ID, or use --backfill to scan all sessions.[/red]")
        raise typer.Exit(1)

    session = db.get_session(id)
    if not session:
        console.print(f"[red]Session not found: {id}[/red]")
        raise typer.Exit(1)
    full_id = session["id"]

    if reset:
        db.clear_title(full_id)
        console.print(f"[green]Cleared title for {full_id[:12]}[/green]")
        return

    if text is not None:
        ok = db.update_title(full_id, text, "manual")
        if not ok:
            console.print(f"[red]Failed to set title (empty or invalid).[/red]")
            raise typer.Exit(1)
        console.print(f"[green]Set title for {full_id[:12]}: {text}[/green]")
        return

    # No text and no flag → show current
    title = session.get("title") or "(untitled)"
    src = session.get("title_source") or "—"
    console.print(f"{full_id[:12]}  {title}  [dim](source: {src})[/dim]")
```

Note: the `_backfill_titles` reference is forward-declared and implemented in Task 8.

For now (until Task 8), to avoid breaking import, define a stub at module level above the command:

```python
def _backfill_titles(db):
    """Implemented in Task 8."""
    raise NotImplementedError("backfill not yet implemented")
```

- [ ] **Step 4: Run the new tests**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k "title_show or title_set or title_reset or title_unknown"
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/cli.py tests/test_cli.py
git commit -m "feat(cli): add zoo title command for show/set/reset"
```

---

## Task 8: `zoo title --backfill`

**Files:**
- Modify: `src/session_zoo/cli.py` (replace `_backfill_titles` stub)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_title_backfill_fills_untitled_sessions(
    tmp_path, sample_claude_session_with_ai_title
):
    """Backfill should pick up ai-title from jsonl when title was unset."""
    # Reuse the import flow but with the ai-title fixture
    config_dir = tmp_path / ".session-zoo"
    claude_dir = sample_claude_session_with_ai_title / ".claude"
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["init"])
        # Import populates the DB but Task 11 hasn't been done yet,
        # so title may still be NULL. We force NULL to simulate that.
        runner.invoke(app, ["import"])
        from session_zoo.db import SessionDB
        db = SessionDB(config_dir / "index.db"); db.init()
        db.clear_title("test-session-001")  # force unset
        result = runner.invoke(app, ["title", "--backfill"])

    assert result.exit_code == 0
    row = db.get_session("test-session-001")
    assert row["title"] == "Newest title"
    assert row["title_source"] == "ai-title"


def test_title_backfill_does_not_override_manual(
    tmp_path, sample_claude_session_with_ai_title
):
    config_dir = tmp_path / ".session-zoo"
    claude_dir = sample_claude_session_with_ai_title / ".claude"
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["import"])
        from session_zoo.db import SessionDB
        db = SessionDB(config_dir / "index.db"); db.init()
        db.update_title("test-session-001", "User picks this", "manual")
        runner.invoke(app, ["title", "--backfill"])

    row = db.get_session("test-session-001")
    assert row["title"] == "User picks this"
    assert row["title_source"] == "manual"
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k title_backfill
```

Expected: FAIL — `_backfill_titles` raises NotImplementedError.

- [ ] **Step 3: Implement backfill**

In `src/session_zoo/cli.py`, replace the `_backfill_titles` stub with:

```python
def _backfill_titles(db):
    from session_zoo.summarizer import parse_title_from_summary

    sessions = db.list_sessions()
    updated = 0
    for s in sessions:
        sid = s["id"]
        adapter = get_adapter(s["tool"], claude_dir=_claude_dir())
        source = Path(s["source_path"])

        # 1. Try summary parse (priority 2). No file read.
        summary = s.get("summary")
        if summary:
            t = parse_title_from_summary(summary)
            if t and db.update_title(sid, t, "summary"):
                updated += 1
                continue  # higher-priority succeeded; skip the rest

        # 2. Try adapter native title (priority 3). Needs jsonl.
        if source.exists():
            native = adapter.extract_native_title(source)
            if native and db.update_title(sid, native, "ai-title"):
                updated += 1
                continue

            # 3. Fallback: first user message (priority 4).
            first = adapter.extract_first_message(source)
            if first and db.update_title(sid, first, "first-message"):
                updated += 1

    console.print(f"[green]Backfilled titles for {updated} session(s)[/green]")
```

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k title_backfill
```

Expected: pass.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/cli.py tests/test_cli.py
git commit -m "feat(cli): zoo title --backfill scans sessions and fills titles by priority"
```

---

## Task 9: `zoo list` Title column

**Files:**
- Modify: `src/session_zoo/cli.py:182-204` (the `list_sessions` function's table)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_list_shows_title_column(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db"); db.init()
    db.update_title("test-session-001", "My specific title", "manual")
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Title" in result.stdout  # column header
    assert "My specific" in result.stdout  # value (rich may truncate)


def test_list_shows_untitled_when_missing(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "untitled" in result.stdout.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k "test_list_shows_title or test_list_shows_untitled"
```

Expected: FAIL — column shows "Summary" not "Title".

- [ ] **Step 3: Modify `list_sessions` table layout**

In `src/session_zoo/cli.py`, replace lines 182-203 (the `Table` setup and the loop body) with:

```python
    table = Table()
    table.add_column("ID", style="cyan", max_width=12)
    table.add_column("Project")
    table.add_column("Tool")
    table.add_column("Date")
    table.add_column("Tokens", justify="right")
    table.add_column("Status")
    table.add_column("Title", max_width=50)

    for s in sessions:
        date = s["started_at"][:10] if s["started_at"] else "?"
        title = (s.get("title") or "(untitled)")[:50]
        table.add_row(
            s["id"][:12],
            s["project"],
            s["tool"],
            date,
            f"{s['total_tokens']:,}" if s["total_tokens"] else "?",
            s["sync_status"],
            title,
        )

    console.print(table)
```

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v
```

Expected: all pass (other list tests still pass since they don't check for "Summary").

- [ ] **Step 5: Commit**

```
git add src/session_zoo/cli.py tests/test_cli.py
git commit -m "feat(cli): replace Summary column with Title in zoo list"
```

---

## Task 10: `zoo show` displays title with source

**Files:**
- Modify: `src/session_zoo/cli.py:250-263` (the `show_session` final-output block)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_show_displays_title_and_source(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db"); db.init()
    db.update_title("test-session-001", "Specific show title", "manual")
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["show", "test-session-001"])
    assert result.exit_code == 0
    assert "Specific show title" in result.stdout
    assert "manual" in result.stdout  # source label appears


def test_show_displays_untitled_when_no_title(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["show", "test-session-001"])
    assert result.exit_code == 0
    assert "untitled" in result.stdout.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k "show_displays_title or show_displays_untitled"
```

Expected: FAIL — title not in output.

- [ ] **Step 3: Modify `show_session` output**

In `src/session_zoo/cli.py`, in `show_session` after `tags = db.get_tags(id)` and before `console.print(f"[bold]Session: {session['id']}[/bold]")`, leave that line alone — instead, after that line, insert the title:

The relevant block becomes:

```python
    tags = db.get_tags(id)
    console.print(f"[bold]Session: {session['id']}[/bold]")
    title = session.get("title") or "(untitled)"
    src = session.get("title_source") or "—"
    console.print(f"Title: {title}   [dim](source: {src})[/dim]")
    console.print(f"Tool: {session['tool']}")
    # ... rest unchanged
```

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v
```

Expected: all pass, including pre-existing show tests.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/cli.py tests/test_cli.py
git commit -m "feat(cli): show title and source in zoo show output"
```

---

## Task 11: `zoo import` integrates extract_native_title + extract_first_message

**Files:**
- Modify: `src/session_zoo/cli.py:106-161` (the `import_sessions` function)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_import_populates_title_from_ai_title(
    tmp_path, sample_claude_session_with_ai_title
):
    config_dir = tmp_path / ".session-zoo"
    claude_dir = sample_claude_session_with_ai_title / ".claude"
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["import"])
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db"); db.init()
    row = db.get_session("test-session-001")
    assert row["title"] == "Newest title"
    assert row["title_source"] == "ai-title"


def test_import_falls_back_to_first_message(tmp_path, sample_claude_session):
    """Sample fixture has no ai-title; import should use first user message."""
    config_dir = tmp_path / ".session-zoo"
    claude_dir = sample_claude_session / ".claude"
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["import"])
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db"); db.init()
    row = db.get_session("test-session-001")
    assert row["title"] == "Fix the login bug"
    assert row["title_source"] == "first-message"


def test_import_does_not_override_manual_title(
    tmp_path, sample_claude_session_with_ai_title
):
    config_dir = tmp_path / ".session-zoo"
    claude_dir = sample_claude_session_with_ai_title / ".claude"
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["import"])
        from session_zoo.db import SessionDB
        db = SessionDB(config_dir / "index.db"); db.init()
        db.update_title("test-session-001", "Manual!", "manual")
        # Re-import should not override
        runner.invoke(app, ["import"])
    row = db.get_session("test-session-001")
    assert row["title"] == "Manual!"
    assert row["title_source"] == "manual"
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k "import_populates_title or import_falls_back or import_does_not_override"
```

Expected: FAIL — no title written.

- [ ] **Step 3: Modify `import_sessions`**

In `src/session_zoo/cli.py`, in `import_sessions`, after each `db.upsert_session(...)` call (both the new-import and the modified-existing branches), call a new helper `_apply_title_after_import(db, adapter, session, path)`. Add this helper near the top of the file:

```python
def _apply_title_after_import(db, adapter, session, path):
    """After import/update, populate title from ai-title or first-message
    (priority guard prevents stomping manual/summary)."""
    if hasattr(adapter, "extract_native_title"):
        native = adapter.extract_native_title(path)
        if native and db.update_title(session.id, native, "ai-title"):
            return
    if hasattr(adapter, "extract_first_message"):
        first = adapter.extract_first_message(path)
        if first:
            db.update_title(session.id, first, "first-message")
```

Then in `import_sessions` itself, after BOTH `db.upsert_session(...)` calls, add:

```python
            _apply_title_after_import(db, adapter, session, path)
```

The two locations (in the existing-but-modified branch and the new-session branch) each get one new line.

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v
```

Expected: pass. Pre-existing import tests should still pass — they don't assert on title.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/cli.py tests/test_cli.py
git commit -m "feat(cli): zoo import populates title from ai-title or first message"
```

---

## Task 12: `zoo summarize` integrates parse_title_from_summary

**Files:**
- Modify: `src/session_zoo/cli.py:344-410` (the `summarize` function)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_summarize_writes_title_from_summary(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    fake_summary = (
        "## Session Summary\n\n"
        "**Title:** Refactor login flow\n\n"
        "**Summary:** ...\n"
    )
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir), \
         patch("session_zoo.summarizer.generate_summary", return_value=fake_summary):
        result = runner.invoke(app, ["summarize", "test-session-001",
                                     "--provider", "claude-code"])
    assert result.exit_code == 0
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db"); db.init()
    row = db.get_session("test-session-001")
    assert row["title"] == "Refactor login flow"
    assert row["title_source"] == "summary"


def test_summarize_does_not_override_manual_title(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db"); db.init()
    db.update_title("test-session-001", "Manual!", "manual")
    fake_summary = "**Title:** Auto title\n\n**Summary:** ..."
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir), \
         patch("session_zoo.summarizer.generate_summary", return_value=fake_summary):
        runner.invoke(app, ["summarize", "test-session-001",
                            "--provider", "claude-code"])
    row = db.get_session("test-session-001")
    assert row["title"] == "Manual!"
    assert row["title_source"] == "manual"
```

- [ ] **Step 2: Run tests to verify they fail**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k summarize_writes_title
```

Expected: FAIL — title not set.

- [ ] **Step 3: Modify `summarize`**

In `src/session_zoo/cli.py`, in the `summarize` command, find the line `db.update_summary(s["id"], summary)` and add right after it:

```python
            from session_zoo.summarizer import parse_title_from_summary
            t = parse_title_from_summary(summary)
            if t:
                db.update_title(s["id"], t, "summary")
```

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/cli.py tests/test_cli.py
git commit -m "feat(cli): zoo summarize derives title from **Title:** line"
```

---

## Task 13: `zoo sync` includes title in meta.json

**Files:**
- Modify: `src/session_zoo/cli.py:460-471` (the meta dict construction in `sync`)
- Test: `tests/test_e2e.py` (reuses the existing `env` fixture and `_run` helper)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_e2e.py` inside an appropriate test class (e.g., near `test_sync_to_git`). Reuses the existing `env` fixture and `_run` helper:

```python
    def test_sync_writes_title_into_meta_json(self, env):
        """Title and title_source must round-trip through meta.json."""
        self._setup(env)

        # Force a known title via the DB before syncing
        from session_zoo.db import SessionDB
        db = SessionDB(env["config_dir"] / "index.db"); db.init()
        db.set_title_raw("sess-aaa-001", "Synced title", "manual")

        result = _run(["sync"], env)
        assert result.exit_code == 0, f"sync failed: {result.stdout}"

        repo_dir = env["config_dir"] / "repo"
        raw_meta = repo_dir / "raw" / "claude-code" / "my-webapp" / "sess-aaa-001.meta.json"
        meta = json.loads(raw_meta.read_text(encoding="utf-8"))
        assert meta["title"] == "Synced title"
        assert meta["title_source"] == "manual"
```

If you can't find a class with `_setup`, use the same `_setup` invocation seen in `test_sync_to_git` (line 412 area).

- [ ] **Step 2: Run test to verify failure**

```
.venv/Scripts/python.exe -m pytest tests/test_e2e.py -v -k sync_writes_title
```

Expected: FAIL — meta.json missing `title` key.

- [ ] **Step 3: Modify the meta dict in `sync`**

In `src/session_zoo/cli.py`, in the `sync` command, find the `meta = {...}` dict (around line 460) and add two new keys:

```python
        meta = {
            "session_id": s["id"], "tool": s["tool"], "project": s["project"],
            "started_at": s["started_at"], "ended_at": s["ended_at"],
            "model": s["model"], "total_tokens": s["total_tokens"],
            "message_count": s["message_count"], "summary": s.get("summary"),
            "tags": tags, "source_path": s["source_path"],
            "cwd": parsed.cwd,
            "title": s.get("title"),
            "title_source": s.get("title_source"),
        }
```

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/test_e2e.py -v -k sync
```

Expected: pass.

- [ ] **Step 5: Commit**

```
git add src/session_zoo/cli.py tests/test_e2e.py
git commit -m "feat(sync): write title and title_source into meta.json"
```

---

## Task 14: `zoo reindex` restores title from meta.json

**Files:**
- Modify: `src/session_zoo/cli.py:524-541` (the reindex loop body)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_reindex_restores_title_from_meta(tmp_path):
    """Build a synthetic repo with a meta.json containing title fields,
    then reindex and verify the title lands in the DB via set_title_raw."""
    config_dir = tmp_path / ".session-zoo"
    repo_dir = config_dir / "repo"
    raw = repo_dir / "raw" / "claude-code" / "my-proj"
    raw.mkdir(parents=True)
    (raw / "abc123.jsonl").write_text(
        '{"type":"user","message":{"role":"user","content":"hi"},"sessionId":"abc123"}\n',
        encoding="utf-8",
    )
    (raw / "abc123.meta.json").write_text(json.dumps({
        "session_id": "abc123",
        "tool": "claude-code",
        "project": "my-proj",
        "started_at": "2026-03-10T10:00:00+00:00",
        "ended_at": "2026-03-10T10:30:00+00:00",
        "model": "claude-opus-4-6",
        "total_tokens": 100,
        "message_count": 1,
        "summary": None,
        "tags": [],
        "title": "Restored title",
        "title_source": "manual",
    }), encoding="utf-8")
    (config_dir / "config.toml").write_text(
        f'repo = "{repo_dir.as_posix()}"\n'
    )

    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["reindex"])
    assert result.exit_code == 0

    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db"); db.init()
    row = db.get_session("abc123")
    assert row["title"] == "Restored title"
    assert row["title_source"] == "manual"


def test_reindex_handles_missing_title_field(tmp_path):
    """meta.json from old version (no title field) reindexes without error."""
    config_dir = tmp_path / ".session-zoo"
    repo_dir = config_dir / "repo"
    raw = repo_dir / "raw" / "claude-code" / "my-proj"
    raw.mkdir(parents=True)
    (raw / "abc123.jsonl").write_text("{}\n", encoding="utf-8")
    (raw / "abc123.meta.json").write_text(json.dumps({
        "session_id": "abc123", "tool": "claude-code", "project": "my-proj",
        "started_at": "2026-03-10T10:00:00+00:00",
        "ended_at": "2026-03-10T10:30:00+00:00",
        "model": "m", "total_tokens": 0, "message_count": 0,
        "summary": None, "tags": [],
    }), encoding="utf-8")
    (config_dir / "config.toml").write_text(
        f'repo = "{repo_dir.as_posix()}"\n'
    )

    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["reindex"])
    assert result.exit_code == 0
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db"); db.init()
    row = db.get_session("abc123")
    assert row["title"] is None
    assert row["title_source"] is None
```

- [ ] **Step 2: Run tests to verify failure**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k reindex_restores_title
```

Expected: FAIL — title not restored.

- [ ] **Step 3: Modify `reindex`**

In `src/session_zoo/cli.py`, inside the `reindex` command's loop, after the existing `db.update_sync_status(entry["session_id"], "synced")` line, add:

```python
        if meta.get("title"):
            db.set_title_raw(
                entry["session_id"],
                meta["title"],
                meta.get("title_source"),
            )
```

- [ ] **Step 4: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/test_cli.py -v -k reindex
```

Expected: pass.

- [ ] **Step 5: Run full suite**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

Expected: all 173+ existing tests + new tests all pass.

- [ ] **Step 6: Commit**

```
git add src/session_zoo/cli.py tests/test_cli.py
git commit -m "feat(reindex): restore title and title_source from meta.json"
```

---

## Final verification

- [ ] **Step 1: Run full test suite**

```
.venv/Scripts/python.exe -m pytest tests/ -v
```

All tests must pass.

- [ ] **Step 2: Manual smoke test**

```
.venv/Scripts/python.exe -m session_zoo.cli list
```

Output should show a `Title` column with values for sessions whose jsonl had `ai-title` records, `(untitled)` for the rest.

- [ ] **Step 3: Run backfill against real local data**

```
.venv/Scripts/python.exe -m session_zoo.cli title --backfill
.venv/Scripts/python.exe -m session_zoo.cli list
```

After backfill, every session should have a non-empty title.

- [ ] **Step 4: Bump version**

Edit `pyproject.toml`: bump `version = "0.1.2"` → `version = "0.1.3"`.

```
git add pyproject.toml
git commit -m "chore: bump version to 0.1.3"
```
