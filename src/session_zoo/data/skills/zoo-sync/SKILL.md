---
name: zoo-sync
description: Use when the user wants to sync, backup, or push AI development sessions to GitHub. Triggers on "sync sessions", "backup sessions", "push sessions", "同步 session", "备份开发记录".
---

# Sync Sessions to GitHub

## Steps

1. Import latest sessions:
   ```bash
   zoo import
   ```

2. Sync to GitHub:
   ```bash
   zoo sync
   ```

## If Not Configured

If `zoo sync` fails with "Repo not set":
```bash
zoo init
zoo config set repo git@github.com:USER/REPO.git
```

## Dry Run

Preview without pushing:
```bash
zoo sync --dry-run
```
