---
name: zoo-browse
description: Use when the user wants to view, list, or browse AI development sessions or asks "what did I work on". Triggers on "list sessions", "show session", "查看开发记录", "最近做了什么", "what did I work on".
---

# Browse Development Sessions

## List Sessions

```bash
zoo list
zoo list --project myapp
zoo list --tag bugfix
zoo list --since 2026-03-01
```

## View Session Details

Use the ID prefix from `zoo list`:
```bash
zoo show <id>
zoo show <id> --markdown    # Full rendered conversation
zoo show <id> --raw         # Raw JSONL
```

## Search by Summary

```bash
zoo search "authentication"
```
