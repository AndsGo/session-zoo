# Cache Hit Rate Stats — Design

**Date:** 2026-06-11
**Status:** Approved

## Goal

Add the ability to inspect per-session, per-model prompt cache hit rates for
indexed AI development sessions, surfaced through a new `zoo stats` command and
persisted through the full sync/reindex chain.

## Background

Claude Code session JSONL files record, on every assistant message, the model
name (`message.model`) and a `usage` object containing `input_tokens`,
`cache_read_input_tokens`, `cache_creation_input_tokens`, and `output_tokens`.
A single session can involve multiple models (main model plus smaller models
for subagents / title generation).

Today `ClaudeCodeAdapter.parse()` collapses the three input-token kinds into a
single number and discards the per-model detail; the DB stores only an
aggregate `total_tokens`.

### Existing bug fixed alongside

Claude Code writes one JSONL record per content block, so a single assistant
message (one `message.id`) appears as several records, each carrying the
**same** `usage` object. The current parser accumulates usage per record,
inflating `total_tokens` (observed: identical usage counted 4x). All usage
accumulation — both the new per-model stats and the existing `total_tokens` —
must dedupe by `message.id`, counting each message's usage exactly once.

## Definitions

- **Hit rate** = `cache_read / (input + cache_read + cache_creation)`.
  Displayed as a percentage; shown as `?` when the denominator is 0.
- Cache write share (`cache_creation` proportion) is also displayed as a cost
  signal.

## Data flow

```
adapter.parse()                      per-model aggregation, deduped by message.id
  └─ Session.model_usage: dict[model, {input, cache_read, cache_creation, output}]
       └─ zoo import → db.replace_model_usage()      (model_usage table)
            └─ zoo sync → meta.json "model_usage"    (list of row dicts)
                 └─ zoo reindex → restore from meta; fall back to re-parsing
                    the repo JSONL when the field is absent (old meta files)
```

Parsing rules:

- Dedupe usage by `message.id` — count each assistant message once.
- Skip records whose model is `<synthetic>`.
- Include sidechain (subagent) records: they are real API usage.
- `Session.model` keeps its current first-seen semantics.

## Components

### models.py

`Session` gains `model_usage: dict[str, dict[str, int]]` (default empty dict),
mapping model name → `{input, cache_read, cache_creation, output}`.

### adapters/claude_code.py

`parse()` accumulates per-model usage with `message.id` dedup and uses the same
deduped numbers for `total_tokens`. No adapter interface change beyond the new
`Session` field; adapters that do not populate it simply leave it empty.

### db.py

New table, created in `init()` (idempotent, follows existing migration style):

```sql
CREATE TABLE IF NOT EXISTS model_usage (
    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, model)
);
```

New methods:

- `replace_model_usage(session_id, usage)` — DELETE existing rows for the
  session, then INSERT; idempotent.
- `get_model_usage(session_id) -> list[dict]` — rows for one session.
- `aggregate_model_usage(*, project=None, tool=None, since=None) -> list[dict]`
  — JOIN with `sessions`, apply filters, GROUP BY model; also returns the
  session count per model.

### cli.py

New command `zoo stats`:

- `zoo stats` — global per-model aggregate table. Columns:
  Model | Sessions | Input | Cache Read | Cache Write | Output | Hit Rate.
  Filters: `--project`, `--tool`, `--since`.
- `zoo stats <id>` — per-model breakdown for one session (same columns minus
  Sessions). ID prefix resolution follows existing commands.
- `zoo stats --backfill` — re-parse the JSONL of every indexed session and
  fill the `model_usage` table (mirrors `zoo title --backfill`); needed because
  already-imported sessions are skipped by `zoo import` when unchanged.

`zoo import` calls `db.replace_model_usage()` after each upsert (both new and
updated sessions).

### sync.py / reindex

- `zoo sync` adds a `model_usage` key to meta.json: a list of
  `{model, input_tokens, cache_read_tokens, cache_creation_tokens, output_tokens}`.
- `zoo reindex` restores from `meta["model_usage"]` when present; for old meta
  files without the field it re-parses the repo's JSONL via the adapter.

## Side effects

Fixing the dedup bug shrinks `total_tokens` for most sessions. The next
`zoo import` will therefore see every session as "updated", mark synced ones
as `modified`, and the next `zoo sync` re-pushes everything. One-time cost;
accepted.

## Error handling

- Missing source JSONL during `--backfill`: skip with a warning (matches
  `zoo summarize` behavior).
- Sessions with no usage data (e.g. empty sessions): no `model_usage` rows;
  excluded from stats output.
- Denominator 0 in hit rate: display `?`, never divide by zero.

## Testing

- Adapter: per-model aggregation; `message.id` dedup (same usage repeated
  across records counted once); `<synthetic>` skipped; sidechain included;
  `total_tokens` matches deduped sum.
- DB: `replace_model_usage` idempotency; `get_model_usage`;
  `aggregate_model_usage` filters and grouping; CASCADE delete.
- CLI: hit-rate formatting incl. zero denominator; `--backfill` fills rows.
- Sync: meta.json round-trip (`sync` writes → `reindex` restores).
- Reindex fallback: old meta without `model_usage` triggers JSONL re-parse.

## Out of scope

- Per-message or time-bucketed usage storage (no current need).
- Cost (USD) estimation.
- Surfacing hit rate in `zoo list` / `zoo show` (can be added later on top of
  the same table).
