import re

from session_zoo.models import Session

# XML-like system tags to strip from content
_SYSTEM_TAG_RE = re.compile(r"</?(?:local-command-caveat|local-command-stdout|command-name|command-message|command-args|system-reminder|antml:[a-z_]+)[^>]*>")

# Messages matching these patterns are system noise, skip entirely
_SKIP_PATTERNS = [
    re.compile(r"^\s*<local-command-caveat>"),
    re.compile(r"^\s*<local-command-stdout>\(no content\)</local-command-stdout>\s*$"),
    re.compile(r"^\s*<command-name>/(?:plugin|exit|reload-plugins|config|help|clear|heapdump)\b"),
    re.compile(r"^\s*\[Request interrupted by user\]\s*$"),
    # System prompt / skill content leaked into user messages
    re.compile(r"^\s*Base directory for this skill:"),
    re.compile(r"^\s*<SUBAGENT-STOP>"),
    re.compile(r"^\s*<EXTREMELY-IMPORTANT>"),
    re.compile(r"^\s*<HARD-GATE>"),
]

# Line-level patterns to strip from mixed messages (prefix noise + real content)
_STRIP_LINE_PATTERNS = [
    re.compile(r"^/?superpowers:\S+"),
    re.compile(r"^/?/superpowers:\S+"),
]

# File path prefixes that are tool/system noise, not project source code
_NOISE_PATH_PREFIXES = (
    ".claude/plugins/",
    ".claude/projects/",
    ".superpowers/",
    "memory/MEMORY.md",
)


def _clean_content(text: str) -> str:
    """Strip system XML tags, noise line prefixes, and clean up whitespace."""
    text = _SYSTEM_TAG_RE.sub("", text)
    # Strip line-level noise patterns (e.g. superpowers: prefixes)
    cleaned_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        skip = False
        for pat in _STRIP_LINE_PATTERNS:
            if pat.match(stripped):
                skip = True
                break
        if not skip:
            cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    # Collapse multiple blank lines into one
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _should_skip(content: str) -> bool:
    """Return True if this message is system noise."""
    for pat in _SKIP_PATTERNS:
        if pat.search(content):
            return True
    return False


def _make_relative(file_path: str, cwd: str | None) -> str:
    """Convert absolute path to relative path based on project cwd."""
    if not cwd or not file_path.startswith("/"):
        return file_path
    cwd_prefix = cwd.rstrip("/") + "/"
    if file_path.startswith(cwd_prefix):
        return file_path[len(cwd_prefix):]
    return file_path


def _is_noise_file(rel_path: str) -> bool:
    """Return True if path is tool/system noise, not project source."""
    for prefix in _NOISE_PATH_PREFIXES:
        if rel_path.startswith(prefix) or ("/" + prefix) in rel_path:
            return True
    # Also filter home-dir dotfiles not under project
    if rel_path.startswith("/home/") and "/.claude/" in rel_path:
        return True
    if rel_path.startswith("/home/") and "/.superpowers/" in rel_path:
        return True
    return False


def _is_tool_only(content: str, tool_calls: list[dict]) -> bool:
    """Return True if the message is just tool calls with no meaningful text."""
    return not content and bool(tool_calls)


def render_session_markdown(session: Session, *,
                            summary: str | None = None,
                            tags: list[str] | None = None) -> str:
    lines: list[str] = []

    # --- Title ---
    if summary:
        title = summary.split("\n")[0].lstrip("# ").strip()
    elif session.started_at:
        date_str = session.started_at.strftime("%Y-%m-%d")
        title = f"{session.project} — {date_str}"
    else:
        title = f"{session.project} — Session {session.id[:8]}"
    lines.append(f"# {title}")
    lines.append("")

    # --- Metadata table ---
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Session ID | {session.id} |")
    lines.append(f"| Tool | {session.tool} |")
    lines.append(f"| Model | {session.model} |")
    lines.append(f"| Project | {session.project} |")
    if session.git_branch:
        lines.append(f"| Branch | {session.git_branch} |")

    # Time
    if session.started_at and session.ended_at:
        start = session.started_at.strftime("%Y-%m-%d %H:%M")
        end = session.ended_at.strftime("%H:%M")
        duration = session.duration_minutes
        dur_str = f"{duration}m" if duration and duration < 60 else f"{duration // 60}h{duration % 60}m" if duration else ""
        lines.append(f"| Time | {start} → {end} ({dur_str}) |")
    elif session.started_at:
        lines.append(f"| Time | {session.started_at.strftime('%Y-%m-%d %H:%M')} |")

    lines.append(f"| Tokens | {session.total_tokens:,} |")
    lines.append(f"| Messages | {session.message_count} |")

    if tags:
        tag_str = " ".join(f"`{t}`" for t in tags)
        lines.append(f"| Tags | {tag_str} |")

    lines.append("")

    # --- Summary ---
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # --- Files Changed ---
    files = _extract_files(session)
    if files:
        file_lines = []
        for f in files:
            rel = _make_relative(f, session.cwd)
            if _is_noise_file(rel):
                continue
            # Skip paths that are the cwd itself (directory, not a file)
            if session.cwd and f.rstrip("/") == session.cwd.rstrip("/"):
                continue
            file_lines.append(f"- `{rel}`")
        if file_lines:
            lines.append("## Files Changed")
            lines.append("")
            lines.extend(file_lines)
            lines.append("")

    # --- Conversation ---
    conversation = _build_conversation(session)
    if conversation:
        lines.append("## Conversation")
        lines.append("")
        for entry in conversation:
            lines.append(f"> **{entry['role']}:** {entry['content']}")
            lines.append(">")
        lines.append("")

    return "\n".join(lines)


def _build_conversation(session: Session) -> list[dict]:
    """Build cleaned conversation entries, merging consecutive tool-only messages."""
    entries: list[dict] = []
    pending_tools: list[str] = []  # accumulate consecutive tool-only names

    for msg in session.messages:
        raw_content = msg.content.strip()

        # Skip system noise messages
        if _should_skip(raw_content):
            continue

        role = "User" if msg.role == "user" else "Assistant"
        content = _clean_content(raw_content)

        # Tool-only assistant message: accumulate
        if role == "Assistant" and _is_tool_only(content, msg.tool_calls):
            for tc in msg.tool_calls:
                pending_tools.append(tc.get("name", "?"))
            continue

        # Flush pending tools before a non-tool message
        if pending_tools:
            entries.append({
                "role": "Assistant",
                "content": _format_tool_group(pending_tools),
            })
            pending_tools = []

        # Skip completely empty messages
        if not content:
            continue

        if len(content) > 500:
            content = content[:500] + "..."
        entries.append({"role": role, "content": content})

    # Flush trailing tools
    if pending_tools:
        entries.append({
            "role": "Assistant",
            "content": _format_tool_group(pending_tools),
        })

    return entries


def _format_tool_group(tools: list[str]) -> str:
    """Format a group of tool calls into a compact summary.
    e.g. ['Bash', 'Bash', 'Read', 'Edit'] → '*[Used: Bash ×2, Read, Edit]*'
    """
    counts: dict[str, int] = {}
    for t in tools:
        counts[t] = counts.get(t, 0) + 1
    parts = []
    for name, count in counts.items():
        if count > 1:
            parts.append(f"{name} ×{count}")
        else:
            parts.append(name)
    return f"*[Used: {', '.join(parts)}]*"


def _extract_files(session: Session) -> list[str]:
    files = set()
    for msg in session.messages:
        for tc in msg.tool_calls:
            inp = tc.get("input", {})
            for key in ("file_path", "path", "filePath"):
                if key in inp and inp[key]:
                    files.add(inp[key])
    return sorted(files)
