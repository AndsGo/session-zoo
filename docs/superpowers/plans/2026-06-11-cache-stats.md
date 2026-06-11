# Per-Model Cache Hit Rate Stats (`zoo stats`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `zoo stats` command showing per-session, per-model prompt cache hit rates, persisted through import → DB → sync(meta.json) → reindex.

**Architecture:** `ClaudeCodeAdapter.parse()` aggregates token usage per model (deduped by `message.id`, fixing an existing double-count bug in `total_tokens`) into a new `Session.model_usage` field. `zoo import` writes it to a new `model_usage` SQLite table. `zoo stats` queries that table (global aggregate or single session). `zoo sync` writes the rows into meta.json; `zoo reindex` restores them (falling back to re-parsing the repo JSONL for old meta files). `zoo stats --backfill` fills the table for already-imported sessions.

**Tech Stack:** Python 3.13, typer, rich, sqlite3, pytest (existing stack; no new dependencies).

**Spec:** `docs/superpowers/specs/2026-06-11-cache-stats-design.md`

**Key formula:** `hit_rate = cache_read / (input + cache_read + cache_creation)`; display `?` when the denominator is 0.

**Background fact (verified against real JSONL):** Claude Code writes one JSONL record per content block, so one assistant message (one `message.id`) appears as several records each carrying the **same** `usage` object. Usage must be counted once per `message.id`. Records may also carry model `"<synthetic>"` (internal placeholder messages) — exclude those from per-model stats. Test fixtures in `tests/conftest.py` have no `message.id` field; records without an id are each counted (they represent distinct messages).

---

### Task 1: Adapter per-model aggregation with message.id dedup

**Files:**
- Modify: `src/session_zoo/models.py` (add `Session.model_usage` field)
- Modify: `src/session_zoo/adapters/claude_code.py:35-127` (`parse()`)
- Test: `tests/test_stats.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stats.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stats.py -v`
Expected: FAIL — `AttributeError: 'Session' object has no attribute 'model_usage'` (or KeyError), all 4 tests.

- [ ] **Step 3: Add `model_usage` field to Session**

In `src/session_zoo/models.py`, add a field to the `Session` dataclass after `cwd`:

```python
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
    # model name -> {"input", "cache_read", "cache_creation", "output"}
    model_usage: dict[str, dict[str, int]] = field(default_factory=dict)
```

- [ ] **Step 4: Implement per-model aggregation in the adapter**

In `src/session_zoo/adapters/claude_code.py`, inside `parse()`:

(a) Add two accumulators next to the existing ones (after `total_output = 0`):

```python
        model_usage: dict[str, dict[str, int]] = {}
        seen_msg_ids: set[str] = set()
```

(b) Replace the existing "Extract token usage" block:

```python
            # Extract token usage
            usage = msg_data.get("usage")
            token_usage = None
            if usage:
                inp = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                out = usage.get("output_tokens", 0)
                total_input += inp
                total_output += out
                token_usage = {"input": inp, "output": out}
```

with:

```python
            # Extract token usage. Claude Code writes one record per content
            # block, so one message (message.id) may appear as several records
            # carrying the same usage object — count it only once.
            usage = msg_data.get("usage")
            token_usage = None
            if usage:
                inp = usage.get("input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                out = usage.get("output_tokens", 0)
                token_usage = {"input": inp + cache_read + cache_creation, "output": out}

                msg_id = msg_data.get("id")
                already_counted = msg_id is not None and msg_id in seen_msg_ids
                if msg_id is not None:
                    seen_msg_ids.add(msg_id)
                if not already_counted:
                    total_input += inp + cache_read + cache_creation
                    total_output += out
                    msg_model = msg_data.get("model")
                    if msg_model and msg_model != "<synthetic>":
                        mu = model_usage.setdefault(msg_model, {
                            "input": 0, "cache_read": 0,
                            "cache_creation": 0, "output": 0,
                        })
                        mu["input"] += inp
                        mu["cache_read"] += cache_read
                        mu["cache_creation"] += cache_creation
                        mu["output"] += out
```

(c) Pass the result into the returned `Session` (add to the constructor call at the end of `parse()`):

```python
            git_branch=git_branch if git_branch != "HEAD" else None,
            cwd=cwd,
            model_usage=model_usage,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_stats.py -v`
Expected: 4 PASS.

- [ ] **Step 6: Run the full suite (existing tests must not regress)**

Run: `pytest -v`
Expected: all PASS. (conftest fixtures have no `message.id`, so existing totals are unchanged.)

- [ ] **Step 7: Commit**

```bash
git add src/session_zoo/models.py src/session_zoo/adapters/claude_code.py tests/test_stats.py
git commit -m "feat(adapter): aggregate token usage per model, dedupe by message.id"
```

---

### Task 2: DB `model_usage` table and accessors

**Files:**
- Modify: `src/session_zoo/db.py` (table in `init()`, three new methods)
- Test: `tests/test_stats.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stats.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stats.py -v -k "model_usage or aggregate"`
Expected: FAIL — `AttributeError: 'SessionDB' object has no attribute 'replace_model_usage'`.

- [ ] **Step 3: Add the table and methods**

In `src/session_zoo/db.py`, inside `init()`, extend the `executescript` (after the `tags` table, inside the same script string):

```sql
            CREATE TABLE IF NOT EXISTS model_usage (
                session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read_tokens INTEGER NOT NULL DEFAULT 0,
                cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (session_id, model)
            );
```

Add three methods (after `list_all_tags`):

```python
    def replace_model_usage(self, session_id: str,
                            usage: dict[str, dict[str, int]]) -> None:
        """Replace all per-model usage rows for a session (idempotent)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM model_usage WHERE session_id = ?", (session_id,))
        for model, u in usage.items():
            conn.execute(
                """INSERT INTO model_usage
                       (session_id, model, input_tokens, cache_read_tokens,
                        cache_creation_tokens, output_tokens)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, model, u.get("input", 0), u.get("cache_read", 0),
                 u.get("cache_creation", 0), u.get("output", 0)),
            )
        conn.commit()

    def get_model_usage(self, session_id: str) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT model, input_tokens, cache_read_tokens,
                      cache_creation_tokens, output_tokens
               FROM model_usage WHERE session_id = ? ORDER BY model""",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def aggregate_model_usage(self, *, project: str | None = None,
                              tool: str | None = None,
                              since: str | None = None) -> list[dict]:
        conn = self._get_conn()
        query = """SELECT mu.model,
                          COUNT(DISTINCT mu.session_id) AS sessions,
                          SUM(mu.input_tokens) AS input_tokens,
                          SUM(mu.cache_read_tokens) AS cache_read_tokens,
                          SUM(mu.cache_creation_tokens) AS cache_creation_tokens,
                          SUM(mu.output_tokens) AS output_tokens
                   FROM model_usage mu
                   JOIN sessions s ON mu.session_id = s.id"""
        conditions: list[str] = []
        params: list = []
        if project:
            conditions.append("s.project = ?")
            params.append(project)
        if tool:
            conditions.append("s.tool = ?")
            params.append(tool)
        if since:
            conditions.append("s.started_at >= ?")
            params.append(since)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += """ GROUP BY mu.model
                     ORDER BY SUM(mu.input_tokens + mu.cache_read_tokens
                                  + mu.cache_creation_tokens + mu.output_tokens) DESC"""
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_stats.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/session_zoo/db.py tests/test_stats.py
git commit -m "feat(db): model_usage table with replace/get/aggregate accessors"
```

---

### Task 3: `zoo stats` command, import wiring, `--backfill`

**Files:**
- Modify: `src/session_zoo/cli.py` (new command + helpers; two lines in `import`)
- Test: `tests/test_stats.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stats.py`:

```python
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
        assert "claude-fab" in result.stdout
        assert "85.7%" in result.stdout  # 900 / (100+900+50)

        result = runner.invoke(app, ["stats", "s-cache"])
        assert result.exit_code == 0, result.stdout
        assert "claude-hai" in result.stdout


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stats.py -v -k "stats or hit_rate"`
Expected: FAIL — `ImportError: cannot import name '_format_hit_rate'`.

- [ ] **Step 3: Implement helpers and the command**

In `src/session_zoo/cli.py`, add module-level helpers (after `_backfill_titles`):

```python
def _format_hit_rate(row: dict) -> str:
    denom = (row["input_tokens"] + row["cache_read_tokens"]
             + row["cache_creation_tokens"])
    if denom == 0:
        return "?"
    return f"{row['cache_read_tokens'] / denom:.1%}"


def _stats_table(rows: list[dict], *, with_sessions: bool) -> Table:
    table = Table()
    table.add_column("Model", style="cyan")
    if with_sessions:
        table.add_column("Sessions", justify="right")
    table.add_column("Input", justify="right")
    table.add_column("Cache Read", justify="right")
    table.add_column("Cache Write", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Hit Rate", justify="right")
    for r in rows:
        cells = [r["model"]]
        if with_sessions:
            cells.append(str(r["sessions"]))
        cells += [
            f"{r['input_tokens']:,}",
            f"{r['cache_read_tokens']:,}",
            f"{r['cache_creation_tokens']:,}",
            f"{r['output_tokens']:,}",
            _format_hit_rate(r),
        ]
        table.add_row(*cells)
    return table


def _backfill_model_usage(db):
    sessions = db.list_sessions()
    updated = 0
    for s in sessions:
        source = Path(s["source_path"])
        if not source.exists():
            console.print(f"[yellow]Skip {s['id'][:12]}: source file missing[/yellow]")
            continue
        adapter = get_adapter(s["tool"], claude_dir=_claude_dir())
        parsed = adapter.parse(source)
        db.replace_model_usage(s["id"], parsed.model_usage)
        if parsed.model_usage:
            updated += 1
    console.print(f"[green]Backfilled model usage for {updated} session(s)[/green]")
```

Add the command (after the `tags` command, before `title`):

```python
@app.command("stats")
def stats(
    id: Optional[str] = typer.Argument(None, help="Session ID (omit for global stats)"),
    project: Optional[str] = typer.Option(None, help="Filter by project"),
    tool: Optional[str] = typer.Option(None, help="Filter by tool"),
    since: Optional[str] = typer.Option(None, help="Filter by start date"),
    backfill: bool = typer.Option(False, "--backfill", help="Recompute model usage for all sessions"),
):
    """Show per-model token usage and cache hit rates."""
    db = _get_db()

    if backfill:
        _backfill_model_usage(db)
        return

    if id:
        session = db.get_session(id)
        if not session:
            console.print(f"[red]Session not found: {id}[/red]")
            raise typer.Exit(1)
        rows = db.get_model_usage(session["id"])
        if not rows:
            console.print("No usage data for this session. Run 'zoo stats --backfill'.")
            return
        console.print(f"[bold]Session: {session['id'][:12]}[/bold]")
        console.print(_stats_table(rows, with_sessions=False))
        return

    rows = db.aggregate_model_usage(project=project, tool=tool, since=since)
    if not rows:
        console.print("No usage data. Run 'zoo stats --backfill' to compute it for existing sessions.")
        return
    console.print(_stats_table(rows, with_sessions=True))
```

- [ ] **Step 4: Wire `zoo import` to persist usage**

In `import_sessions` (`cli.py`), add `db.replace_model_usage(session.id, session.model_usage)` immediately after **both** `_apply_title_after_import(db, adapter, session, path)` calls (the updated-session branch and the new-session branch):

```python
                    _apply_title_after_import(db, adapter, session, path)
                    db.replace_model_usage(session.id, session.model_usage)
```

```python
            _apply_title_after_import(db, adapter, session, path)
            db.replace_model_usage(session.id, session.model_usage)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_stats.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full suite**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/session_zoo/cli.py tests/test_stats.py
git commit -m "feat(cli): zoo stats command with per-model cache hit rates and --backfill"
```

---

### Task 4: Persist through sync meta.json and reindex

**Files:**
- Modify: `src/session_zoo/cli.py` (`sync` meta dict; `reindex` restore + fallback; add `import json` at top)
- Test: `tests/test_stats.py` (append); `tests/test_integration.py` (one assertion)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_stats.py`:

```python
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
```

In `tests/test_integration.py`, at the end of step 9 (after the existing `assert "XSS" in meta["summary"]`), add:

```python
        assert meta["model_usage"] == [{
            "model": "claude-opus-4-6",
            "input_tokens": 300,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "output_tokens": 130,
        }]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stats.py -k reindex -v; pytest tests/test_integration.py -v`
Expected: reindex tests FAIL (`get_model_usage` returns `[]`); integration FAILs on the new meta assertion (`KeyError: 'model_usage'`).

- [ ] **Step 3: Write usage into meta.json on sync**

In `src/session_zoo/cli.py` `sync()`, add one key to the `meta` dict (after `"title_source"`):

```python
            "title": s.get("title"),
            "title_source": s.get("title_source"),
            "model_usage": db.get_model_usage(s["id"]),
        }
```

- [ ] **Step 4: Restore on reindex, with JSONL fallback**

Add `import json` to the imports at the top of `cli.py` (after `from datetime import datetime`):

```python
import json
```

In `reindex()`, after the existing `if meta.get("title"):` block (still inside the `for entry in raw_sessions:` loop, before `count += 1`):

```python
        if meta.get("model_usage"):
            db.replace_model_usage(entry["session_id"], {
                r["model"]: {
                    "input": r["input_tokens"],
                    "cache_read": r["cache_read_tokens"],
                    "cache_creation": r["cache_creation_tokens"],
                    "output": r["output_tokens"],
                }
                for r in meta["model_usage"]
            })
        else:
            # Old meta files predate model_usage — recompute from the JSONL.
            adapter = get_adapter(entry["tool"], claude_dir=_claude_dir())
            try:
                parsed = adapter.parse(entry["jsonl_path"])
            except (json.JSONDecodeError, OSError):
                parsed = None
            if parsed and parsed.model_usage:
                db.replace_model_usage(entry["session_id"], parsed.model_usage)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_stats.py tests/test_integration.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full suite**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/session_zoo/cli.py tests/test_stats.py tests/test_integration.py
git commit -m "feat(sync): persist model_usage through meta.json and reindex"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md` (commands table + new section)
- Modify: `README_zh.md` (mirror)
- Modify: `CHANGELOG.md` (entry)

- [ ] **Step 1: Update README.md**

In the commands table (after the `zoo title` row, README.md:99):

```markdown
| `zoo stats [id]` | Per-model token usage and cache hit rates (`--project/--tool/--since` filters; `--backfill` recomputes for all sessions) |
```

After the "## Session Titles" section, add:

```markdown
## Cache Stats

`zoo stats` shows per-model token usage and prompt cache hit rates, aggregated
across sessions (filter with `--project`, `--tool`, `--since`) or for a single
session via `zoo stats <id>`. Hit rate = `cache_read / (input + cache_read +
cache_creation)`; `?` means no input tokens were recorded.

Usage data is collected on `zoo import`, written to meta.json on `zoo sync`,
and restored by `zoo reindex`. After upgrading from a previous version, run
`zoo stats --backfill` once to compute usage for existing sessions.

Note: this release also fixes token double-counting (multi-block assistant
messages were counted once per block), so `total_tokens` shrinks for most
sessions and the next `zoo import` will mark them for re-sync. One-time cost.
```

- [ ] **Step 2: Update README_zh.md**

Add the matching row to the命令表 (same position, after the `zoo title` row):

```markdown
| `zoo stats [id]` | 按模型统计 token 用量与缓存命中率（支持 `--project/--tool/--since` 过滤；`--backfill` 为所有 session 重算） |
```

Add the matching section (after the Session Titles 对应章节):

```markdown
## 缓存统计

`zoo stats` 按模型展示 token 用量和提示词缓存命中率，可跨 session 聚合
（`--project`、`--tool`、`--since` 过滤），或用 `zoo stats <id>` 查看单个
session。命中率 = `cache_read / (input + cache_read + cache_creation)`；
`?` 表示没有输入 token 记录。

用量数据在 `zoo import` 时采集，`zoo sync` 时写入 meta.json，`zoo reindex`
时恢复。从旧版本升级后，运行一次 `zoo stats --backfill` 即可为已有 session
补算用量。

注意：本次同时修复了 token 重复计数问题（多 content block 的 assistant 消息
此前按 block 重复累计），多数 session 的 `total_tokens` 会变小，下次
`zoo import` 会将它们标记为待重新同步，属一次性成本。
```

- [ ] **Step 3: Update CHANGELOG.md**

Add under the latest unreleased/new version heading (follow the existing format in the file; create a new version section if the file lists released versions only):

```markdown
- feat: `zoo stats` — per-session / per-model token usage and cache hit rates,
  persisted through sync meta.json and reindex; `zoo stats --backfill` for
  existing sessions
- fix: token usage deduplicated by `message.id` — `total_tokens` no longer
  counts multi-block assistant messages once per block
```

- [ ] **Step 4: Commit**

```bash
git add README.md README_zh.md CHANGELOG.md
git commit -m "docs: document zoo stats command and cache hit rates"
```

---

## Verification (after all tasks)

1. `pytest -v` — full suite green.
2. Manual smoke test against the real local index:
   ```bash
   zoo stats --backfill
   zoo stats
   zoo stats <some-real-session-prefix>
   ```
   Expected: a table per model with plausible hit rates (interactive Claude Code sessions typically show >80% cache read share).
