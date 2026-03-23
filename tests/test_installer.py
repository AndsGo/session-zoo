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


def _has_zoo_hook(hooks_list):
    """检查 hooks 列表中是否包含 zoo import hook。"""
    for entry in hooks_list:
        for hook in entry.get("hooks", []):
            if "zoo import" in hook.get("command", ""):
                return True
    return False


def _count_zoo_hooks(hooks_list):
    """统计 hooks 列表中 zoo import hook 的数量。"""
    count = 0
    for entry in hooks_list:
        for hook in entry.get("hooks", []):
            if "zoo import" in hook.get("command", ""):
                count += 1
    return count


def test_install_hook_creates_settings(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    install_hook(claude_dir)
    settings = json.loads((claude_dir / "settings.json").read_text())
    hooks = settings["hooks"]["SessionStart"]
    assert _has_zoo_hook(hooks)


def test_install_hook_merges_existing(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    existing = {
        "hooks": {
            "SessionStart": [
                {"matcher": "", "hooks": [{"type": "command", "command": "echo hello"}]},
            ],
            "PreToolUse": [
                {"matcher": "", "hooks": [{"type": "command", "command": "echo pre"}]},
            ],
        },
        "other_key": "preserved",
    }
    (claude_dir / "settings.json").write_text(json.dumps(existing))
    install_hook(claude_dir)
    settings = json.loads((claude_dir / "settings.json").read_text())
    hooks = settings["hooks"]["SessionStart"]
    # Both original and zoo hook present
    assert len(hooks) == 2
    assert _has_zoo_hook(hooks)
    # Other hooks preserved
    assert len(settings["hooks"]["PreToolUse"]) == 1
    # Other keys preserved
    assert settings["other_key"] == "preserved"


def test_install_hook_no_duplicate(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    install_hook(claude_dir)
    install_hook(claude_dir)  # second call
    settings = json.loads((claude_dir / "settings.json").read_text())
    hooks = settings["hooks"]["SessionStart"]
    assert _count_zoo_hooks(hooks) == 1  # no duplicate
