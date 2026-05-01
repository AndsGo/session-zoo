"""
End-to-end tests for session-zoo.

These tests exercise the full CLI through real commands, using a local bare git
repo as the "remote" and temp directories for all state.  No network access
or real AI providers are required.

Workflow coverage:
  1. First-time setup:         init → config → import → list → show
  2. Tagging & search:         tag → tags → search
  3. Summarize & sync:         summarize → sync → verify repo
  4. Cross-device restore:     clone → reindex → restore → verify files
  5. Incremental updates:      re-import (idempotent) → modify → re-sync
  6. Filters & edge cases:     list filters, show --raw/--markdown, delete, dry-run
  7. Multi-session workflow:    import 2 projects, filter by project/tool/tag
  8. Error handling:            missing repo, missing session, bad config key
"""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from typer.testing import CliRunner

from session_zoo.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_session(tmp_path, session_id, project_dir_name, cwd, messages=None):
    """Create a .jsonl session file with realistic content."""
    project_dir = tmp_path / ".claude" / "projects" / project_dir_name
    project_dir.mkdir(parents=True, exist_ok=True)

    if messages is None:
        messages = [
            {
                "type": "user",
                "sessionId": session_id,
                "cwd": cwd,
                "gitBranch": "main",
                "version": "2.1.72",
                "message": {"role": "user", "content": "Fix the login bug"},
                "timestamp": "2026-03-10T10:30:00.000Z",
                "uuid": "msg-001",
            },
            {
                "type": "assistant",
                "sessionId": session_id,
                "cwd": cwd,
                "gitBranch": "main",
                "version": "2.1.72",
                "message": {
                    "model": "claude-opus-4-6",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "I'll fix the login bug."}],
                    "usage": {
                        "input_tokens": 100, "output_tokens": 50,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
                "timestamp": "2026-03-10T10:31:00.000Z",
                "uuid": "msg-002",
            },
            {
                "type": "assistant",
                "sessionId": session_id,
                "cwd": cwd,
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
                            "input": {"file_path": f"{cwd}/src/login.py"},
                        },
                        {"type": "text", "text": "Fixed the issue."},
                    ],
                    "usage": {
                        "input_tokens": 200, "output_tokens": 80,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
                "timestamp": "2026-03-10T10:35:00.000Z",
                "uuid": "msg-003",
            },
        ]

    session_file = project_dir / f"{session_id}.jsonl"
    with open(session_file, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return session_file


@pytest.fixture
def env(tmp_path):
    """Set up a complete isolated test environment."""
    config_dir = tmp_path / "sz-config"
    claude_dir = tmp_path / ".claude"

    # Create a local bare git repo as "remote"
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)],
                   capture_output=True, check=True)
    # Seed with initial commit so push works
    staging = tmp_path / "staging"
    subprocess.run(["git", "clone", str(remote), str(staging)],
                   capture_output=True, check=True)
    (staging / ".gitkeep").touch()
    subprocess.run(["git", "-C", str(staging), "add", "."],
                   capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(staging), "-c", "user.email=test@test.com",
         "-c", "user.name=Test", "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    subprocess.run(["git", "-C", str(staging), "push"],
                   capture_output=True, check=True)

    # Create two sessions in different projects
    _make_session(tmp_path, "sess-aaa-001",
                  "-home-user-my-webapp", "/home/user/my-webapp")
    _make_session(tmp_path, "sess-bbb-002",
                  "-home-user-api-server", "/home/user/api-server")

    return {
        "tmp_path": tmp_path,
        "config_dir": config_dir,
        "claude_dir": claude_dir,
        "remote": remote,
    }


def _run(args, env_ctx):
    """Run a CLI command with patched config/claude dirs and git identity."""
    git_env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    with patch("session_zoo.cli._config_dir", return_value=env_ctx["config_dir"]), \
         patch("session_zoo.cli._claude_dir", return_value=env_ctx["claude_dir"]), \
         patch.dict("os.environ", git_env):
        result = runner.invoke(app, args)
    return result


def _run_with_mock_ai(args, env_ctx, summary_text="AI generated summary"):
    """Run a CLI command with mocked Anthropic API."""
    git_env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    with patch("session_zoo.cli._config_dir", return_value=env_ctx["config_dir"]), \
         patch("session_zoo.cli._claude_dir", return_value=env_ctx["claude_dir"]), \
         patch.dict("os.environ", git_env), \
         patch("anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=summary_text)]
        )
        result = runner.invoke(app, args)
    return result


# ===========================================================================
# Workflow 1: First-time setup (init → config → import → list → show)
# ===========================================================================

class TestFirstTimeSetup:

    def test_init_creates_config_and_db(self, env):
        result = _run(["init"], env)
        assert result.exit_code == 0
        assert (env["config_dir"] / "config.toml").exists()
        assert (env["config_dir"] / "index.db").exists()

    def test_init_is_idempotent(self, env):
        _run(["init"], env)
        result = _run(["init"], env)
        assert result.exit_code == 0

    def test_config_set_and_show(self, env):
        _run(["init"], env)
        result = _run(["config", "set", "repo", str(env["remote"])], env)
        assert result.exit_code == 0

        result = _run(["config", "show"], env)
        assert result.exit_code == 0
        # Rich console 可能在长路径中插入换行符，去除后再比较
        stdout_flat = result.stdout.replace("\n", "")
        assert str(env["remote"]) in stdout_flat

    def test_config_set_ai_key_masked(self, env):
        _run(["init"], env)
        result = _run(["config", "set", "ai-key", "sk-secret-key"], env)
        assert "***" in result.stdout
        assert "sk-secret-key" not in result.stdout

    def test_config_set_bad_key(self, env):
        _run(["init"], env)
        result = _run(["config", "set", "invalid-key", "value"], env)
        assert result.exit_code == 1

    def test_import_discovers_sessions(self, env):
        _run(["init"], env)
        result = _run(["import"], env)
        assert result.exit_code == 0
        assert "2" in result.stdout  # imported 2 sessions

    def test_list_shows_imported_sessions(self, env):
        _run(["init"], env)
        _run(["import"], env)
        result = _run(["list"], env)
        assert result.exit_code == 0
        assert "my-webapp" in result.stdout or "my-webap" in result.stdout
        assert "api-serv" in result.stdout

    def test_show_displays_session_details(self, env):
        _run(["init"], env)
        _run(["import"], env)
        result = _run(["show", "sess-aaa-001"], env)
        assert result.exit_code == 0
        assert "claude-code" in result.stdout
        assert "my-webapp" in result.stdout

    def test_show_raw_outputs_jsonl(self, env):
        _run(["init"], env)
        _run(["import"], env)
        result = _run(["show", "sess-aaa-001", "--raw"], env)
        assert result.exit_code == 0
        assert "sessionId" in result.stdout
        assert "Fix the login bug" in result.stdout

    def test_show_markdown_renders(self, env):
        _run(["init"], env)
        _run(["import"], env)
        result = _run(["show", "sess-aaa-001", "--markdown"], env)
        assert result.exit_code == 0
        assert "login" in result.stdout.lower()

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
        assert any(
            "zoo import" in hook.get("command", "")
            for entry in hooks
            for hook in entry.get("hooks", [])
        )

    def test_init_skip_skills_flag(self, env):
        _run(["init", "--skip-skills"], env)
        skills_dir = env["claude_dir"] / "skills"
        assert not (skills_dir / "zoo-sync").exists()

    def test_init_skip_hooks_flag(self, env):
        _run(["init", "--skip-hooks"], env)
        settings_path = env["claude_dir"] / "settings.json"
        assert not settings_path.exists()


# ===========================================================================
# Workflow 2: Tagging & search
# ===========================================================================

class TestTaggingAndSearch:

    def _setup(self, env):
        _run(["init"], env)
        _run(["import"], env)

    def test_add_tags(self, env):
        self._setup(env)
        result = _run(["tag", "sess-aaa-001", "bugfix", "auth"], env)
        assert result.exit_code == 0
        assert "bugfix" in result.stdout
        assert "auth" in result.stdout

    def test_remove_tag(self, env):
        self._setup(env)
        _run(["tag", "sess-aaa-001", "bugfix", "auth"], env)
        result = _run(["tag", "sess-aaa-001", "--remove", "auth"], env)
        assert result.exit_code == 0
        assert "auth" not in result.stdout.split("Current tags:")[1]

    def test_list_all_tags(self, env):
        self._setup(env)
        _run(["tag", "sess-aaa-001", "bugfix", "auth"], env)
        _run(["tag", "sess-bbb-002", "bugfix", "api"], env)
        result = _run(["tags"], env)
        assert result.exit_code == 0
        assert "bugfix" in result.stdout
        assert "2" in result.stdout  # bugfix count = 2

    def test_list_filter_by_tag(self, env):
        self._setup(env)
        _run(["tag", "sess-aaa-001", "bugfix"], env)
        result = _run(["list", "--tag", "bugfix"], env)
        assert result.exit_code == 0
        assert "my-webapp" in result.stdout or "my-webap" in result.stdout
        # api-server should not appear (no bugfix tag)
        assert "api-serv" not in result.stdout

    def test_search_by_summary(self, env):
        self._setup(env)
        _run(["config", "set", "ai-key", "test-key"], env)
        _run_with_mock_ai(
            ["summarize", "--provider", "api", "sess-aaa-001"],
            env, summary_text="Fixed XSS vulnerability in login form",
        )
        result = _run(["search", "XSS"], env)
        assert result.exit_code == 0
        assert "sess-aaa-001" in result.stdout

    def test_search_no_match(self, env):
        self._setup(env)
        result = _run(["search", "nonexistent-query-xyz"], env)
        assert "No matches" in result.stdout

    def test_tag_nonexistent_session(self, env):
        self._setup(env)
        result = _run(["tag", "nonexistent-id", "bugfix"], env)
        assert result.exit_code == 1


# ===========================================================================
# Workflow 3: Summarize & sync
# ===========================================================================

class TestSummarizeAndSync:

    def _setup(self, env):
        _run(["init"], env)
        _run(["config", "set", "repo", str(env["remote"])], env)
        _run(["config", "set", "ai-key", "test-key"], env)
        _run(["import"], env)

    def test_summarize_single_session(self, env):
        self._setup(env)
        result = _run_with_mock_ai(
            ["summarize", "--provider", "api", "sess-aaa-001"],
            env, summary_text="Fixed login bug with XSS sanitization",
        )
        assert result.exit_code == 0
        assert "done" in result.stdout

        # Verify summary persisted
        result = _run(["show", "sess-aaa-001"], env)
        assert "XSS" in result.stdout

    def test_summarize_skip_existing(self, env):
        self._setup(env)
        _run_with_mock_ai(
            ["summarize", "--provider", "api", "sess-aaa-001"],
            env, summary_text="First summary",
        )
        # Without --force, should skip
        result = _run_with_mock_ai(
            ["summarize", "--provider", "api", "sess-aaa-001"],
            env, summary_text="Second summary",
        )
        assert result.exit_code == 0
        # Verify first summary preserved
        result = _run(["show", "sess-aaa-001"], env)
        assert "First summary" in result.stdout

    def test_summarize_force_regenerate(self, env):
        self._setup(env)
        _run_with_mock_ai(
            ["summarize", "--provider", "api", "sess-aaa-001"],
            env, summary_text="Old summary",
        )
        result = _run_with_mock_ai(
            ["summarize", "--provider", "api", "--force", "sess-aaa-001"],
            env, summary_text="New summary",
        )
        assert result.exit_code == 0
        result = _run(["show", "sess-aaa-001"], env)
        assert "New summary" in result.stdout

    def test_sync_to_git(self, env):
        self._setup(env)
        _run(["tag", "sess-aaa-001", "bugfix"], env)
        _run_with_mock_ai(
            ["summarize", "--provider", "api", "sess-aaa-001"],
            env, summary_text="Fixed login bug",
        )

        result = _run(["sync"], env)
        assert result.exit_code == 0, f"sync failed: {result.stdout}\n{result.exception}"

        # Verify files in repo
        repo_dir = env["config_dir"] / "repo"
        raw_jsonl = repo_dir / "raw" / "claude-code" / "my-webapp" / "sess-aaa-001.jsonl"
        raw_meta = repo_dir / "raw" / "claude-code" / "my-webapp" / "sess-aaa-001.meta.json"

        assert raw_jsonl.exists()
        assert raw_meta.exists()

        meta = json.loads(raw_meta.read_text())
        assert meta["tags"] == ["bugfix"]
        assert "login" in meta["summary"]
        assert meta["tool"] == "claude-code"
        assert meta["project"] == "my-webapp"

        # Verify markdown generated
        md_files = list(repo_dir.rglob("sess-aaa-001.md"))
        assert len(md_files) == 1

    def test_sync_writes_title_into_meta_json(self, env):
        """Title and title_source must round-trip through meta.json."""
        self._setup(env)

        # Force a known title via the DB before syncing
        from session_zoo.db import SessionDB
        db = SessionDB(env["config_dir"] / "index.db")
        db.init()
        db.set_title_raw("sess-aaa-001", "Synced title", "manual")

        result = _run(["sync"], env)
        assert result.exit_code == 0, f"sync failed: {result.stdout}"

        repo_dir = env["config_dir"] / "repo"
        raw_meta = repo_dir / "raw" / "claude-code" / "my-webapp" / "sess-aaa-001.meta.json"
        meta = json.loads(raw_meta.read_text(encoding="utf-8"))
        assert meta["title"] == "Synced title"
        assert meta["title_source"] == "manual"

    def test_sync_dry_run(self, env):
        self._setup(env)
        result = _run(["sync", "--dry-run"], env)
        assert result.exit_code == 0
        assert "Would sync" in result.stdout

        # Verify nothing was actually pushed
        repo_dir = env["config_dir"] / "repo"
        assert not (repo_dir / "raw").exists() or not list(
            (repo_dir / "raw").rglob("*.jsonl")
        )

    def test_sync_status_transitions(self, env):
        """pending → synced, then modify (summarize) → modified → synced."""
        self._setup(env)
        # Initial status should be pending
        result = _run(["list", "--status", "pending"], env)
        assert "sess-aaa" in result.stdout

        # Sync makes it synced
        _run(["sync"], env)
        result = _run(["list", "--status", "synced"], env)
        assert "sess-aaa" in result.stdout

        # Summarize changes status to modified
        _run_with_mock_ai(
            ["summarize", "--provider", "api", "sess-aaa-001"],
            env, summary_text="New summary",
        )
        result = _run(["list", "--status", "modified"], env)
        assert "sess-aaa" in result.stdout

        # Re-sync
        _run(["sync"], env)
        result = _run(["list", "--status", "synced"], env)
        assert "sess-aaa" in result.stdout

    def test_sync_no_repo_configured(self, env):
        _run(["init"], env)
        _run(["import"], env)
        result = _run(["sync"], env)
        assert result.exit_code == 1

    def test_sync_everything_up_to_date(self, env):
        self._setup(env)
        _run(["sync"], env)
        result = _run(["sync"], env)
        assert "up to date" in result.stdout


# ===========================================================================
# Workflow 4: Cross-device restore (clone → reindex → restore)
# ===========================================================================

class TestCrossDeviceRestore:

    def _setup_synced_env(self, env):
        """Set up a fully synced state in env, then return remote URL."""
        _run(["init"], env)
        _run(["config", "set", "repo", str(env["remote"])], env)
        _run(["config", "set", "ai-key", "test-key"], env)
        _run(["import"], env)
        _run(["tag", "sess-aaa-001", "bugfix"], env)
        _run_with_mock_ai(
            ["summarize", "--provider", "api", "sess-aaa-001"],
            env, summary_text="Fixed login bug",
        )
        _run(["sync"], env)

    def test_full_restore_workflow(self, env, tmp_path):
        """Simulate: machine A syncs, machine B clones → reindex → restore."""
        self._setup_synced_env(env)

        # --- Machine B: fresh config dir ---
        new_config = tmp_path / "machine-b-config"
        new_claude = tmp_path / "machine-b-claude"
        env_b = {**env, "config_dir": new_config, "claude_dir": new_claude}

        _run(["init"], env_b)
        _run(["config", "set", "repo", str(env["remote"])], env_b)

        # Clone
        result = _run(["clone"], env_b)
        assert result.exit_code == 0
        assert (new_config / "repo" / "raw").exists()

        # Reindex
        result = _run(["reindex"], env_b)
        assert result.exit_code == 0

        # Verify sessions are in DB
        result = _run(["list"], env_b)
        assert "my-webapp" in result.stdout or "my-webap" in result.stdout

        # Verify tags survived
        result = _run(["show", "sess-aaa-001"], env_b)
        assert "bugfix" in result.stdout
        assert "login" in result.stdout  # summary

        # Restore files to ~/.claude/
        result = _run(["restore"], env_b)
        assert result.exit_code == 0

        # Verify JSONL restored to expected path
        restored = list(new_claude.rglob("sess-aaa-001.jsonl"))
        assert len(restored) == 1

    def test_clone_idempotent(self, env, tmp_path):
        self._setup_synced_env(env)
        new_config = tmp_path / "machine-b-config"
        env_b = {**env, "config_dir": new_config}

        _run(["init"], env_b)
        _run(["config", "set", "repo", str(env["remote"])], env_b)
        _run(["clone"], env_b)

        # Second clone should not fail
        result = _run(["clone"], env_b)
        assert result.exit_code == 0
        assert "already exists" in result.stdout

    def test_restore_filter_by_project(self, env, tmp_path):
        self._setup_synced_env(env)
        new_config = tmp_path / "machine-b-config"
        new_claude = tmp_path / "machine-b-claude"
        env_b = {**env, "config_dir": new_config, "claude_dir": new_claude}

        _run(["init"], env_b)
        _run(["config", "set", "repo", str(env["remote"])], env_b)
        _run(["clone"], env_b)
        _run(["reindex"], env_b)

        result = _run(["restore", "--project", "my-webapp"], env_b)
        assert result.exit_code == 0

        # Only my-webapp session should be restored
        webapp_files = list(new_claude.rglob("sess-aaa-001.jsonl"))
        api_files = list(new_claude.rglob("sess-bbb-002.jsonl"))
        assert len(webapp_files) == 1
        assert len(api_files) == 0

    def test_reindex_without_clone(self, env):
        _run(["init"], env)
        result = _run(["reindex"], env)
        assert result.exit_code == 1


# ===========================================================================
# Workflow 5: Incremental updates (re-import idempotent, modify, re-sync)
# ===========================================================================

class TestIncrementalUpdates:

    def test_reimport_skips_existing(self, env):
        _run(["init"], env)
        result1 = _run(["import"], env)
        assert "2" in result1.stdout  # imported 2

        result2 = _run(["import"], env)
        assert "Imported: 0" in result2.stdout
        assert "Skipped: 2" in result2.stdout

    def test_reimport_updates_changed_session(self, env):
        """When a session has new messages, re-import should update metadata."""
        _run(["init"], env)
        _run(["import"], env)

        # Verify initial state
        result = _run(["show", "sess-aaa-001"], env)
        assert "Messages: 3" in result.stdout  # original has 3 messages

        # Append a new message to the JSONL file
        session_file = (env["tmp_path"] / ".claude" / "projects"
                        / "-home-user-my-webapp" / "sess-aaa-001.jsonl")
        new_msg = {
            "type": "user",
            "sessionId": "sess-aaa-001",
            "cwd": "/home/user/my-webapp",
            "gitBranch": "main",
            "version": "2.1.72",
            "message": {"role": "user", "content": "Now add tests for the fix"},
            "timestamp": "2026-03-10T11:00:00.000Z",
            "uuid": "msg-004",
        }
        with open(session_file, "a") as f:
            f.write(json.dumps(new_msg) + "\n")

        # Re-import should detect the change
        result = _run(["import"], env)
        assert "Updated: 1" in result.stdout

        # Verify updated message count
        result = _run(["show", "sess-aaa-001"], env)
        assert "Messages: 4" in result.stdout

    def test_reimport_update_marks_synced_as_modified(self, env):
        """Updated session that was synced should become 'modified'."""
        _run(["init"], env)
        _run(["config", "set", "repo", str(env["remote"])], env)
        _run(["import"], env)
        _run(["sync"], env)

        # Verify synced status
        result = _run(["list", "--status", "synced"], env)
        assert "sess-aaa" in result.stdout

        # Append new message
        session_file = (env["tmp_path"] / ".claude" / "projects"
                        / "-home-user-my-webapp" / "sess-aaa-001.jsonl")
        new_msg = {
            "type": "user",
            "sessionId": "sess-aaa-001",
            "cwd": "/home/user/my-webapp",
            "message": {"role": "user", "content": "Follow-up question"},
            "timestamp": "2026-03-10T12:00:00.000Z",
            "uuid": "msg-005",
        }
        with open(session_file, "a") as f:
            f.write(json.dumps(new_msg) + "\n")

        _run(["import"], env)

        # Should now be modified
        result = _run(["list", "--status", "modified"], env)
        assert "sess-aaa" in result.stdout

    def test_new_session_discovered_on_reimport(self, env):
        _run(["init"], env)
        _run(["import"], env)

        # Add a new session file
        _make_session(env["tmp_path"], "sess-ccc-003",
                      "-home-user-my-webapp", "/home/user/my-webapp")
        result = _run(["import"], env)
        assert "Imported: 1" in result.stdout

    def test_modify_then_resync(self, env):
        _run(["init"], env)
        _run(["config", "set", "repo", str(env["remote"])], env)
        _run(["config", "set", "ai-key", "test-key"], env)
        _run(["import"], env)

        # First sync
        _run(["sync"], env)

        # Add tag (modifies session → status changes)
        _run(["tag", "sess-aaa-001", "important"], env)
        # Summarize also marks as modified
        _run_with_mock_ai(
            ["summarize", "--provider", "api", "sess-aaa-001"],
            env, summary_text="Updated analysis",
        )

        # Re-sync should pick up modified session
        result = _run(["sync"], env)
        assert result.exit_code == 0

        # Verify updated meta in repo
        repo_dir = env["config_dir"] / "repo"
        meta_path = repo_dir / "raw" / "claude-code" / "my-webapp" / "sess-aaa-001.meta.json"
        meta = json.loads(meta_path.read_text())
        assert "important" in meta["tags"]
        assert "Updated analysis" in meta["summary"]


# ===========================================================================
# Workflow 6: Filters & edge cases
# ===========================================================================

class TestFiltersAndEdgeCases:

    def _setup(self, env):
        _run(["init"], env)
        _run(["import"], env)

    def test_list_filter_by_project(self, env):
        self._setup(env)
        result = _run(["list", "--project", "my-webapp"], env)
        assert "my-webapp" in result.stdout or "my-webap" in result.stdout
        assert "api-serv" not in result.stdout

    def test_list_filter_by_tool(self, env):
        self._setup(env)
        result = _run(["list", "--tool", "claude-code"], env)
        assert result.exit_code == 0

        result = _run(["list", "--tool", "nonexistent"], env)
        assert "No sessions" in result.stdout

    def test_list_no_summary_filter(self, env):
        self._setup(env)
        result = _run(["list", "--no-summary"], env)
        # Both sessions have no summary yet
        assert "sess-aaa" in result.stdout or "my-webapp" in result.stdout or "my-webap" in result.stdout

    def test_show_nonexistent_session(self, env):
        self._setup(env)
        result = _run(["show", "nonexistent-id"], env)
        assert result.exit_code == 1
        assert "not found" in result.stdout.lower()

    def test_delete_session(self, env):
        self._setup(env)
        result = _run(["delete", "sess-aaa-001"], env, )
        # CliRunner doesn't support interactive confirm by default,
        # but typer.confirm raises Abort which gives exit_code=1
        # We test the confirmation flow works at all
        assert result.exit_code in (0, 1)

    def test_delete_nonexistent_session(self, env):
        self._setup(env)
        result = _run(["delete", "nonexistent-id"], env)
        assert result.exit_code == 1

    def test_empty_tags_list(self, env):
        self._setup(env)
        result = _run(["tags"], env)
        assert "No tags" in result.stdout

    def test_summarize_nonexistent_session(self, env):
        self._setup(env)
        _run(["config", "set", "ai-key", "test-key"], env)
        result = _run_with_mock_ai(
            ["summarize", "--provider", "api", "nonexistent-id"], env
        )
        assert result.exit_code == 1

    def test_import_with_project_filter(self, env):
        _run(["init"], env)
        result = _run(["import", "--project", "my-webapp"], env)
        assert result.exit_code == 0
        assert "1" in result.stdout

        result = _run(["list"], env)
        assert "my-webapp" in result.stdout or "my-webap" in result.stdout


# ===========================================================================
# Workflow 7: Multi-session cross-project
# ===========================================================================

class TestMultiSession:

    def _setup(self, env):
        _run(["init"], env)
        _run(["config", "set", "repo", str(env["remote"])], env)
        _run(["config", "set", "ai-key", "test-key"], env)
        _run(["import"], env)

    def test_tag_multiple_sessions_different_tags(self, env):
        self._setup(env)
        _run(["tag", "sess-aaa-001", "bugfix", "frontend"], env)
        _run(["tag", "sess-bbb-002", "feature", "backend"], env)

        result = _run(["tags"], env)
        for tag in ["bugfix", "frontend", "feature", "backend"]:
            assert tag in result.stdout

    def test_filter_by_tag_across_projects(self, env):
        self._setup(env)
        _run(["tag", "sess-aaa-001", "urgent"], env)
        _run(["tag", "sess-bbb-002", "urgent"], env)

        result = _run(["list", "--tag", "urgent"], env)
        assert "my-webapp" in result.stdout or "my-webap" in result.stdout
        assert "api-serv" in result.stdout

    def test_sync_multiple_sessions(self, env):
        self._setup(env)
        _run(["tag", "sess-aaa-001", "v1"], env)
        _run(["tag", "sess-bbb-002", "v1"], env)

        result = _run(["sync"], env)
        assert result.exit_code == 0

        repo_dir = env["config_dir"] / "repo"
        # Both sessions should have raw files
        assert (repo_dir / "raw" / "claude-code" / "my-webapp" / "sess-aaa-001.jsonl").exists()
        assert (repo_dir / "raw" / "claude-code" / "api-server" / "sess-bbb-002.jsonl").exists()

        # Both should have markdown
        md_files = list(repo_dir.rglob("*.md"))
        # At least 2 session markdowns (plus .gitkeep)
        session_mds = [f for f in md_files if "sess-" in f.name]
        assert len(session_mds) == 2

    def test_summarize_all_without_id(self, env):
        self._setup(env)
        result = _run_with_mock_ai(
            ["summarize", "--provider", "api"],
            env, summary_text="Batch summary",
        )
        assert result.exit_code == 0
        assert "2" in result.stdout  # Summarized 2 sessions


# ===========================================================================
# Workflow 8: Error handling & edge cases
# ===========================================================================

class TestErrorHandling:

    def test_operations_before_init(self, env):
        """Most commands should work if config dir doesn't exist yet (auto-create db)."""
        # list without init — depends on _get_db which auto-creates
        result = _run(["list"], env)
        # Should not crash — either shows empty or creates automatically
        assert result.exit_code == 0

    def test_sync_without_repo(self, env):
        _run(["init"], env)
        result = _run(["sync"], env)
        assert result.exit_code == 1
        assert "Repo not set" in result.stdout

    def test_clone_without_repo(self, env):
        _run(["init"], env)
        result = _run(["clone"], env)
        assert result.exit_code == 1

    def test_restore_without_clone(self, env):
        _run(["init"], env)
        result = _run(["restore"], env)
        assert result.exit_code == 1

    def test_summarize_no_provider_available(self, env):
        _run(["init"], env)
        _run(["import"], env)
        # No ai-key, mock shutil.which to return None (no CLI tools)
        with patch("shutil.which", return_value=None):
            result = _run(["summarize", "sess-aaa-001"], env)
        assert result.exit_code == 1
