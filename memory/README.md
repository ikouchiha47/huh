# Crisp Engine — Episodic Memory for AI Agents

Automatic, layered memory for Claude Code sessions. Every file you edit, every
correction you give, every session you run — captured, summarised, and promoted
through four layers so future sessions carry what past ones learned.

```
Edit file  →  L0 episode (raw diff + symbols)
              ↓ every 20 episodes
           L1 session summary
              ↓ every 10 summaries on same topic
           L2 topic cluster
              ↓ every 3 clusters
           L3 life arc (permanent)
```

Memory is **global** — stored in `~/.claude/memory/`, shared across all projects.
A bug fixed in one repo surfaces when you hit the same pattern elsewhere.

---

## How it works

| Hook | Fires when | What gets stored |
|---|---|---|
| `PostToolUse` (Write/Edit) | You edit a file | git diff + extracted symbols → L0 |
| `Stop` | Claude finishes a turn | Corrections and frustration signals → L0 |
| `PreCompact` | Context window fills | Last 30 conversation turns → L0, then full cascade |
| `SessionEnd` | Session closes | Conversation transcript → L0, then full cascade |

The cascade (`L0→L1→L2→L3`) runs automatically at `PreCompact` and `SessionEnd`.
Each layer has a decay half-life: L0=30d, L1=180d, L2=2yr, L3=permanent.

All layers write to `~/.claude/memory/` regardless of which project you're in.
Episodes are tagged with `source_path` so you can filter by project if needed.

---

## Installation

```bash
git clone https://github.com/ikouchiha47/huh
uv tool install ./huh/memory
```

This installs three commands into `~/.local/bin/`:

| Command | Purpose |
|---|---|
| `huh` | CLI — search, reflect, stats, prune |
| `crisp-hook` | Hook entry point wired into `.claude/settings.json` |
| `crisp-sense` | Standalone file analyser |

For **fish shell**, ensure `~/.local/bin` is on your PATH:

```fish
fish_add_path ~/.local/bin
```

After updates, reinstall to pick up changes:

```bash
uv tool install ./huh/memory
```

---

## Wire into Claude Code

Add to `.claude/settings.json` in any project:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Write|Edit|MultiEdit",
      "hooks": [{ "type": "command", "command": "crisp-hook", "args": ["claude-post-tool"], "timeout": 10 }]
    }],
    "Stop": [{
      "hooks": [{ "type": "command", "command": "crisp-hook", "args": ["claude-stop"], "timeout": 10 }]
    }],
    "SessionEnd": [{
      "hooks": [{ "type": "command", "command": "crisp-hook", "args": ["claude-session-end"], "timeout": 30 }]
    }],
    "PreCompact": [{
      "hooks": [{ "type": "command", "command": "crisp-hook", "args": ["claude-pre-compact"], "timeout": 30 }]
    }]
  }
}
```

---

## CLI usage

```bash
huh stats                     # layer counts, cache size
huh search "JWT validation"   # keyword search across all layers
huh reflect                   # manually trigger L0→L1→L2→L3 cascade
huh prune                     # remove decayed episodes
huh save "note" --permanent   # save a permanent note
```

Or type `/huh` in Claude Code (copy `commands/huh.md` from this repo to `~/.claude/commands/`).

---

## Storage layout

Everything lives in `~/.claude/memory/` — **global, not per-project**:

```
~/.claude/memory/
  layers/
    l0/   raw episodes (.md, 30-day decay)
    l1/   session summaries (.md, 180-day decay)
    l2/   topic clusters (.md, 2-year decay)
    l3/   life arcs (.md, permanent)
  cache/
    hashes.json       content-hash dedup index
    file_states.json  per-file change detection
    links.json        episode graph edges
  config/
    config.json
```

Episodes are plain markdown with YAML frontmatter — readable in any editor,
diff-friendly in git. SQLite-backed FTS is on the roadmap for scale.

---

## Architecture

```
lib/
  hooks.py      Claude Code hook handlers + payload translation
  store.py      IMemoryStore interface + FileStore implementation
  analyzer.py   Code symbol extractor (tree-sitter, regex fallback)
  reflector.py  L0→L1→L2→L3 consolidation pipeline
  retrieve.py   Multi-layer search + graph expansion + reranking
  prune.py      Ebbinghaus decay pruning
  cli.py        huh CLI entry point
  crisp_sense.py  standalone file analyser
```

The `IMemoryStore` interface makes the storage backend swappable — a `SQLiteStore`
can be dropped in without changing anything else.

---

## Episode format

```markdown
---
id: file_20260504_135959
layer: 0
timestamp: 2026-05-04T13:59:59Z
title: File change: auth.ts
source_type: file
source_path: /project/src/auth.ts
category: code
importance: 0.6
tags: [file_change, ts]
---

File changed: auth.ts
Change type: edit

## Diff
\`\`\`diff
@@ -12,6 +12,8 @@ ...
\`\`\`

## Code Elements
- `verifyToken()` (function)
- `AuthService` (class)
```
