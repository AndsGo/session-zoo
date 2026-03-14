---
name: zoo-summarize
description: Use when the user wants to generate AI summaries for development sessions. Triggers on "summarize session", "generate summary", "总结 session", "生成摘要".
---

# Summarize Sessions

## Summarize One

```bash
zoo summarize <id>
```

## Summarize All Unsummarized

```bash
zoo summarize
```

## Force Regenerate

```bash
zoo summarize <id> --force
```

## Provider Selection

Auto-detects: installed claude CLI > codex CLI > API key.
```bash
zoo summarize --provider claude-code <id>
zoo summarize --provider api <id>       # Needs: zoo config set ai-key <key>
```

## Check What Needs Summary

```bash
zoo list --no-summary
```
