from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from session_zoo.config import Config, load_config, save_config
from session_zoo.db import SessionDB
from session_zoo.adapters import get_adapter, list_adapters
from session_zoo.renderer import render_session_markdown

app = typer.Typer(name="zoo", help="AI development session recorder")
config_app = typer.Typer(help="Manage configuration")
app.add_typer(config_app, name="config")
console = Console()


def _config_dir() -> Path:
    return Path.home() / ".session-zoo"


def _claude_dir() -> Path:
    return Path.home() / ".claude"


def _get_config() -> Config:
    cfg = load_config(_config_dir() / "config.toml")
    cfg.config_dir = _config_dir()
    return cfg


def _get_db() -> SessionDB:
    cfg = _get_config()
    db = SessionDB(cfg.db_path)
    db.init()
    return db


@app.command()
def init(
    skip_skills: bool = typer.Option(False, help="Skip skill installation"),
    skip_hooks: bool = typer.Option(False, help="Skip hook installation"),
):
    """Initialize session-zoo configuration."""
    d = _config_dir()
    d.mkdir(parents=True, exist_ok=True)
    config_path = d / "config.toml"
    if not config_path.exists():
        save_config(Config(config_dir=d), config_path)
    db = SessionDB(d / "index.db")
    db.init()
    console.print(f"[green]Initialized session-zoo at {d}[/green]")

    # Install skills
    if not skip_skills:
        from session_zoo.installer import install_skills
        claude_dir = _claude_dir()
        skills_dir = claude_dir / "skills"
        installed, skipped = install_skills(skills_dir)
        if installed:
            console.print(f"[green]Installed {installed} skill(s)[/green]")
        if skipped:
            console.print(f"[dim]Skipped {skipped} existing skill(s)[/dim]")

    # Install hook
    if not skip_hooks:
        from session_zoo.installer import install_hook
        claude_dir = _claude_dir()
        claude_dir.mkdir(parents=True, exist_ok=True)
        added = install_hook(claude_dir)
        if added:
            console.print("[green]Installed SessionStart hook[/green]")
        else:
            console.print("[dim]SessionStart hook already installed[/dim]")


@config_app.command("show")
def config_show():
    """Show current configuration."""
    cfg = _get_config()
    console.print(f"Config dir: {cfg.config_dir}")
    console.print(f"Repo: {cfg.repo or '(not set)'}")
    console.print(f"AI model: {cfg.ai_model}")
    console.print(f"AI key: {'***' if cfg.ai_key else '(not set)'}")


@config_app.command("set")
def config_set(key: str, value: str):
    """Set a configuration value."""
    cfg = _get_config()
    if key == "repo":
        cfg.repo = value
    elif key == "ai-key":
        cfg.ai_key = value
    elif key == "ai-model":
        cfg.ai_model = value
    else:
        console.print(f"[red]Unknown key: {key}. Use: repo, ai-key, ai-model[/red]")
        raise typer.Exit(1)
    save_config(cfg, cfg.config_file)
    console.print(f"[green]Set {key} = {value if key != 'ai-key' else '***'}[/green]")


@app.command("import")
def import_sessions(
    tool: Optional[str] = typer.Option(None, help="Filter by tool"),
    project: Optional[str] = typer.Option(None, help="Filter by project"),
    since: Optional[str] = typer.Option(None, help="Only import after date (YYYY-MM-DD)"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only show output when new sessions found"),
):
    """Import new sessions from AI dev tools."""
    db = _get_db()
    since_dt = datetime.fromisoformat(since) if since else None
    tools = [tool] if tool else list_adapters()
    total_imported = 0
    total_updated = 0
    total_skipped = 0

    for tool_name in tools:
        adapter = get_adapter(tool_name, claude_dir=_claude_dir())
        paths = adapter.discover(since=since_dt, project=project)
        for path in paths:
            session = adapter.parse(path)
            existing = db.get_session(session.id)
            if existing:
                # Check if session has been updated (more messages or tokens changed)
                if (existing["message_count"] != session.message_count
                        or existing["total_tokens"] != session.total_tokens):
                    db.upsert_session(
                        id=session.id, tool=session.tool, project=session.project,
                        source_path=str(session.source_path),
                        started_at=session.started_at, ended_at=session.ended_at,
                        model=session.model, total_tokens=session.total_tokens,
                        message_count=session.message_count,
                    )
                    # Mark as modified so next sync picks it up
                    if existing["sync_status"] == "synced":
                        db.update_sync_status(session.id, "modified")
                    total_updated += 1
                else:
                    total_skipped += 1
                continue
            db.upsert_session(
                id=session.id, tool=session.tool, project=session.project,
                source_path=str(session.source_path),
                started_at=session.started_at, ended_at=session.ended_at,
                model=session.model, total_tokens=session.total_tokens,
                message_count=session.message_count,
            )
            total_imported += 1

    if quiet and total_imported == 0 and total_updated == 0:
        return

    parts = [f"[green]Imported: {total_imported}[/green]"]
    if total_updated:
        parts.append(f"[cyan]Updated: {total_updated}[/cyan]")
    parts.append(f"Skipped: {total_skipped}")
    console.print(" | ".join(parts))


@app.command("list")
def list_sessions(
    project: Optional[str] = typer.Option(None, help="Filter by project"),
    tag: Optional[str] = typer.Option(None, help="Filter by tag"),
    tool: Optional[str] = typer.Option(None, help="Filter by tool"),
    since: Optional[str] = typer.Option(None, help="Filter by start date"),
    status: Optional[str] = typer.Option(None, help="Filter by sync status"),
    no_summary: bool = typer.Option(False, help="Only show sessions without summary"),
):
    """List indexed sessions."""
    db = _get_db()
    sessions = db.list_sessions(
        project=project, tag=tag, tool=tool,
        since=since, status=status, no_summary=no_summary,
    )
    if not sessions:
        console.print("No sessions found.")
        return

    table = Table()
    table.add_column("ID", style="cyan", max_width=12)
    table.add_column("Project")
    table.add_column("Tool")
    table.add_column("Date")
    table.add_column("Tokens", justify="right")
    table.add_column("Status")
    table.add_column("Summary", max_width=40)

    for s in sessions:
        date = s["started_at"][:10] if s["started_at"] else "?"
        table.add_row(
            s["id"][:12],
            s["project"],
            s["tool"],
            date,
            f"{s['total_tokens']:,}" if s["total_tokens"] else "?",
            s["sync_status"],
            (s["summary"] or "")[:40],
        )

    console.print(table)


@app.command("show")
def show_session(
    id: str = typer.Argument(help="Session ID (or prefix)"),
    raw: bool = typer.Option(False, help="Show raw JSONL"),
    markdown: bool = typer.Option(False, help="Show rendered Markdown"),
):
    """Show session details."""
    db = _get_db()
    session = db.get_session(id)
    if not session:
        # Check if prefix matches multiple sessions
        matches = db.find_sessions_by_prefix(id)
        if len(matches) > 1:
            console.print(f"[yellow]Ambiguous ID prefix '{id}', matches {len(matches)} sessions:[/yellow]")
            for m in matches:
                console.print(f"  {m['id'][:16]}  {m['project']}")
            raise typer.Exit(1)
        console.print(f"[red]Session not found: {id}[/red]")
        raise typer.Exit(1)

    # Use resolved full ID for all subsequent operations
    id = session["id"]

    if raw:
        source = Path(session["source_path"])
        if source.exists():
            console.print(source.read_text())
        else:
            console.print(f"[red]Source file not found: {source}[/red]")
        return

    if markdown:
        adapter = get_adapter(session["tool"], claude_dir=_claude_dir())
        source = Path(session["source_path"])
        if source.exists():
            parsed = adapter.parse(source)
            tags = db.get_tags(id)
            md = render_session_markdown(parsed, summary=session.get("summary"), tags=tags)
            console.print(md)
        else:
            console.print(f"[red]Source file not found: {source}[/red]")
        return

    tags = db.get_tags(id)
    console.print(f"[bold]Session: {session['id']}[/bold]")
    console.print(f"Tool: {session['tool']}")
    console.print(f"Project: {session['project']}")
    console.print(f"Model: {session['model']}")
    console.print(f"Started: {session['started_at']}")
    console.print(f"Ended: {session['ended_at']}")
    console.print(f"Tokens: {session['total_tokens']:,}" if session['total_tokens'] else "Tokens: ?")
    console.print(f"Messages: {session['message_count']}")
    console.print(f"Sync: {session['sync_status']}")
    if tags:
        console.print(f"Tags: {', '.join(tags)}")
    if session.get("summary"):
        console.print(f"\n[bold]Summary:[/bold]\n{session['summary']}")


@app.command("search")
def search_sessions(query: str = typer.Argument(help="Search query")):
    """Search sessions by summary content. (v1: summary only, future: SQLite FTS5)"""
    db = _get_db()
    all_sessions = db.list_sessions()
    matches = [
        s for s in all_sessions
        if s.get("summary") and query.lower() in s["summary"].lower()
    ]
    if not matches:
        console.print("No matches found.")
        return

    for s in matches:
        console.print(f"[cyan]{s['id'][:12]}[/cyan] [{s['project']}] {s['summary'][:60]}")


@app.command("tag")
def tag_session(
    id: str = typer.Argument(help="Session ID"),
    tags: list[str] = typer.Argument(default=None, help="Tags to add"),
    remove: Optional[str] = typer.Option(None, help="Tag to remove"),
):
    """Add or remove tags on a session."""
    db = _get_db()
    full_id = db.resolve_id(id)
    if not full_id:
        console.print(f"[red]Session not found: {id}[/red]")
        raise typer.Exit(1)
    id = full_id

    if remove:
        db.remove_tag(id, remove)
        console.print(f"[green]Removed tag '{remove}' from {id[:12]}[/green]")
    elif tags:
        db.add_tags(id, tags)
        console.print(f"[green]Added tags {tags} to {id[:12]}[/green]")

    current = db.get_tags(id)
    console.print(f"Current tags: {', '.join(current) if current else '(none)'}")


@app.command("tags")
def list_tags():
    """List all tags and their counts."""
    db = _get_db()
    tags = db.list_all_tags()
    if not tags:
        console.print("No tags found.")
        return
    for tag, count in tags:
        console.print(f"  {tag}: {count}")


@app.command("delete")
def delete_session(
    id: str = typer.Argument(help="Session ID"),
    index_only: bool = typer.Option(False, help="Only remove from index"),
):
    """Delete a session."""
    db = _get_db()
    session = db.get_session(id)
    if not session:
        console.print(f"[red]Session not found: {id}[/red]")
        raise typer.Exit(1)
    id = session["id"]  # resolve to full ID

    confirm = typer.confirm(f"Delete session {id[:12]}?")
    if not confirm:
        return

    db.delete_session(id)
    console.print(f"[green]Deleted session {id} from index[/green]")

    if not index_only:
        console.print("[yellow]Note: Run 'zoo sync' to remove from GitHub repo[/yellow]")


@app.command("summarize")
def summarize(
    id: Optional[str] = typer.Argument(None, help="Session ID (omit for all)"),
    force: bool = typer.Option(False, help="Regenerate existing summaries"),
    model: Optional[str] = typer.Option(None, help="AI model to use"),
    provider: Optional[str] = typer.Option(None, help="Provider: auto, claude-code, codex, api"),
):
    """Generate AI summaries for sessions.

    Without --provider, auto-detects: claude CLI > codex CLI > API key.
    No API key needed if claude or codex CLI is installed.
    """
    from session_zoo.summarizer import generate_summary, detect_provider

    cfg = _get_config()
    db = _get_db()
    prov = provider or "auto"

    # Show which provider will be used
    if prov == "auto":
        if cfg.ai_key:
            effective = "api"
        else:
            effective = detect_provider()
            if effective is None:
                console.print(
                    "[red]No provider available. Install claude-code or codex, "
                    "or run: zoo config set ai-key <key>[/red]"
                )
                raise typer.Exit(1)
        console.print(f"[dim]Using provider: {effective}[/dim]")

    if id:
        sessions = [db.get_session(id)]
        if not sessions[0]:
            console.print(f"[red]Session not found: {id}[/red]")
            raise typer.Exit(1)
    else:
        sessions = db.list_sessions(no_summary=not force)

    count = 0
    for s in sessions:
        if not force and s.get("summary"):
            continue

        adapter = get_adapter(s["tool"], claude_dir=_claude_dir())
        source = Path(s["source_path"])
        if not source.exists():
            console.print(f"[yellow]Skip {s['id'][:12]}: source file missing[/yellow]")
            continue

        parsed = adapter.parse(source)
        console.print(f"Summarizing {s['id'][:12]} ({s['project']})...", end=" ")
        try:
            summary = generate_summary(
                parsed,
                provider=prov,
                api_key=cfg.ai_key,
                model=model,
            )
            db.update_summary(s["id"], summary)
            console.print("[green]done[/green]")
            count += 1
        except RuntimeError as e:
            console.print(f"[red]failed: {e}[/red]")

    console.print(f"\n[green]Summarized {count} session(s)[/green]")


@app.command("sync")
def sync(
    dry_run: bool = typer.Option(False, help="Preview changes without syncing"),
):
    """Sync sessions to GitHub."""
    from session_zoo import sync as sync_module

    cfg = _get_config()
    if not cfg.repo:
        console.print("[red]Repo not set. Run: zoo config set repo <url>[/red]")
        raise typer.Exit(1)

    db = _get_db()
    repo_dir = cfg.repo_dir

    if not repo_dir.exists():
        console.print(f"Cloning {cfg.repo}...")
        sync_module.init_repo(repo_dir, cfg.repo)
    else:
        console.print("Pulling latest...")
        sync_module.pull_repo(repo_dir)

    pending = db.list_sessions(status="pending") + db.list_sessions(status="modified")
    if not pending:
        console.print("Everything up to date.")
        return

    if dry_run:
        console.print(f"Would sync {len(pending)} session(s):")
        for s in pending:
            console.print(f"  {s['id'][:12]} ({s['project']}) [{s['sync_status']}]")
        return

    for s in pending:
        source = Path(s["source_path"])
        if not source.exists():
            console.print(f"[yellow]Skip {s['id'][:12]}: source missing[/yellow]")
            continue

        sync_module.copy_raw_session(
            repo_dir=repo_dir, source_path=source,
            tool=s["tool"], project=s["project"], session_id=s["id"],
        )

        tags = db.get_tags(s["id"])
        adapter = get_adapter(s["tool"], claude_dir=_claude_dir())
        parsed = adapter.parse(source)
        meta = {
            "session_id": s["id"], "tool": s["tool"], "project": s["project"],
            "started_at": s["started_at"], "ended_at": s["ended_at"],
            "model": s["model"], "total_tokens": s["total_tokens"],
            "message_count": s["message_count"], "summary": s.get("summary"),
            "tags": tags, "source_path": s["source_path"],
            "cwd": parsed.cwd,
        }
        sync_module.write_meta_json(
            repo_dir=repo_dir, tool=s["tool"], project=s["project"],
            session_id=s["id"], meta=meta,
        )

        md = render_session_markdown(parsed, summary=s.get("summary"), tags=tags)
        date = s["started_at"][:10] if s["started_at"] else "unknown"
        sync_module.write_session_markdown(
            repo_dir=repo_dir, project=s["project"], date=date,
            tool=s["tool"], session_id=s["id"], content=md,
        )

        db.update_sync_status(s["id"], "synced")
        console.print(f"  [green]Synced {s['id'][:12]}[/green]")

    committed = sync_module.commit_and_push(
        repo_dir, f"zoo: sync {len(pending)} session(s)",
    )
    if committed:
        console.print(f"\n[green]Pushed {len(pending)} session(s) to GitHub[/green]")


@app.command("clone")
def clone():
    """Clone the session repo to local."""
    from session_zoo import sync as sync_module

    cfg = _get_config()
    if not cfg.repo:
        console.print("[red]Repo not set. Run: zoo config set repo <url>[/red]")
        raise typer.Exit(1)

    if cfg.repo_dir.exists():
        console.print("[yellow]Repo already exists locally. Use 'zoo sync' to update.[/yellow]")
        return

    console.print(f"Cloning {cfg.repo}...")
    sync_module.init_repo(cfg.repo_dir, cfg.repo)
    console.print("[green]Clone complete.[/green]")


@app.command("reindex")
def reindex():
    """Rebuild SQLite index from repo files."""
    from session_zoo import sync as sync_module

    cfg = _get_config()
    repo_dir = cfg.repo_dir
    if not repo_dir.exists():
        console.print("[red]Repo not found. Run 'zoo clone' first.[/red]")
        raise typer.Exit(1)

    db = _get_db()
    raw_sessions = sync_module.list_raw_sessions(repo_dir)
    count = 0

    for entry in raw_sessions:
        meta = entry["meta"]
        db.upsert_session(
            id=entry["session_id"],
            tool=entry["tool"],
            project=entry["project"],
            source_path=str(entry["jsonl_path"]),
            started_at=datetime.fromisoformat(meta["started_at"]) if meta.get("started_at") else None,
            ended_at=datetime.fromisoformat(meta["ended_at"]) if meta.get("ended_at") else None,
            model=meta.get("model", "unknown"),
            total_tokens=meta.get("total_tokens", 0),
            message_count=meta.get("message_count", 0),
        )
        if meta.get("summary"):
            db.update_summary(entry["session_id"], meta["summary"])
        if meta.get("tags"):
            db.add_tags(entry["session_id"], meta["tags"])
        db.update_sync_status(entry["session_id"], "synced")
        count += 1

    console.print(f"[green]Reindexed {count} session(s) from repo[/green]")


@app.command("restore")
def restore(
    project: Optional[str] = typer.Option(None, help="Only restore specific project"),
    tool: Optional[str] = typer.Option(None, help="Only restore specific tool"),
):
    """Restore session files to tool directories (e.g. ~/.claude/) for /resume support."""
    import shutil
    from session_zoo import sync as sync_module

    cfg = _get_config()
    repo_dir = cfg.repo_dir
    if not repo_dir.exists():
        console.print("[red]Repo not found. Run 'zoo clone' first.[/red]")
        raise typer.Exit(1)

    raw_sessions = sync_module.list_raw_sessions(repo_dir)
    count = 0

    for entry in raw_sessions:
        if project and entry["project"] != project:
            continue
        if tool and entry["tool"] != tool:
            continue

        adapter = get_adapter(entry["tool"], claude_dir=_claude_dir())
        meta = entry["meta"]
        from session_zoo.models import Session
        session = Session(
            id=entry["session_id"], tool=entry["tool"],
            project=entry["project"], source_path=entry["jsonl_path"],
            started_at=None, ended_at=None, model="", total_tokens=0,
            cwd=meta.get("cwd"),
        )

        dest = adapter.get_restore_path(session)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(str(entry["jsonl_path"]), str(dest))
            console.print(f"  Restored {entry['session_id'][:12]} → {dest}")
            count += 1

    console.print(f"\n[green]Restored {count} session(s)[/green]")
