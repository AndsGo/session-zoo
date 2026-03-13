from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Message:
    role: str
    content: str
    timestamp: datetime
    tool_calls: list[dict] = field(default_factory=list)
    token_usage: dict | None = None


@dataclass
class Session:
    id: str
    tool: str
    project: str
    source_path: Path
    started_at: datetime
    ended_at: datetime | None
    model: str
    total_tokens: int
    messages: list[Message] = field(default_factory=list)
    git_branch: str | None = None
    cwd: str | None = None

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def duration_minutes(self) -> int | None:
        if self.ended_at is None or self.started_at is None:
            return None
        delta = self.ended_at - self.started_at
        return int(delta.total_seconds() / 60)
