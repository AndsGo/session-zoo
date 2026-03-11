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
