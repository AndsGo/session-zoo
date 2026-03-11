from session_zoon.models import Session


def render_session_markdown(session: Session, *,
                            summary: str | None = None,
                            tags: list[str] | None = None) -> str:
    lines: list[str] = []

    # Title
    title = summary.split("\n")[0] if summary else f"Session {session.id[:8]}"
    lines.append(f"# {title}")
    lines.append("")

    # Metadata table
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

    # Summary
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # Files touched (from tool calls)
    files = _extract_files(session)
    if files:
        lines.append("## Files")
        lines.append("")
        for f in files:
            lines.append(f"- {f}")
        lines.append("")

    # Conversation
    lines.append("## Conversation")
    lines.append("")
    for msg in session.messages:
        role = "User" if msg.role == "user" else "Assistant"
        content = msg.content.strip()
        if len(content) > 500:
            content = content[:500] + "..."
        lines.append(f"> **{role}:** {content}")
        lines.append(">")
    lines.append("")

    return "\n".join(lines)


def _extract_files(session: Session) -> list[str]:
    files = set()
    for msg in session.messages:
        for tc in msg.tool_calls:
            inp = tc.get("input", {})
            for key in ("file_path", "path", "filePath"):
                if key in inp:
                    files.add(inp[key])
    return sorted(files)
