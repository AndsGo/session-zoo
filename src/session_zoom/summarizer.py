import anthropic

from session_zoom.models import Session

MAX_PROMPT_CHARS = 80_000


def build_prompt(session: Session) -> str:
    lines = [
        f"Project: {session.project}",
        f"Tool: {session.tool}",
        f"Model: {session.model}",
        f"Branch: {session.git_branch or 'N/A'}",
        f"Duration: {session.duration_minutes or '?'} minutes",
        "",
        "Conversation:",
    ]

    char_count = sum(len(l) for l in lines)
    for msg in session.messages:
        role = "User" if msg.role == "user" else "Assistant"
        content = msg.content.strip()
        entry = f"\n[{role}]: {content}"

        if msg.tool_calls:
            tools = ", ".join(tc.get("name", "?") for tc in msg.tool_calls)
            files = ", ".join(
                tc.get("input", {}).get("file_path", "")
                for tc in msg.tool_calls
                if tc.get("input", {}).get("file_path")
            )
            entry += f"\n  Tools: {tools}"
            if files:
                entry += f"\n  Files: {files}"

        if char_count + len(entry) > MAX_PROMPT_CHARS:
            lines.append("\n... (truncated)")
            break
        lines.append(entry)
        char_count += len(entry)

    return "\n".join(lines)


SYSTEM_PROMPT = """You are summarizing an AI-assisted development session.
Generate a concise summary with these sections:
1. A one-line title (what was accomplished)
2. A brief summary paragraph (2-3 sentences)
3. Key decisions made during the session
4. Keep it factual and concise. Write in the same language as the conversation."""


def generate_summary(session: Session, *,
                     api_key: str,
                     model: str = "claude-haiku-4-5-20251001") -> str:
    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_prompt(session)

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
