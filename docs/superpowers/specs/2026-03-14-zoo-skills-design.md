# session-zoo Skills Design Spec

## Goal

Provide 5 CLI skills + 1 session-start hook for AI coding tools (Claude Code, Codex), so that session-zoo integrates seamlessly into daily AI development workflows. Skills are auto-installed via `zoo init`.

## Architecture

```
zoo init
  ├── Copy 5 SKILL.md files → ~/.claude/skills/zoo-{sync,browse,summarize,tag,restore}/
  ├── Merge hook config → ~/.claude/settings.json (SessionStart: zoo import --quiet)
  └── Existing init logic (config.toml, index.db)
```

Skills are bundled inside the Python package at `src/session_zoo/data/skills/` and `src/session_zoo/data/hooks/`. `zoo init` copies them to the target tool's skill/hook directory.

## Components

### Hook: zoo-auto-import

Not a skill file. A SessionStart hook injected into `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{
      "command": "zoo import --quiet 2>/dev/null || true"
    }]
  }
}
```

Requires adding `--quiet` flag to `zoo import`:
- With `--quiet`: only print output when new sessions are imported or updated
- Without: current behavior (always print counts)
- `|| true` in hook ensures failures don't block conversation startup

### Skill 1: zoo-sync

- **Trigger**: "sync sessions", "push sessions", "backup sessions", "同步 session", "备份开发记录"
- **Flow**: Run `zoo import` then `zoo sync`
- **Error handling**: Guide user through `zoo init` and `zoo config set repo` if not configured

### Skill 2: zoo-browse

- **Trigger**: "list sessions", "show session", "查看开发记录", "最近做了什么", "what did I work on"
- **Flow**: Run `zoo list`, let user pick a session, then `zoo show <id>` or `zoo show <id> --markdown`
- **Supports**: Filter flags `--project`, `--tool`, `--tag`, `--since`

### Skill 3: zoo-summarize

- **Trigger**: "summarize session", "generate summary", "总结 session", "生成摘要"
- **Flow**: Check unsummarized sessions with `zoo list --no-summary`, then `zoo summarize [id]`
- **Supports**: `--force` for regeneration, `--provider` selection

### Skill 4: zoo-tag

- **Trigger**: "tag session", "add tags", "打标签", "归类 session", "search sessions"
- **Flow**: `zoo list` → `zoo tag <id> <tags>` → `zoo tags` to confirm
- **Also covers**: `zoo tag <id> --remove <tag>`, `zoo search <query>`

### Skill 5: zoo-restore

- **Trigger**: "restore sessions", "migrate sessions", "恢复 session", "迁移设备", "new machine setup"
- **Flow**: `zoo clone` → `zoo reindex` → `zoo restore`
- **Guard**: Check if repo is configured, guide user if not

## zoo init Changes

Current `zoo init` logic:
1. Create `~/.session-zoo/` directory
2. Create `config.toml`
3. Create `index.db`

New steps added:
4. Copy skill files from package data to `~/.claude/skills/zoo-*/SKILL.md`
   - Skip if skill already exists (don't overwrite user customizations)
   - Print count of installed/skipped skills
5. Merge SessionStart hook into `~/.claude/settings.json`
   - Read existing settings, merge `hooks.SessionStart` array (avoid duplicates)
   - Create settings.json if it doesn't exist
   - Don't remove existing hooks

### Package Data Layout

```
src/session_zoo/
  data/
    skills/
      zoo-sync/SKILL.md
      zoo-browse/SKILL.md
      zoo-summarize/SKILL.md
      zoo-tag/SKILL.md
      zoo-restore/SKILL.md
    hooks/
      settings-snippet.json    # SessionStart hook template
```

## Skill File Constraints

- Each SKILL.md: **< 200 words** (token efficiency)
- Description: starts with "Use when...", no workflow summary
- Bilingual trigger words (English + Chinese)
- All skills assume `zoo` CLI is installed and on PATH

## CLI Changes

### `zoo import --quiet`

New `--quiet` / `-q` flag:
- Suppresses output when nothing is imported or updated
- Only prints when `total_imported > 0` or `total_updated > 0`
- Used by the SessionStart hook to avoid noise

### `zoo init` (extended)

Add skill + hook installation after existing init logic. New flags:
- `--skip-skills`: Skip skill installation
- `--skip-hooks`: Skip hook installation

## Testing

- Unit tests: verify `zoo init` copies skills and merges hooks correctly
- E2E test: full flow with hook → import → skill-triggered sync
- Verify hook merging doesn't corrupt existing settings.json
- Verify `--quiet` flag produces no output on no-op import
