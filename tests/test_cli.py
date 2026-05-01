"""Regression tests for all CLI commands."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from session_zoo.cli import app

runner = CliRunner()


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _setup_config(tmp_path):
    """Create config dir with empty config."""
    config_dir = tmp_path / ".session-zoo"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("")
    return config_dir


def _setup_db_with_session(tmp_path, sample_claude_session, *, session_id="test-session-001"):
    """Import a session into the DB and return (config_dir, claude_dir)."""
    config_dir = tmp_path / ".session-zoo"
    claude_dir = sample_claude_session / ".claude"
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["init"])
        runner.invoke(app, ["import"])
    return config_dir, claude_dir


# ─── init ──────────────────────────────────────────────────────────────────────

def test_init_creates_config_dir(tmp_path):
    with patch("session_zoo.cli._config_dir", return_value=tmp_path / ".session-zoo"):
        result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (tmp_path / ".session-zoo").exists()
    assert (tmp_path / ".session-zoo" / "index.db").exists()


def test_init_idempotent(tmp_path):
    with patch("session_zoo.cli._config_dir", return_value=tmp_path / ".session-zoo"):
        runner.invoke(app, ["init"])
        result = runner.invoke(app, ["init"])
    assert result.exit_code == 0


# ─── config show ───────────────────────────────────────────────────────────────

def test_config_show(tmp_path):
    config_dir = _setup_config(tmp_path)
    (config_dir / "config.toml").write_text('repo = "https://github.com/user/repo.git"\n')
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "github.com" in result.stdout


def test_config_show_defaults(tmp_path):
    config_dir = _setup_config(tmp_path)
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "(not set)" in result.stdout


# ─── config set ────────────────────────────────────────────────────────────────

def test_config_set_repo(tmp_path):
    config_dir = _setup_config(tmp_path)
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["config", "set", "repo", "https://github.com/user/repo.git"])
    assert result.exit_code == 0
    assert "repo" in result.stdout


def test_config_set_ai_key_masks_output(tmp_path):
    config_dir = _setup_config(tmp_path)
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["config", "set", "ai-key", "sk-secret-key-123"])
    assert result.exit_code == 0
    assert "***" in result.stdout
    assert "sk-secret-key-123" not in result.stdout


def test_config_set_ai_model(tmp_path):
    config_dir = _setup_config(tmp_path)
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["config", "set", "ai-model", "claude-haiku-4-5-20251001"])
    assert result.exit_code == 0


def test_config_set_unknown_key(tmp_path):
    config_dir = _setup_config(tmp_path)
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["config", "set", "invalid-key", "value"])
    assert result.exit_code == 1
    assert "Unknown key" in result.stdout


# ─── import ────────────────────────────────────────────────────────────────────

def test_import_finds_sessions(tmp_path, sample_claude_session):
    config_dir = tmp_path / "sz"
    config_dir.mkdir()
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=sample_claude_session / ".claude"):
        result = runner.invoke(app, ["import"])
    assert result.exit_code == 0
    assert "1" in result.stdout


def test_import_skips_duplicates(tmp_path, sample_claude_session):
    config_dir = tmp_path / "sz"
    config_dir.mkdir()
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=sample_claude_session / ".claude"):
        runner.invoke(app, ["import"])
        result = runner.invoke(app, ["import"])
    assert result.exit_code == 0
    assert "Skipped: 1" in result.stdout


def test_import_with_tool_filter(tmp_path, sample_claude_session):
    config_dir = tmp_path / "sz"
    config_dir.mkdir()
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=sample_claude_session / ".claude"):
        result = runner.invoke(app, ["import", "--tool", "claude-code"])
    assert result.exit_code == 0
    assert "1" in result.stdout


def test_import_no_sessions_for_unknown_tool(tmp_path, sample_claude_session):
    config_dir = tmp_path / "sz"
    config_dir.mkdir()
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=sample_claude_session / ".claude"):
        result = runner.invoke(app, ["import", "--tool", "nonexistent"])
    # Unknown tool raises KeyError in get_adapter
    assert result.exit_code != 0


# ─── list ──────────────────────────────────────────────────────────────────────

def test_list_empty(tmp_path):
    config_dir = _setup_config(tmp_path)
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        with patch("session_zoo.cli._get_db") as mock_db:
            mock_db.return_value.list_sessions.return_value = []
            result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No sessions" in result.stdout


def test_list_shows_sessions(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    # Rich may truncate column values with "…"
    assert "my-proje" in result.stdout
    assert "claude-co" in result.stdout


def test_list_filter_by_project(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["list", "--project", "nonexistent"])
    assert result.exit_code == 0
    assert "No sessions" in result.stdout


def test_list_filter_by_tool(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["list", "--tool", "claude-code"])
    assert result.exit_code == 0
    assert "my-proje" in result.stdout


# ─── show ──────────────────────────────────────────────────────────────────────

def test_show_session_details(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["show", "test-session-001"])
    assert result.exit_code == 0
    assert "test-session-001" in result.stdout
    assert "claude-code" in result.stdout
    assert "my-project" in result.stdout


def test_show_not_found(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["show", "nonexistent-id"])
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_show_raw_mode(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["show", "test-session-001", "--raw"])
    assert result.exit_code == 0
    # Raw output should contain JSONL content
    assert "sessionId" in result.stdout


def test_show_markdown_mode(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["show", "test-session-001", "--markdown"])
    assert result.exit_code == 0
    # Markdown should contain session info
    assert "Session" in result.stdout


def test_show_with_summary(tmp_path, sample_claude_session):
    """Show should display summary if one exists."""
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    # Add a summary to the session
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db")
    db.init()
    db.update_summary("test-session-001", "Fixed a critical XSS bug")
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["show", "test-session-001"])
    assert result.exit_code == 0
    assert "XSS" in result.stdout
    assert "Summary" in result.stdout


def test_show_with_tags(tmp_path, sample_claude_session):
    """Show should display tags if any exist."""
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db")
    db.init()
    db.add_tags("test-session-001", ["bugfix", "security"])
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["show", "test-session-001"])
    assert result.exit_code == 0
    assert "bugfix" in result.stdout
    assert "security" in result.stdout


# ─── search ────────────────────────────────────────────────────────────────────

def test_search_finds_matching(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db")
    db.init()
    db.update_summary("test-session-001", "Fixed XSS vulnerability in login")
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["search", "XSS"])
    assert result.exit_code == 0
    assert "XSS" in result.stdout


def test_search_case_insensitive(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db")
    db.init()
    db.update_summary("test-session-001", "Fixed XSS vulnerability")
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["search", "xss"])
    assert result.exit_code == 0
    assert "XSS" in result.stdout


def test_search_no_matches(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["search", "nonexistent-query"])
    assert result.exit_code == 0
    assert "No matches" in result.stdout


# ─── tag ───────────────────────────────────────────────────────────────────────

def test_tag_add(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["tag", "test-session-001", "bugfix", "security"])
    assert result.exit_code == 0
    assert "Added" in result.stdout
    assert "bugfix" in result.stdout


def test_tag_remove(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        # Add first
        runner.invoke(app, ["tag", "test-session-001", "bugfix"])
        # Remove
        result = runner.invoke(app, ["tag", "test-session-001", "--remove", "bugfix"])
    assert result.exit_code == 0
    assert "Removed" in result.stdout


def test_tag_session_not_found(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["tag", "nonexistent", "bugfix"])
    assert result.exit_code == 1
    assert "not found" in result.stdout


# ─── tags ──────────────────────────────────────────────────────────────────────

def test_tags_empty(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["tags"])
    assert result.exit_code == 0
    assert "No tags" in result.stdout


def test_tags_list(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["tag", "test-session-001", "bugfix", "security"])
        result = runner.invoke(app, ["tags"])
    assert result.exit_code == 0
    assert "bugfix" in result.stdout
    assert "security" in result.stdout


# ─── delete ────────────────────────────────────────────────────────────────────

def test_delete_session_confirmed(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["delete", "test-session-001"], input="y\n")
    assert result.exit_code == 0
    assert "Deleted" in result.stdout


def test_delete_session_cancelled(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["delete", "test-session-001"], input="n\n")
    assert result.exit_code != 0 or "Deleted" not in result.stdout
    # Session should still exist
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db")
    db.init()
    assert db.session_exists("test-session-001")


def test_delete_not_found(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["delete", "nonexistent"])
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_delete_index_only(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["delete", "--index-only", "test-session-001"], input="y\n")
    assert result.exit_code == 0
    assert "Deleted" in result.stdout
    # Should NOT mention sync
    assert "zoo sync" not in result.stdout


# ─── summarize ─────────────────────────────────────────────────────────────────

def test_summarize_single_session_api(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["config", "set", "ai-key", "test-key"])
        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = MagicMock(
                content=[MagicMock(text="Fixed login XSS bug")]
            )
            result = runner.invoke(app, ["summarize", "--provider", "api", "test-session-001"])
    assert result.exit_code == 0
    assert "done" in result.stdout


def test_summarize_via_claude_code_cli(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Summary text", stderr="")
            result = runner.invoke(app, ["summarize", "--provider", "claude-code", "test-session-001"])
    assert result.exit_code == 0
    assert "done" in result.stdout


def test_summarize_session_not_found(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["summarize", "--provider", "api", "nonexistent"])
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_summarize_no_provider(tmp_path, sample_claude_session):
    """Auto-detect with no CLI tools and no API key should fail."""
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        with patch("shutil.which", return_value=None):
            result = runner.invoke(app, ["summarize", "test-session-001"])
    assert result.exit_code == 1
    assert "No provider" in result.stdout


def test_summarize_all_without_summary(tmp_path, sample_claude_session):
    """Summarize without session ID should process sessions lacking summaries."""
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["config", "set", "ai-key", "test-key"])
        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.return_value = MagicMock(
                content=[MagicMock(text="Summary")]
            )
            result = runner.invoke(app, ["summarize", "--provider", "api"])
    assert result.exit_code == 0
    assert "Summarized 1" in result.stdout


def test_summarize_skip_already_summarized(tmp_path, sample_claude_session):
    """Without --force, skip sessions that already have summaries."""
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db")
    db.init()
    db.update_summary("test-session-001", "Existing summary")
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["config", "set", "ai-key", "test-key"])
        with patch("anthropic.Anthropic") as mock_cls:
            result = runner.invoke(app, ["summarize", "--provider", "api"])
    assert result.exit_code == 0
    assert "Summarized 0" in result.stdout


# ─── sync ──────────────────────────────────────────────────────────────────────

def test_sync_no_repo(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["sync"])
    assert result.exit_code == 1
    assert "Repo not set" in result.stdout


def test_sync_dry_run(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["config", "set", "repo", "https://github.com/user/repo.git"])
        # Mock the sync module to avoid actual git operations
        with patch("session_zoo.sync.init_repo"), \
             patch("session_zoo.sync.pull_repo"):
            # Create a fake repo dir so it looks like it exists
            repo_dir = config_dir / "repo"
            repo_dir.mkdir()
            result = runner.invoke(app, ["sync", "--dry-run"])
    assert result.exit_code == 0
    assert "Would sync" in result.stdout


def test_sync_nothing_pending(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    # Mark session as synced
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db")
    db.init()
    db.update_sync_status("test-session-001", "synced")
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        runner.invoke(app, ["config", "set", "repo", "https://github.com/user/repo.git"])
        with patch("session_zoo.sync.pull_repo"):
            repo_dir = config_dir / "repo"
            repo_dir.mkdir()
            result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0
    assert "up to date" in result.stdout


# ─── clone ─────────────────────────────────────────────────────────────────────

def test_clone_no_repo(tmp_path):
    config_dir = _setup_config(tmp_path)
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["clone"])
    assert result.exit_code == 1
    assert "Repo not set" in result.stdout


def test_clone_already_exists(tmp_path):
    config_dir = _setup_config(tmp_path)
    (config_dir / "config.toml").write_text('repo = "https://github.com/user/repo.git"\n')
    (config_dir / "repo").mkdir()
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["clone"])
    assert result.exit_code == 0
    assert "already exists" in result.stdout


def test_clone_success(tmp_path):
    config_dir = _setup_config(tmp_path)
    (config_dir / "config.toml").write_text('repo = "https://github.com/user/repo.git"\n')
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.sync.init_repo") as mock_init:
        result = runner.invoke(app, ["clone"])
    assert result.exit_code == 0
    assert "complete" in result.stdout.lower()
    mock_init.assert_called_once()


# ─── reindex ───────────────────────────────────────────────────────────────────

def test_reindex_no_repo(tmp_path):
    config_dir = _setup_config(tmp_path)
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["reindex"])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


def test_reindex_from_repo(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    # Create a fake repo structure with raw session files
    repo_dir = config_dir / "repo"
    raw_dir = repo_dir / "raw" / "claude-code" / "my-project"
    raw_dir.mkdir(parents=True)
    # Copy the JSONL file
    source_jsonl = sample_claude_session / ".claude" / "projects" / "-home-user-my-project" / "test-session-001.jsonl"
    import shutil
    shutil.copy2(str(source_jsonl), str(raw_dir / "test-session-001.jsonl"))
    # Write meta
    meta = {
        "session_id": "test-session-001",
        "tool": "claude-code",
        "project": "my-project",
        "started_at": "2026-03-10T10:30:00+00:00",
        "ended_at": "2026-03-10T10:35:00+00:00",
        "model": "claude-opus-4-6",
        "total_tokens": 430,
        "message_count": 2,
        "summary": "Fixed login bug",
        "tags": ["bugfix"],
    }
    (raw_dir / "test-session-001.meta.json").write_text(json.dumps(meta))

    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["reindex"])
    assert result.exit_code == 0
    assert "Reindexed 1" in result.stdout

    # Verify summary and tags were restored
    from session_zoo.db import SessionDB
    db = SessionDB(config_dir / "index.db")
    db.init()
    session = db.get_session("test-session-001")
    assert session["summary"] == "Fixed login bug"
    tags = db.get_tags("test-session-001")
    assert "bugfix" in tags


# ─── restore ───────────────────────────────────────────────────────────────────

def test_restore_no_repo(tmp_path):
    config_dir = _setup_config(tmp_path)
    with patch("session_zoo.cli._config_dir", return_value=config_dir):
        result = runner.invoke(app, ["restore"])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


def test_restore_sessions(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    # Create a fake repo structure
    repo_dir = config_dir / "repo"
    raw_dir = repo_dir / "raw" / "claude-code" / "my-project"
    raw_dir.mkdir(parents=True)
    source_jsonl = sample_claude_session / ".claude" / "projects" / "-home-user-my-project" / "test-session-001.jsonl"
    import shutil
    shutil.copy2(str(source_jsonl), str(raw_dir / "test-session-001.jsonl"))
    meta = {
        "session_id": "test-session-001",
        "tool": "claude-code",
        "project": "my-project",
        "cwd": "/home/user/my-project",
    }
    (raw_dir / "test-session-001.meta.json").write_text(json.dumps(meta))

    # Use a fresh claude dir so the file doesn't already exist
    fresh_claude = tmp_path / "fresh-claude"
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=fresh_claude):
        result = runner.invoke(app, ["restore"])
    assert result.exit_code == 0
    assert "Restored 1" in result.stdout


def test_restore_skips_existing(tmp_path, sample_claude_session):
    """Restore should skip files that already exist at destination."""
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    # Create a fake repo structure
    repo_dir = config_dir / "repo"
    raw_dir = repo_dir / "raw" / "claude-code" / "my-project"
    raw_dir.mkdir(parents=True)
    source_jsonl = sample_claude_session / ".claude" / "projects" / "-home-user-my-project" / "test-session-001.jsonl"
    import shutil
    shutil.copy2(str(source_jsonl), str(raw_dir / "test-session-001.jsonl"))
    meta = {
        "session_id": "test-session-001",
        "tool": "claude-code",
        "project": "my-project",
        "cwd": "/home/user/my-project",
    }
    (raw_dir / "test-session-001.meta.json").write_text(json.dumps(meta))

    # The session file already exists in claude_dir, so restore should skip it
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=claude_dir):
        result = runner.invoke(app, ["restore"])
    assert result.exit_code == 0
    assert "Restored 0" in result.stdout


def test_restore_filter_by_project(tmp_path, sample_claude_session):
    config_dir, claude_dir = _setup_db_with_session(tmp_path, sample_claude_session)
    repo_dir = config_dir / "repo"
    raw_dir = repo_dir / "raw" / "claude-code" / "my-project"
    raw_dir.mkdir(parents=True)
    source_jsonl = sample_claude_session / ".claude" / "projects" / "-home-user-my-project" / "test-session-001.jsonl"
    import shutil
    shutil.copy2(str(source_jsonl), str(raw_dir / "test-session-001.jsonl"))
    (raw_dir / "test-session-001.meta.json").write_text(json.dumps({
        "session_id": "test-session-001", "tool": "claude-code",
        "project": "my-project", "cwd": "/home/user/my-project",
    }))

    fresh_claude = tmp_path / "fresh-claude"
    with patch("session_zoo.cli._config_dir", return_value=config_dir), \
         patch("session_zoo.cli._claude_dir", return_value=fresh_claude):
        # Filter by nonexistent project
        result = runner.invoke(app, ["restore", "--project", "other-project"])
    assert result.exit_code == 0
    assert "Restored 0" in result.stdout


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
