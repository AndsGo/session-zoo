# session-zoo Skills Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 CLI skills + 1 SessionStart hook to session-zoo, auto-installed via `zoo init`, so AI tools (Claude Code, Codex) can seamlessly use zoo commands.

**Architecture:** Skills bundled as package data at `src/session_zoo/data/skills/`. `zoo init` copies SKILL.md files to `~/.claude/skills/` and merges a SessionStart hook into `~/.claude/settings.json`. A new `--quiet` flag on `zoo import` supports silent hook execution.

**Tech Stack:** Python, Typer CLI, hatchling (package data), JSON (settings.json merging)

---

## File Structure

**Create:**
- `src/session_zoo/data/skills/zoo-sync/SKILL.md`
- `src/session_zoo/data/skills/zoo-browse/SKILL.md`
- `src/session_zoo/data/skills/zoo-summarize/SKILL.md`
- `src/session_zoo/data/skills/zoo-tag/SKILL.md`
- `src/session_zoo/data/skills/zoo-restore/SKILL.md`
- `src/session_zoo/installer.py` — skill/hook installation logic
- `tests/test_installer.py` — tests for installer
- `tests/test_import_quiet.py` — tests for --quiet flag

**Modify:**
- `src/session_zoo/cli.py:41-51` — extend `init()` to call installer
- `src/session_zoo/cli.py:81-86` — add `--quiet` flag to `import_sessions()`
- `pyproject.toml` — add package data include for `data/`

---

## Chunk 1: --quiet flag and package data config

### Task 1: Add `--quiet` flag to `zoo import`

**Files:**
- Modify: `src/session_zoo/cli.py:81-132`
- Test: `tests/test_import_quiet.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_import_quiet.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_import_quiet.py -v`
Expected: FAIL — `--quiet` flag not recognized

- [ ] **Step 3: Implement --quiet flag**

Modify `src/session_zoo/cli.py` — add `quiet` parameter to `import_sessions()`:

```python
@app.command("import")
def import_sessions(
    tool: Optional[str] = typer.Option(None, help="Filter by tool"),
    project: Optional[str] = typer.Option(None, help="Filter by project"),
    since: Optional[str] = typer.Option(None, help="Only import after date (YYYY-MM-DD)"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only show output when new sessions found"),
):
```

And change the output section at the end of the function:

```python
    if quiet and total_imported == 0 and total_updated == 0:
        return

    parts = [f"[green]Imported: {total_imported}[/green]"]
    if total_updated:
        parts.append(f"[cyan]Updated: {total_updated}[/cyan]")
    parts.append(f"Skipped: {total_skipped}")
    console.print(" | ".join(parts))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_import_quiet.py -v`
Expected: 3 passed

- [ ] **Step 5: Run all tests to check for regressions**

Run: `python3 -m pytest --tb=short -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/session_zoo/cli.py tests/test_import_quiet.py
git commit -m "feat: add --quiet flag to zoo import for hook usage"
```

---

### Task 2: Configure package data in pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add hatchling package data config**

Add to `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/session_zoo"]

[tool.hatch.build.targets.wheel.force-include]
"src/session_zoo/data" = "session_zoo/data"
```

- [ ] **Step 2: Create data directory structure**

```bash
mkdir -p src/session_zoo/data/skills/{zoo-sync,zoo-browse,zoo-summarize,zoo-tag,zoo-restore}
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml src/session_zoo/data/
git commit -m "chore: configure package data for bundled skills"
```

---

## Chunk 2: Skill files

### Task 3: Write the 5 SKILL.md files

Each file must be < 200 words, description starts with "Use when...", bilingual triggers.

**Files:**
- Create: `src/session_zoo/data/skills/zoo-sync/SKILL.md`
- Create: `src/session_zoo/data/skills/zoo-browse/SKILL.md`
- Create: `src/session_zoo/data/skills/zoo-summarize/SKILL.md`
- Create: `src/session_zoo/data/skills/zoo-tag/SKILL.md`
- Create: `src/session_zoo/data/skills/zoo-restore/SKILL.md`

- [ ] **Step 1: Create zoo-sync/SKILL.md**

```markdown
---
name: zoo-sync
description: Use when the user wants to sync, backup, or push AI development sessions to GitHub. Triggers on "sync sessions", "backup sessions", "push sessions", "同步 session", "备份开发记录".
---

# Sync Sessions to GitHub

## Steps

1. Import latest sessions:
   ```bash
   zoo import
   ```

2. Sync to GitHub:
   ```bash
   zoo sync
   ```

## If Not Configured

If `zoo sync` fails with "Repo not set":
```bash
zoo init
zoo config set repo git@github.com:USER/REPO.git
```

## Dry Run

Preview without pushing:
```bash
zoo sync --dry-run
```
```

- [ ] **Step 2: Create zoo-browse/SKILL.md**

```markdown
---
name: zoo-browse
description: Use when the user wants to view, list, or browse AI development sessions or asks "what did I work on". Triggers on "list sessions", "show session", "查看开发记录", "最近做了什么", "what did I work on".
---

# Browse Development Sessions

## List Sessions

```bash
zoo list
zoo list --project myapp
zoo list --tag bugfix
zoo list --since 2026-03-01
```

## View Session Details

Use the ID prefix from `zoo list`:
```bash
zoo show <id>
zoo show <id> --markdown    # Full rendered conversation
zoo show <id> --raw         # Raw JSONL
```

## Search by Summary

```bash
zoo search "authentication"
```
```

- [ ] **Step 3: Create zoo-summarize/SKILL.md**

```markdown
---
name: zoo-summarize
description: Use when the user wants to generate AI summaries for development sessions. Triggers on "summarize session", "generate summary", "总结 session", "生成摘要".
---

# Summarize Sessions

## Summarize One

```bash
zoo summarize <id>
```

## Summarize All Unsummarized

```bash
zoo summarize
```

## Force Regenerate

```bash
zoo summarize <id> --force
```

## Provider Selection

Auto-detects: installed claude CLI > codex CLI > API key.
```bash
zoo summarize --provider claude-code <id>
zoo summarize --provider api <id>       # Needs: zoo config set ai-key <key>
```

## Check What Needs Summary

```bash
zoo list --no-summary
```
```

- [ ] **Step 4: Create zoo-tag/SKILL.md**

```markdown
---
name: zoo-tag
description: Use when the user wants to tag, categorize, or search AI development sessions. Triggers on "tag session", "add tags", "打标签", "归类 session", "search sessions".
---

# Tag & Search Sessions

## Add Tags

```bash
zoo tag <id> bugfix security
```

## Remove a Tag

```bash
zoo tag <id> --remove security
```

## List All Tags

```bash
zoo tags
```

## Filter Sessions by Tag

```bash
zoo list --tag bugfix
```

## Search by Summary Content

```bash
zoo search "login bug"
```
```

- [ ] **Step 5: Create zoo-restore/SKILL.md**

```markdown
---
name: zoo-restore
description: Use when the user wants to restore sessions on a new device, migrate sessions, or set up session-zoo from an existing repo. Triggers on "restore sessions", "migrate sessions", "恢复 session", "迁移设备", "new machine setup".
---

# Restore Sessions to New Device

Run these steps in order:

## 1. Initialize

```bash
zoo init
zoo config set repo git@github.com:USER/REPO.git
```

## 2. Clone Session Repo

```bash
zoo clone
```

## 3. Rebuild Local Index

```bash
zoo reindex
```

## 4. Restore Files for /resume

```bash
zoo restore                          # All sessions
zoo restore --project myapp          # One project only
```

After restore, sessions are available in `~/.claude/` for Claude Code `/resume`.
```

- [ ] **Step 6: Verify word counts**

```bash
wc -w src/session_zoo/data/skills/*/SKILL.md
```

Each should be < 200 words.

- [ ] **Step 7: Commit**

```bash
git add src/session_zoo/data/skills/
git commit -m "feat: add 5 bundled skill files for Claude Code/Codex"
```

---

## Chunk 3: Installer module and zoo init integration

### Task 4: Create installer module

**Files:**
- Create: `src/session_zoo/installer.py`
- Test: `tests/test_installer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_installer.py
"""Tests for skill and hook installer."""
import json
from pathlib import Path
from session_zoo.installer import install_skills, install_hook


def test_install_skills_copies_files(tmp_path):
    target = tmp_path / ".claude" / "skills"
    installed, skipped = install_skills(target)
    assert installed == 5
    assert skipped == 0
    assert (target / "zoo-sync" / "SKILL.md").exists()
    assert (target / "zoo-browse" / "SKILL.md").exists()
    assert (target / "zoo-summarize" / "SKILL.md").exists()
    assert (target / "zoo-tag" / "SKILL.md").exists()
    assert (target / "zoo-restore" / "SKILL.md").exists()


def test_install_skills_skips_existing(tmp_path):
    target = tmp_path / ".claude" / "skills"
    install_skills(target)
    # Modify one to simulate user customization
    (target / "zoo-sync" / "SKILL.md").write_text("custom content")
    installed, skipped = install_skills(target)
    assert installed == 0
    assert skipped == 5
    # User customization preserved
    assert (target / "zoo-sync" / "SKILL.md").read_text() == "custom content"


def test_install_hook_creates_settings(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    install_hook(claude_dir)
    settings = json.loads((claude_dir / "settings.json").read_text())
    hooks = settings["hooks"]["SessionStart"]
    assert any("zoo import" in h["command"] for h in hooks)


def test_install_hook_merges_existing(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    existing = {
        "hooks": {
            "SessionStart": [{"command": "echo hello"}],
            "PreToolUse": [{"command": "echo pre"}],
        },
        "other_key": "preserved",
    }
    (claude_dir / "settings.json").write_text(json.dumps(existing))
    install_hook(claude_dir)
    settings = json.loads((claude_dir / "settings.json").read_text())
    hooks = settings["hooks"]["SessionStart"]
    # Both original and zoo hook present
    assert any("echo hello" in h["command"] for h in hooks)
    assert any("zoo import" in h["command"] for h in hooks)
    # Other hooks preserved
    assert settings["hooks"]["PreToolUse"] == [{"command": "echo pre"}]
    # Other keys preserved
    assert settings["other_key"] == "preserved"


def test_install_hook_no_duplicate(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    install_hook(claude_dir)
    install_hook(claude_dir)  # second call
    settings = json.loads((claude_dir / "settings.json").read_text())
    hooks = settings["hooks"]["SessionStart"]
    zoo_hooks = [h for h in hooks if "zoo import" in h["command"]]
    assert len(zoo_hooks) == 1  # no duplicate
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_installer.py -v`
Expected: FAIL — `session_zoo.installer` does not exist

- [ ] **Step 3: Implement installer.py**

```python
# src/session_zoo/installer.py
"""Install session-zoo skills and hooks into AI tool directories."""
import json
import shutil
from importlib import resources
from pathlib import Path


def _get_data_path() -> Path:
    """Get the path to bundled data files."""
    return Path(resources.files("session_zoo")) / "data"


def install_skills(skills_dir: Path) -> tuple[int, int]:
    """Copy bundled SKILL.md files to the target skills directory.

    Returns (installed_count, skipped_count).
    Skips skills that already exist (preserves user customizations).
    """
    data = _get_data_path() / "skills"
    installed = 0
    skipped = 0

    for skill_src in sorted(data.iterdir()):
        if not skill_src.is_dir():
            continue
        dest = skills_dir / skill_src.name
        if (dest / "SKILL.md").exists():
            skipped += 1
            continue
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(skill_src / "SKILL.md"), str(dest / "SKILL.md"))
        installed += 1

    return installed, skipped


_ZOO_HOOK_CMD = "zoo import --quiet 2>/dev/null || true"


def install_hook(claude_dir: Path) -> bool:
    """Merge SessionStart hook into claude settings.json.

    Returns True if hook was added, False if already present.
    """
    settings_path = claude_dir / "settings.json"

    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        settings = {}

    hooks = settings.setdefault("hooks", {})
    session_start = hooks.setdefault("SessionStart", [])

    # Check for duplicate
    for entry in session_start:
        if "zoo import" in entry.get("command", ""):
            return False

    session_start.append({"command": _ZOO_HOOK_CMD})
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_installer.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/session_zoo/installer.py tests/test_installer.py
git commit -m "feat: add installer module for skills and hooks"
```

---

### Task 5: Integrate installer into `zoo init`

**Files:**
- Modify: `src/session_zoo/cli.py:41-51`
- Test: `tests/test_e2e.py` (add new tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_e2e.py` in `TestFirstTimeSetup`:

```python
def test_init_installs_skills(self, env):
    _run(["init"], env)
    skills_dir = env["claude_dir"] / "skills"
    assert (skills_dir / "zoo-sync" / "SKILL.md").exists()
    assert (skills_dir / "zoo-browse" / "SKILL.md").exists()
    assert (skills_dir / "zoo-summarize" / "SKILL.md").exists()
    assert (skills_dir / "zoo-tag" / "SKILL.md").exists()
    assert (skills_dir / "zoo-restore" / "SKILL.md").exists()


def test_init_installs_hook(self, env):
    _run(["init"], env)
    settings_path = env["claude_dir"] / "settings.json"
    assert settings_path.exists()
    import json
    settings = json.loads(settings_path.read_text())
    hooks = settings["hooks"]["SessionStart"]
    assert any("zoo import" in h["command"] for h in hooks)


def test_init_skip_skills_flag(self, env):
    _run(["init", "--skip-skills"], env)
    skills_dir = env["claude_dir"] / "skills"
    assert not (skills_dir / "zoo-sync").exists()


def test_init_skip_hooks_flag(self, env):
    _run(["init", "--skip-hooks"], env)
    settings_path = env["claude_dir"] / "settings.json"
    assert not settings_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_e2e.py::TestFirstTimeSetup::test_init_installs_skills -v`
Expected: FAIL

- [ ] **Step 3: Update zoo init command**

Modify `src/session_zoo/cli.py` — update `init()`:

```python
@app.command()
def init(
    skip_skills: bool = typer.Option(False, help="Skip skill installation"),
    skip_hooks: bool = typer.Option(False, help="Skip hook installation"),
):
    """Initialize session-zoo configuration."""
    d = _config_dir()
    d.mkdir(parents=True, exist_ok=True)
    config_path = d / "config.toml"
    if not config_path.exists():
        save_config(Config(config_dir=d), config_path)
    db = SessionDB(d / "index.db")
    db.init()
    console.print(f"[green]Initialized session-zoo at {d}[/green]")

    # Install skills
    if not skip_skills:
        from session_zoo.installer import install_skills
        claude_dir = _claude_dir()
        skills_dir = claude_dir / "skills"
        installed, skipped = install_skills(skills_dir)
        if installed:
            console.print(f"[green]Installed {installed} skill(s)[/green]")
        if skipped:
            console.print(f"[dim]Skipped {skipped} existing skill(s)[/dim]")

    # Install hook
    if not skip_hooks:
        from session_zoo.installer import install_hook
        claude_dir = _claude_dir()
        claude_dir.mkdir(parents=True, exist_ok=True)
        added = install_hook(claude_dir)
        if added:
            console.print("[green]Installed SessionStart hook[/green]")
        else:
            console.print("[dim]SessionStart hook already installed[/dim]")
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `python3 -m pytest tests/test_e2e.py::TestFirstTimeSetup -v`
Expected: all pass

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest --tb=short -q`
Expected: all pass (160+ tests)

- [ ] **Step 6: Commit**

```bash
git add src/session_zoo/cli.py tests/test_e2e.py
git commit -m "feat: zoo init installs skills and SessionStart hook"
```

---

## Chunk 4: Final verification

### Task 6: End-to-end verification

- [ ] **Step 1: Run complete test suite**

```bash
python3 -m pytest --tb=short -q
```

Expected: all pass

- [ ] **Step 2: Manual verification of zoo init**

```bash
# In a temp dir, test the full flow:
zoo init
ls ~/.claude/skills/zoo-*/SKILL.md
cat ~/.claude/settings.json
```

Verify:
- 5 SKILL.md files present
- settings.json has SessionStart hook with `zoo import --quiet`

- [ ] **Step 3: Verify skill word counts**

```bash
wc -w src/session_zoo/data/skills/*/SKILL.md
```

All should be < 200 words.

- [ ] **Step 4: Test quiet import via simulated hook**

```bash
zoo import --quiet   # should produce no output if nothing new
```

- [ ] **Step 5: Final commit with all changes**

If any loose changes remain:
```bash
git add -A
git commit -m "chore: final cleanup for zoo skills feature"
```
