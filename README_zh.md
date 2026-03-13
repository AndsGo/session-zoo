# session-zoo

[English](README.md) | [中文](README_zh.md)

将你的 AI 开发会话保存并同步到 GitHub。

`session-zoo` 自动发现 AI 编程工具（Claude Code、Codex 等）的会话记录，生成 AI 摘要，并将所有数据同步到 GitHub 仓库 —— 原始数据完整保留以便跨设备迁移，同时生成可读的 Markdown 方便回顾。

## 特性

- **自动发现** `~/.claude/` 下的会话（内置 Claude Code 适配器）
- **AI 摘要** 直接使用已安装的 Claude/Codex CLI（无需 API key），也支持 Anthropic API
- **Git 同步** 原始 JSONL + 元数据 + Markdown 摘要同步到 GitHub
- **跨设备恢复** — 在新设备 clone 后恢复会话到 `~/.claude/`，支持 `/resume`
- **标签与搜索** 按项目、工具、日期或自定义标签管理会话
- **可扩展** 适配器模式，轻松添加新工具支持

## 快速开始

### 安装

```bash
pip install session-zoo
```

或从源码安装：

```bash
git clone https://github.com/AndsGo/session-zoo.git
cd session-zoo
pip install -e .
```

### 初始化

```bash
# 初始化配置
zoo init

# 设置 GitHub 仓库（需先创建一个空仓库）
zoo config set repo git@github.com:yourname/my-sessions.git
```

### 基本用法

```bash
# 导入 Claude Code 会话
zoo import

# 查看所有会话
zoo list

# 查看会话详情
zoo show <session-id>
zoo show <session-id> --markdown

# 生成 AI 摘要（自动使用已安装的 claude/codex CLI）
zoo summarize <session-id>

# 添加标签
zoo tag <session-id> bugfix security

# 同步到 GitHub
zoo sync
```

### 跨设备恢复

在新设备上：

```bash
zoo init
zoo config set repo git@github.com:yourname/my-sessions.git
zoo clone      # 克隆会话仓库
zoo reindex    # 从仓库重建本地索引
zoo restore    # 恢复 .jsonl 文件到 ~/.claude/ 以支持 /resume
```

## 命令列表

| 命令 | 说明 |
|------|------|
| `zoo init` | 初始化配置 |
| `zoo config show/set` | 查看或设置配置（repo, ai-key, ai-model） |
| `zoo import` | 从 AI 工具导入新会话 |
| `zoo list` | 列出会话（支持 --project, --tool, --tag, --since 筛选） |
| `zoo show <id>` | 查看会话详情（--raw 原始数据, --markdown 渲染） |
| `zoo search <query>` | 按摘要内容搜索 |
| `zoo tag <id> [tags...]` | 添加/删除标签 |
| `zoo tags` | 列出所有标签及数量 |
| `zoo delete <id>` | 删除会话 |
| `zoo summarize [id]` | 生成 AI 摘要（--provider auto/claude-code/codex/api） |
| `zoo sync` | 同步到 GitHub（--dry-run 预览） |
| `zoo clone` | 克隆会话仓库到本地 |
| `zoo reindex` | 从仓库重建 SQLite 索引 |
| `zoo restore` | 恢复会话文件到工具目录 |

## 摘要生成

`zoo summarize` 支持多种方式，按优先级自动检测：

1. **claude-code** — 使用已安装的 `claude -p` CLI（无需 API key）
2. **codex** — 使用已安装的 `codex -q` CLI（无需 API key）
3. **api** — 直接调用 Anthropic API（需 `zoo config set ai-key <key>`）

```bash
# 自动检测
zoo summarize <id>

# 指定方式
zoo summarize --provider claude-code <id>
zoo summarize --provider api <id>
```

## GitHub 仓库结构

```
your-sessions-repo/
├── raw/claude-code/my-project/
│   ├── <session-id>.jsonl          # 原始会话数据（完整保留）
│   └── <session-id>.meta.json     # 元数据（标签、摘要、工作目录）
└── sessions/my-project/2026-03-10/claude-code/
    └── <session-id>.md            # 可读的 Markdown 摘要
```

## 添加适配器

session-zoo 使用适配器模式支持不同的 AI 工具。目前支持：

- **Claude Code** (`~/.claude/projects/`)

添加新适配器需实现 `discover()`、`parse()` 和 `get_restore_path()` 方法。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 环境要求

- Python 3.12+
- Git
- （可选）`claude` 或 `codex` CLI 用于无 API key 的摘要生成

## 许可证

[MIT](LICENSE)
