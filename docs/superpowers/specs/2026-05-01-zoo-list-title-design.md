# Zoo List Title — Design

**Status**: Draft
**Date**: 2026-05-01
**Author**: brainstorm with Claude

## Background

`zoo list` 当前在第 7 列显示 `summary[:40]`。AI 生成的 summary 实际是个 markdown 块（开头是 `## Session Summary\n\n**Title:** ...`），盲目截断后用户只看到表头噪音，看不到真正的标题；没生成过 summary 的 session 这一列直接是空的，无法识别。

调研发现 Claude Code 自身在 jsonl 里写一条 `{"type":"ai-title","aiTitle":"..."}` 记录给 `/resume` 用——结构清晰、跨 session 自动生成、随 jsonl 文件自然传播到同步仓库和恢复目标机器。利用这个数据 + 解析 summary 中的 `**Title:**` 行 + 兜底首条 user 消息，可以让每条 session 都有一个高质量的可识别标题。

## Goals

- `zoo list` 每行显示一个简短标题，跨"已总结/未总结/手动设置"三种状态都有合理结果。
- 复用 Claude Code 原生的 `aiTitle`，跟 `/resume` 显示一致。
- 用户可手动覆盖（`zoo title <id> "..."`）。
- 自动流程不踩用户的手动标题。
- 同步链路完整：title 跟 session 一起进同步仓库、`reindex` 能恢复。

## Non-Goals

- 不改 summary 字段本身（仍按现有逻辑生成完整 markdown）。
- 不为标题做 i18n／sanitization（除最小化的 strip + 折叠空白）。
- 不引入 TUI 编辑界面。
- 不在 title 变化时把 session 标记为需重推同步。

## Architecture Overview

新增两个数据列 + 一个写入入口（带优先级守卫）+ 各 CLI 命令的触发点。所有标题最终落到 `sessions.title`，单一来源给 `zoo list`/`zoo show` 读。

```
┌──────────────────────────────────────────────────────────────────┐
│  sources (优先级 1=最高)                                         │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ 1 manual         zoo title <id> "..."                      │  │
│  │ 2 summary        zoo summarize 解析 summary 中 **Title:**  │  │
│  │ 3 ai-title       adapter 从 jsonl 抽 type=="ai-title"      │  │
│  │ 4 first-message  adapter 截首条 user 消息 ≤80 字符         │  │
│  └─────────────────────┬──────────────────────────────────────┘  │
│                        │                                         │
│                        ▼                                         │
│   db.update_title(id, title, source) — 优先级守卫                │
│   （新 source ≤ 已有 source 时才写）                             │
│                        │                                         │
│                        ▼                                         │
│            sessions.title  +  sessions.title_source              │
│                        │                                         │
│   ┌────────────────────┼─────────────────────┐                   │
│   ▼                    ▼                     ▼                   │
│ zoo list            zoo show              zoo sync               │
│ (Title 列)          (Title + source)      (写进 meta.json)       │
└──────────────────────────────────────────────────────────────────┘
                                                  │
                                                  ▼
                                       reindex 调 set_title_raw
                                       （绕过守卫直接恢复）
```

## Data Model

### `sessions` 表新增列

```sql
ALTER TABLE sessions ADD COLUMN title TEXT;
ALTER TABLE sessions ADD COLUMN title_source TEXT;
```

`title_source` 取值：

| 值 | 含义 | 优先级（数字越小越优先） |
|----|------|----------|
| `manual` | 用户 `zoo title <id> "..."` | 1 |
| `summary` | 从 summary 的 `**Title:**` 行解析 | 2 |
| `ai-title` | adapter 从 jsonl 抽出（如 Claude Code 的 `aiTitle`） | 3 |
| `first-message` | 首条 user 消息截断 ≤80 字符 | 4 |
| `NULL` | 还没算出来；显示 `(untitled)` | 5（最低） |

### `meta.json` schema 扩展

`zoo sync` 写出的 meta.json 增加：

```json
{
  "title": "Debug remote session sync plugin error",
  "title_source": "ai-title"
}
```

旧 meta.json 没这两个字段时 reindex 容错跳过（保持 NULL）。

## Components

### `db.py` — 新增方法

```python
def update_title(self, id: str, title: str, source: str) -> bool:
    """带优先级守卫的写入。返回 True=已写入，False=被更高优先级保护。"""

def set_title_raw(self, id: str, title: str | None, source: str | None) -> None:
    """直接写入，不做优先级判断。仅给 reindex 用。"""

def clear_title(self, id: str) -> None:
    """把 title 和 title_source 都设为 NULL（zoo title --reset）。"""
```

`init()` 里加幂等迁移：

```python
for sql in (
    "ALTER TABLE sessions ADD COLUMN title TEXT",
    "ALTER TABLE sessions ADD COLUMN title_source TEXT",
):
    try:
        conn.execute(sql)
    except sqlite3.OperationalError:
        pass
```

### `adapters/claude_code.py` — 新增方法

```python
def extract_native_title(self, path: Path) -> str | None:
    """扫 jsonl，取最后一条 type=='ai-title' 的 aiTitle 字段；
    没有就返回 None。最后一条是因为 Claude Code 会随对话演进重写。"""

def extract_first_message(self, path: Path) -> str | None:
    """取首条 type=='user' 的文本，strip + 折叠空白，截 80 字符；
    空字符串返回 None。"""
```

未来其他 adapter（Codex 等）实现 `extract_native_title` 即可对齐；没有原生 title 的就返回 None，自动降级到 first-message。

### `summarizer.py` — 新增函数

```python
def parse_title_from_summary(summary: str) -> str | None:
    """从 summary markdown 中正则抽 **Title:**\\s*(.+)$ 第一行；命中即返回，否则 None。"""
```

### `cli.py` — 命令变更

#### `zoo list` 表格列调整

把 `Summary` 列替换为 `Title` 列，宽度 50。

```python
table.add_column("Title", max_width=50)
# ...
title = (s["title"] or "(untitled)")[:50]
```

完整 summary 仍能在 `zoo show <id>` 里看到。

#### `zoo show <id>` 输出补充

在 `Project` 行之上插入：

```
Title: <title>   (source: <title_source>)
```

title 为 NULL 时显示 `(untitled)`。

#### 新命令 `zoo title`

```python
@app.command("title")
def title_cmd(
    id: Optional[str] = typer.Argument(None),
    text: Optional[str] = typer.Argument(None),
    reset: bool = typer.Option(False, "--reset"),
    backfill: bool = typer.Option(False, "--backfill"),
):
    ...
```

行为：

| 调用 | 行为 |
|------|------|
| `zoo title <id>` | 显示当前 title 和 source |
| `zoo title <id> "新标题"` | `db.update_title(id, "新标题", "manual")` |
| `zoo title <id> --reset` | `db.clear_title(id)` |
| `zoo title --backfill` | 扫 DB 中所有 session，对每条按优先级再算一遍：调 `extract_native_title`、`extract_first_message`、`parse_title_from_summary`，把所有结果交给 `update_title`（守卫保证不踩 manual） |

#### `zoo import` 集成

`cli.py:106-161` 的 `import_sessions` 在每次 `db.upsert_session` 之后追加：

```python
native = adapter.extract_native_title(path)
if native:
    db.update_title(session.id, native, "ai-title")
else:
    first = adapter.extract_first_message(path)
    if first:
        db.update_title(session.id, first, "first-message")
```

注意守卫保证：已有 manual / summary 不会被踩。

#### `zoo summarize` 集成

`cli.py:344-410` 的 `summarize` 在 `db.update_summary(s["id"], summary)` 之后追加：

```python
title = parse_title_from_summary(summary)
if title:
    db.update_title(s["id"], title, "summary")
```

#### `zoo reindex` 集成

`cli.py:509-544` 的 reindex 在 `upsert_session` + `update_summary` + `add_tags` 之后追加：

```python
if meta.get("title"):
    db.set_title_raw(entry["session_id"], meta["title"], meta.get("title_source"))
```

用 `set_title_raw` 跳过守卫——reindex 是从权威源恢复，不是派生。

#### `zoo sync` meta 字段

`cli.py:460-467` 构造 meta dict 时加：

```python
meta = {
    ...,
    "title": s.get("title"),
    "title_source": s.get("title_source"),
}
```

## Data Flow

### 新 session import 路径

```
new jsonl → adapter.parse() → db.upsert_session()
         → adapter.extract_native_title() → "Debug remote session sync plugin error"
         → db.update_title(id, "Debug ...", "ai-title")  ✓ written (was NULL)
```

### 已 import 的 session 再被 import（message_count 变化）

```
更新过的 jsonl → upsert_session()
              → extract_native_title() 可能这次有值了
              → update_title(..., "ai-title")
                 │
                 ├─ 现有 source 是 NULL/first-message → 写入 ✓
                 ├─ 现有 source 是 ai-title → 写入（新值覆盖旧值）✓
                 ├─ 现有 source 是 summary → 跳过 ✗
                 └─ 现有 source 是 manual → 跳过 ✗
```

### summarize 路径

```
zoo summarize → AI 输出 markdown summary
              → db.update_summary(id, summary)  [既有逻辑]
              → parse_title_from_summary(summary) → "session-zoo Windows..."
              → db.update_title(id, "...", "summary")
                 │
                 ├─ 现有是 manual → 跳过 ✗
                 └─ 其他 → 写入 ✓
```

### 新机器恢复路径

```
zoo init       → 新 schema（含 title 列）
zoo clone      → repo 落地
zoo reindex    → 读 meta.json → set_title_raw（直接恢复 title + source）
zoo restore    → jsonl 回 ~/.claude/projects/   ← /resume 也能用 ai-title
zoo list       → 看到 Title 列 ✓
```

## Error Handling

- **DB 迁移失败**：`OperationalError` 表示列已存在，silently 跳过。其他异常（极少见）让它冒泡。
- **jsonl 损坏**：`extract_native_title` / `extract_first_message` 内部 try/except，单行解析失败跳过；整文件读不出来就返回 None，不阻断 import。
- **meta.json 缺 title 字段**：`meta.get("title")` 返回 None，reindex 跳过（保持 NULL，等下次 import/summarize/backfill 填）。
- **空标题**：`update_title` 拒绝写空字符串（视为 None）。
- **超长 first-message**：固定截 80 字符，不留省略号。
- **多条 ai-title 记录**：取最后一条（流式遍历，记录每次出现，最后返回最新值）。

## Testing

### 单元测试

**`tests/test_db.py`**
- `test_init_adds_title_columns_on_existing_db` — 模拟旧 schema：先用裸 SQL 建无 title 列的 sessions 表，再调 `db.init()`，能写 title。
- `test_update_title_priority_guard` — 五用例：
  - `NULL → manual` ✓
  - `manual → summary` ✗
  - `summary → manual` ✓
  - `first-message → ai-title` ✓
  - `ai-title → first-message` ✗
- `test_set_title_raw_bypasses_guard` — 给 manual 强制覆盖为 ai-title。
- `test_clear_title_resets_both_columns` — 验证 title 和 title_source 都变 NULL。

**`tests/test_claude_code_adapter.py`**
- `test_extract_native_title_returns_ai_title` — fixture 含一条 ai-title。
- `test_extract_native_title_returns_last_when_multiple` — 多条，返回最后一条。
- `test_extract_native_title_returns_none_when_absent`
- `test_extract_first_message_truncates_and_collapses_whitespace` — 多行 + 首条 user 含 `\n\n  text  ` → 返回单空格折叠 + 80 字符截断。
- `test_extract_first_message_returns_none_when_empty`

**`tests/test_summarizer.py`**
- `test_parse_title_from_summary_standard` — `**Title:** xxx\n` → `"xxx"`
- `test_parse_title_from_summary_chinese` — 中文 title 不丢
- `test_parse_title_from_summary_missing_returns_none`

### 集成测试

**`tests/test_cli.py`**
- `test_import_populates_title_from_ai_title`
- `test_import_falls_back_to_first_message_when_no_ai_title`
- `test_summarize_overrides_first_message_title`
- `test_manual_title_not_overridden_by_summarize`
- `test_manual_title_not_overridden_by_import`
- `test_title_reset_clears_and_allows_re_derivation`
- `test_title_backfill_fills_existing_untitled_sessions`
- `test_list_shows_title_column`
- `test_show_displays_title_with_source`

**`tests/test_sync.py`**
- `test_meta_json_includes_title_fields`
- `test_reindex_restores_title_from_meta`

### 现有测试调整

凡 `tests/test_cli.py` 中检查 `Summary` 表头/列宽的，改为 `Title`。

### Fixtures

- `tests/conftest.py` 现有 `sample_claude_session` **保留不变**（无 ai-title），用作"兜底到 first-message"路径的 fixture。
- 新增 `sample_claude_session_with_ai_title`：在现有 jsonl 基础上插入一条 `{"type":"ai-title","aiTitle":"Test ai title"}`。

## Migration / Rollout

### 升级路径 A — 本机已有 DB

1. `pip install -U session-zoo`
2. 任意命令触发 `db.init()` → ALTER TABLE 加 title 列（值 NULL）
3. 用户跑 `zoo title --backfill` → 扫所有 session 的本地 jsonl 回填
4. `zoo list` 看到 Title

### 升级路径 B — 新机器从远端仓库恢复

1. `zoo init` → 新 schema
2. `zoo config set repo <url>` + `zoo clone`
3. `zoo reindex` → meta.json 中的 title 和 title_source 进 DB
4. `zoo restore` → jsonl 回 `~/.claude/projects/`
5. `zoo list` 看到 Title；`/resume` 看到原 ai-title

### 同步重推策略

**title 变化不触发 modified**——理由：
- manual title 是本地偏好，未必想推到共享仓库
- 频繁 summarize 会把全部 session 标 modified，sync 噪音大
- 等下一次 message_count 变化触发 sync 时会自然带上新 title

## Open Questions

无。所有决策点已在上面闭环。

## Out of Scope (Future Work)

- Codex / 其他 adapter 的 `extract_native_title` 实现（按需补）。
- `zoo title --backfill` 加 `--dry-run` 预览。
- `zoo list` 加 `--sort-by title` 选项。
- title 多语言截断（按字符宽度而非字符数）。
