# Session Zoon — Design Spec

AI 开发会话记录工具，将开发会话保存到 GitHub，适配不同 AI 开发工具。

## Goals

- **当前**：个人回顾，方便回看开发过程和决策
- **后期**：团队知识共享、审计合规

## Scope (v1)

- 只支持 Claude Code
- CLI 工具（命令名：`zoom`）
- Python + Typer
- 后期可扩展：更多工具适配、守护进程、Hook、定时任务

## Architecture

方案 B：本地 SQLite 索引 + Adapter 模式。

### Three-Layer Design

| 层 | 角色 | 说明 |
|---|---|---|
| GitHub Repo | Source of Truth | 原始 JSONL + meta.json + Markdown 摘要 |
| SQLite Index | 本地缓存 | 加速搜索和管理，可从仓库重建 |
| ~/.claude/ | 工作区 | 通过 restore 恢复，支持 /resume 等工具功能 |

### Data Flow

```
~/.claude/projects/**/*.jsonl
        │
        ▼
zoom import ── Adapter 解析 ──▶ SQLite 索引 (本地缓存)
                                      │
                                      ▼
zoom summarize ── AI API ──▶ 摘要写入索引 + meta.json
                                      │
                                      ▼
zoom sync ── 生成文件 ──▶ GitHub Repo
                            ├── raw/claude-code/项目名/*.jsonl
                            ├── raw/claude-code/项目名/*.meta.json
                            └── sessions/项目名/日期/claude-code/*.md
```

### Cross-Device Restore

```
GitHub Repo
    │
    ▼
zoom clone    ── 克隆仓库到本地
    ▼
zoom reindex  ── 从 JSONL + meta.json 重建 SQLite
    ▼
zoom restore  ── 复制 JSONL 回 ~/.claude/ 以支持 /resume
```

## GitHub Repo Structure

```
session-zoon-repo/
├── raw/                           # 原始文件（按工具/项目，方便迁移）
│   └── claude-code/
│       └── my-project/
│           ├── abc123.jsonl       # 原始会话
│           └── abc123.meta.json   # 标签、摘要、备注
│
└── sessions/                      # 可读摘要（按项目/日期/工具）
    └── my-project/
        └── 2026-03-10/
            └── claude-code/
                └── abc123.md
```

## Local File Structure

```
~/.session-zoon/
├── config.toml       # 配置：GitHub repo、AI API key
├── index.db          # SQLite 索引
└── cache/            # 临时缓存
```

## CLI Commands

### Init & Config

```
zoom init                       # 初始化 ~/.session-zoon/，配置 GitHub repo
zoom config set repo <url>      # 设置 GitHub 仓库
zoom config set ai-key <key>    # 设置 AI API key
zoom config show                # 查看配置
```

### Import

```
zoom import                     # 扫描所有已知工具，导入新会话
zoom import --tool claude-code  # 只导入指定工具
zoom import --project my-app    # 只导入指定项目
zoom import --since 2026-03-01  # 只导入指定日期之后
```

### View & Search

```
zoom list                       # 列出所有会话（最近优先）
zoom list --project my-app      # 按项目过滤
zoom list --tag bugfix          # 按标签过滤
zoom list --since 2026-03-01    # 按日期过滤
zoom list --no-summary          # 未生成摘要的会话
zoom list --status pending      # 未同步的会话
zoom show <id>                  # 查看会话详情
zoom show <id> --raw            # 查看原始内容
zoom show <id> --markdown       # 查看 Markdown
zoom search "XSS 漏洞"          # 全文搜索
```

### Manage & Tag

```
zoom tag <id> bugfix security   # 添加标签
zoom tag <id> --remove bugfix   # 移除标签
zoom tags                       # 列出所有标签
zoom delete <id>                # 删除会话
zoom delete <id> --index-only   # 只从索引删除
```

### AI Summary

```
zoom summarize                  # 为所有未摘要的会话生成摘要
zoom summarize <id>             # 为指定会话生成/更新摘要
zoom summarize --force          # 重新生成所有
zoom summarize --model haiku    # 用指定模型
```

### Sync & Restore

```
zoom sync                       # 同步 pending 会话到 GitHub
zoom sync --dry-run             # 预览变更
zoom clone                      # 克隆仓库到本地
zoom reindex                    # 从仓库重建 SQLite
zoom restore                    # 恢复 JSONL 到 ~/.claude/
zoom restore --project my-app   # 只恢复指定项目
```

## Data Models

```python
@dataclass
class Session:
    id: str                     # 会话 UUID
    tool: str                   # "claude-code" | "codex" | ...
    project: str                # 项目名称
    source_path: Path           # 原始文件路径
    started_at: datetime
    ended_at: datetime
    model: str
    total_tokens: int
    messages: list[Message]
    git_branch: str | None
    cwd: str | None

@dataclass
class Message:
    role: str                   # "user" | "assistant" | "system"
    content: str
    timestamp: datetime
    tool_calls: list[dict]
    token_usage: dict | None
```

## SQLite Schema

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    project TEXT NOT NULL,
    source_path TEXT NOT NULL,
    started_at DATETIME,
    ended_at DATETIME,
    model TEXT,
    total_tokens INTEGER,
    message_count INTEGER,
    summary TEXT,
    sync_status TEXT DEFAULT 'pending',  -- pending | synced | modified
    synced_at DATETIME
);

CREATE TABLE tags (
    session_id TEXT REFERENCES sessions(id),
    tag TEXT NOT NULL,
    PRIMARY KEY (session_id, tag)
);
```

## Adapter Protocol

```python
class SessionAdapter(Protocol):
    name: str

    def discover(self, since: datetime | None,
                 project: str | None) -> list[Path]:
        """发现本地会话文件"""

    def parse(self, path: Path) -> Session:
        """解析原始文件为统一 Session"""

    def get_restore_path(self, session: Session) -> Path:
        """返回恢复时应放置的目标路径"""
```

Adding a new tool: implement these 3 methods, register in adapter registry.

## meta.json Format

```json
{
    "session_id": "abc123",
    "tool": "claude-code",
    "project": "my-project",
    "started_at": "2026-03-10T10:30:00Z",
    "ended_at": "2026-03-10T11:45:00Z",
    "model": "claude-opus-4-6",
    "total_tokens": 52340,
    "message_count": 28,
    "summary": "修复了登录页的 XSS 漏洞...",
    "tags": ["bugfix", "security"],
    "source_path": "~/.claude/projects/-home-user-my-project/uuid.jsonl"
}
```

## Markdown Summary Template

```markdown
# 修复登录页 XSS 漏洞

| 字段 | 值 |
|------|------|
| 会话 ID | abc123 |
| 工具 | claude-code |
| 模型 | claude-opus-4-6 |
| 项目 | my-project |
| 分支 | fix/xss-login |
| 时间 | 2026-03-10 10:30 → 11:45 (1h15m) |
| Token | 52,340 (输入: 38,200 / 输出: 14,140) |
| 消息数 | 28 条 |
| 标签 | `bugfix` `security` |

## 摘要
(AI 生成)

## 关键决策
(AI 生成)

## 涉及文件
(从工具调用中提取)

## 会话记录
(关键对话摘录)
```

## Project Structure

```
session-zoon/
├── pyproject.toml
├── src/session_zoon/
│   ├── __init__.py
│   ├── cli.py              # Typer CLI 入口
│   ├── config.py           # 配置管理
│   ├── db.py               # SQLite 索引操作
│   ├── models.py           # Session, Message 数据模型
│   ├── summarizer.py       # AI 摘要生成
│   ├── renderer.py         # Markdown 渲染
│   ├── sync.py             # GitHub 同步逻辑
│   └── adapters/
│       ├── __init__.py     # Adapter 注册表
│       └── claude_code.py  # Claude Code adapter
└── tests/
```

## Tech Stack

- **Language**: Python 3.12+
- **CLI**: Typer
- **Database**: SQLite (stdlib)
- **AI Summary**: Anthropic API (claude-haiku for cost, configurable)
- **Git**: subprocess calls to git CLI
- **Config**: TOML (stdlib tomllib)
- **Package**: pyproject.toml with hatchling or setuptools
