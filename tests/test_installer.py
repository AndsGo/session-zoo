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
