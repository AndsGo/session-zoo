"""End-to-end test: import → list → tag → show → summarize (mocked) → sync (local)"""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from session_zoom.cli import app

runner = CliRunner()


def test_full_workflow(sample_claude_session, tmp_path):
    config_dir = tmp_path / "sz-config"
    claude_dir = sample_claude_session / ".claude"

    # Set up a local bare git repo as "remote"
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True, check=True)

    with patch("session_zoom.cli._config_dir", return_value=config_dir), \
         patch("session_zoom.cli._claude_dir", return_value=claude_dir):

        # 1. Init
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0, f"init failed: {result.stdout}"

        # 2. Config: set repo
        result = runner.invoke(app, ["config", "set", "repo", str(remote)])
        assert result.exit_code == 0, f"config set repo failed: {result.stdout}"

        # 3. Import
        result = runner.invoke(app, ["import"])
        assert result.exit_code == 0, f"import failed: {result.stdout}"
        assert "1" in result.stdout

        # 4. List
        result = runner.invoke(app, ["list"])
        assert result.exit_code == 0, f"list failed: {result.stdout}"
        # Rich may truncate column values with "…"; check for the common prefix
        assert "my-proje" in result.stdout

        # 5. Tag
        result = runner.invoke(app, ["tag", "test-session-001", "bugfix", "test"])
        assert result.exit_code == 0, f"tag failed: {result.stdout}"

        # 6. Show
        result = runner.invoke(app, ["show", "test-session-001"])
        assert result.exit_code == 0, f"show failed: {result.stdout}"
        assert "claude-code" in result.stdout

        # 7. Summarize (mocked AI)
        result = runner.invoke(app, ["config", "set", "ai-key", "test-key"])
        assert result.exit_code == 0, f"config set ai-key failed: {result.stdout}"

        with patch("session_zoom.summarizer.anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.Anthropic.return_value = mock_client
            mock_client.messages.create.return_value = MagicMock(
                content=[MagicMock(text="Fixed login bug with XSS sanitization")]
            )
            result = runner.invoke(app, ["summarize", "test-session-001"])
            assert result.exit_code == 0, f"summarize failed: {result.stdout}"
            assert "done" in result.stdout

        # 8. Sync (to local bare repo)
        # First, seed the remote with an initial commit so we can push to it
        staging = tmp_path / "staging"
        subprocess.run(["git", "clone", str(remote), str(staging)], capture_output=True, check=True)
        (staging / ".gitkeep").touch()
        subprocess.run(["git", "-C", str(staging), "add", "."], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(staging), "-c", "user.email=test@test.com",
             "-c", "user.name=Test", "commit", "-m", "init"],
            capture_output=True, check=True,
        )
        subprocess.run(["git", "-C", str(staging), "push"], capture_output=True, check=True)

        # Configure git identity in the repo that sync will clone/use
        # (sync clones into config_dir/repo, so we set global fallback via env)
        import os
        env = os.environ.copy()
        env.setdefault("GIT_AUTHOR_NAME", "Test")
        env.setdefault("GIT_AUTHOR_EMAIL", "test@test.com")
        env.setdefault("GIT_COMMITTER_NAME", "Test")
        env.setdefault("GIT_COMMITTER_EMAIL", "test@test.com")

        with patch.dict("os.environ", {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        }):
            result = runner.invoke(app, ["sync"])
        assert result.exit_code == 0, f"sync failed: {result.stdout}\n{result.exception}"

        # 9. Verify repo contents
        repo_dir = config_dir / "repo"
        raw_jsonl = repo_dir / "raw" / "claude-code" / "my-project" / "test-session-001.jsonl"
        raw_meta = repo_dir / "raw" / "claude-code" / "my-project" / "test-session-001.meta.json"

        assert raw_jsonl.exists(), f"JSONL file not found at {raw_jsonl}"
        assert raw_meta.exists(), f"Meta JSON not found at {raw_meta}"

        meta = json.loads(raw_meta.read_text())
        assert meta["tags"] == ["bugfix", "test"]
        assert "XSS" in meta["summary"]
