# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-03-12

### Added

- CLI tool `zoo` with 14 commands: init, config, import, list, show, search, tag, tags, delete, summarize, sync, clone, reindex, restore
- Claude Code adapter: discover, parse, and restore sessions from `~/.claude/`
- Multi-provider AI summarization: Claude Code CLI, Codex CLI, Anthropic API
- Git-based sync: push raw JSONL + metadata + Markdown summaries to GitHub
- Cross-device restore: clone repo → reindex → restore sessions to `~/.claude/`
- SQLite local index with search, filter by project/tool/tag/date
- Markdown renderer with noise filtering, tool call merging, relative paths
- Tag management for organizing sessions
