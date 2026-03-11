import shutil
import subprocess

from session_zoom.models import Session

MAX_PROMPT_CHARS = 80_000

SYSTEM_PROMPT = """You are summarizing an AI-assisted development session.
Generate a concise summary with these sections:
1. A one-line title (what was accomplished)
2. A brief summary paragraph (2-3 sentences)
3. Key decisions made during the session
4. Keep it factual and concise. Write in the same language as the conversation."""


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


def detect_provider() -> str | None:
    """Auto-detect available summarization provider.
    Priority: claude-code > codex > None
    """
    if shutil.which("claude"):
        return "claude-code"
    if shutil.which("codex"):
        return "codex"
    return None


def generate_summary(session: Session, *,
                     provider: str = "auto",
                     api_key: str | None = None,
                     model: str | None = None) -> str:
    """Generate a summary using the specified provider.

    provider: "auto" | "claude-code" | "codex" | "api"
      - auto: detect available CLI tool, fall back to API
      - claude-code: use `claude -p` CLI
      - codex: use `codex -q` CLI
      - api: use Anthropic API directly (requires api_key)
    """
    if provider == "auto":
        if api_key:
            provider = "api"
        else:
            detected = detect_provider()
            if detected is None:
                raise RuntimeError(
                    "No summarization provider available. "
                    "Install claude-code or codex, or set an API key with: "
                    "zoom config set ai-key <key>"
                )
            provider = detected

    prompt = build_prompt(session)
    full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"

    if provider == "claude-code":
        return _summarize_via_claude(full_prompt, model)
    elif provider == "codex":
        return _summarize_via_codex(full_prompt)
    elif provider == "api":
        if not api_key:
            raise RuntimeError("API key required for 'api' provider. Run: zoom config set ai-key <key>")
        return _summarize_via_api(prompt, api_key, model)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _summarize_via_claude(prompt: str, model: str | None = None) -> str:
    """Use `claude -p` (non-interactive print mode) to generate summary."""
    cmd = ["claude", "-p", "--no-session-persistence"]
    if model:
        cmd.extend(["--model", model])
    # Remove CLAUDECODE env var to allow running inside a Claude Code session
    import os
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _summarize_via_codex(prompt: str) -> str:
    """Use `codex -q` (quiet/non-interactive mode) to generate summary."""
    result = subprocess.run(
        ["codex", "-q", prompt],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"codex CLI failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _summarize_via_api(prompt: str, api_key: str, model: str | None = None) -> str:
    """Use Anthropic API directly."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model or "claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
