---
name: zoo-tag
description: Use when the user wants to tag, categorize, or search AI development sessions. Triggers on "tag session", "add tags", "打标签", "归类 session", "search sessions".
---

# Tag & Search Sessions

## Add Tags

```bash
zoo tag <id> bugfix security
```

## Remove a Tag

```bash
zoo tag <id> --remove security
```

## List All Tags

```bash
zoo tags
```

## Filter Sessions by Tag

```bash
zoo list --tag bugfix
```

## Search by Summary Content

```bash
zoo search "login bug"
```
