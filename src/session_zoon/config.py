from dataclasses import dataclass, field
from pathlib import Path
import tomllib


@dataclass
class Config:
    repo: str | None = None
    ai_key: str | None = None
    ai_model: str = "claude-haiku-4-5-20251001"
    config_dir: Path = field(default_factory=lambda: Path.home() / ".session-zoon")

    @property
    def db_path(self) -> Path:
        return self.config_dir / "index.db"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def repo_dir(self) -> Path:
        return self.config_dir / "repo"


def load_config(path: Path | None = None) -> Config:
    if path is None:
        path = Config().config_file
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Config(
        repo=data.get("repo"),
        ai_key=data.get("ai_key"),
        ai_model=data.get("ai_model", "claude-haiku-4-5-20251001"),
    )


def save_config(cfg: Config, path: Path | None = None) -> None:
    if path is None:
        path = cfg.config_file
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if cfg.repo:
        lines.append(f'repo = "{cfg.repo}"')
    if cfg.ai_key:
        lines.append(f'ai_key = "{cfg.ai_key}"')
    lines.append(f'ai_model = "{cfg.ai_model}"')
    path.write_text("\n".join(lines) + "\n")
