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
