import json
import shutil
import subprocess
from pathlib import Path


def init_repo(repo_dir: Path, remote_url: str) -> None:
    if repo_dir.exists():
        return
    subprocess.run(
        ["git", "clone", remote_url, str(repo_dir)],
        check=True, capture_output=True, text=True,
    )


def pull_repo(repo_dir: Path) -> None:
    # 空仓库（无 commit）时 pull 会失败，跳过即可
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_dir), capture_output=True, text=True,
    )
    if result.returncode != 0:
        return  # 空仓库，无需 pull
    subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=str(repo_dir), check=True, capture_output=True, text=True,
    )


def copy_raw_session(*, repo_dir: Path, source_path: Path,
                     tool: str, project: str, session_id: str) -> Path:
    dest_dir = repo_dir / "raw" / tool / project
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{session_id}.jsonl"
    shutil.copy2(str(source_path), str(dest))
    return dest


def write_meta_json(*, repo_dir: Path, tool: str, project: str,
                    session_id: str, meta: dict) -> Path:
    dest_dir = repo_dir / "raw" / tool / project
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{session_id}.meta.json"
    dest.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest


def write_session_markdown(*, repo_dir: Path, project: str, date: str,
                           tool: str, session_id: str, content: str) -> Path:
    dest_dir = repo_dir / "sessions" / project / date / tool
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{session_id}.md"
    dest.write_text(content, encoding="utf-8")
    return dest


def commit_and_push(repo_dir: Path, message: str) -> bool:
    subprocess.run(["git", "add", "-A"], cwd=str(repo_dir),
                   check=True, capture_output=True)
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_dir), capture_output=True, text=True,
    )
    if not result.stdout.strip():
        return False  # Nothing to commit
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(repo_dir), check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "push"],
        cwd=str(repo_dir), check=True, capture_output=True, text=True,
    )
    return True


def list_raw_sessions(repo_dir: Path) -> list[dict]:
    raw_dir = repo_dir / "raw"
    if not raw_dir.exists():
        return []

    sessions = []
    for jsonl_file in raw_dir.rglob("*.jsonl"):
        parts = jsonl_file.relative_to(raw_dir).parts
        if len(parts) < 3:
            continue
        tool, project = parts[0], parts[1]
        session_id = jsonl_file.stem
        meta_path = jsonl_file.with_suffix(".meta.json")
        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

        sessions.append({
            "session_id": session_id,
            "tool": tool,
            "project": project,
            "jsonl_path": jsonl_file,
            "meta": meta,
        })
    return sorted(sessions, key=lambda s: s["session_id"])
