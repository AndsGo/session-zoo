from pathlib import Path
from session_zoo.config import Config, load_config, save_config


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
    assert cfg.config_dir == Path.home() / ".session-zoo"
    assert cfg.db_path == Path.home() / ".session-zoo" / "index.db"
    assert cfg.config_file == Path.home() / ".session-zoo" / "config.toml"
