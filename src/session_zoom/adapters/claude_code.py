import json
from datetime import datetime, timezone
from pathlib import Path

from session_zoom.models import Message, Session


class ClaudeCodeAdapter:
    name = "claude-code"

    def __init__(self, claude_dir: Path | None = None):
        self.claude_dir = claude_dir or Path.home() / ".claude"

    def discover(self, *, since: datetime | None = None,
                 project: str | None = None) -> list[Path]:
        projects_dir = self.claude_dir / "projects"
        if not projects_dir.exists():
            return []

        paths = []
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            if project and not self._match_project(project_dir.name, project):
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                if since and self._get_file_start_time(jsonl_file):
                    start = self._get_file_start_time(jsonl_file)
                    if start and start < since:
                        continue
                paths.append(jsonl_file)
        return sorted(paths)

    def parse(self, path: Path) -> Session:
        lines = path.read_text().strip().split("\n")
        records = [json.loads(line) for line in lines if line.strip()]

        session_id = None
        model = None
        git_branch = None
        cwd = None
        messages: list[Message] = []
        total_input = 0
        total_output = 0
        timestamps: list[datetime] = []

        for record in records:
            rec_type = record.get("type")
            ts_str = record.get("timestamp")
            if ts_str:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                timestamps.append(ts)

            if session_id is None:
                session_id = record.get("sessionId")
            if git_branch is None:
                git_branch = record.get("gitBranch")
            if cwd is None:
                cwd = record.get("cwd")

            if rec_type not in ("user", "assistant"):
                continue

            msg_data = record.get("message", {})
            role = msg_data.get("role", rec_type)
            content_raw = msg_data.get("content", "")

            # Extract text content
            if isinstance(content_raw, list):
                text_parts = [
                    c.get("text", "") for c in content_raw
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                content = "\n".join(text_parts)
            else:
                content = str(content_raw)

            # Extract tool calls
            tool_calls = []
            if isinstance(content_raw, list):
                for c in content_raw:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        tool_calls.append({
                            "id": c.get("id"),
                            "name": c.get("name"),
                            "input": c.get("input", {}),
                        })

            # Extract token usage
            usage = msg_data.get("usage")
            token_usage = None
            if usage:
                inp = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                out = usage.get("output_tokens", 0)
                total_input += inp
                total_output += out
                token_usage = {"input": inp, "output": out}

            # Extract model
            if model is None and msg_data.get("model"):
                model = msg_data["model"]

            messages.append(Message(
                role=role,
                content=content,
                timestamp=ts if ts_str else datetime.now(timezone.utc),
                tool_calls=tool_calls,
                token_usage=token_usage,
            ))

        # Derive project name from directory
        project_name = self._extract_project_name(path)

        return Session(
            id=session_id or path.stem,
            tool="claude-code",
            project=project_name,
            source_path=path,
            started_at=min(timestamps) if timestamps else None,
            ended_at=max(timestamps) if timestamps else None,
            model=model or "unknown",
            total_tokens=total_input + total_output,
            messages=messages,
            git_branch=git_branch if git_branch != "HEAD" else None,
            cwd=cwd,
        )

    def get_restore_path(self, session: Session) -> Path:
        encoded = self._encode_project_path(session.cwd or f"/unknown/{session.project}")
        return self.claude_dir / "projects" / encoded / f"{session.id}.jsonl"

    def _extract_project_name(self, path: Path) -> str:
        """Extract project name from the session's cwd field if available,
        otherwise fall back to the last segment of the encoded directory name."""
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    cwd = record.get("cwd")
                    if cwd:
                        return Path(cwd).name
        except (json.JSONDecodeError, OSError):
            pass
        # Fallback: encoded dir name last segment is ambiguous with hyphens,
        # but best effort — take everything after the last "-" grouping.
        dir_name = path.parent.name  # e.g., "-home-user-my-project"
        # Strip leading "-", split on "-", take last token
        parts = dir_name.lstrip("-").split("-")
        return parts[-1] if parts else dir_name

    def _encode_project_path(self, cwd: str) -> str:
        # Claude Code encodes "/home/user/project" as "-home-user-project"
        return "-" + cwd.strip("/").replace("/", "-")

    def _match_project(self, dir_name: str, project: str) -> bool:
        return project.lower() in dir_name.lower()

    def _get_file_start_time(self, path: Path) -> datetime | None:
        try:
            with open(path) as f:
                first_line = f.readline()
            record = json.loads(first_line)
            ts_str = record.get("timestamp")
            if ts_str:
                return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (json.JSONDecodeError, OSError):
            pass
        return None
