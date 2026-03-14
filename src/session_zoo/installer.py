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
