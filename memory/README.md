# Crisp Engine — Episodic Memory for AI Agents

Automatic, layered memory for Claude Code sessions. Every file you edit, every
correction you give, every tool you run — captured, summarised, and promoted
through four layers so future sessions carry what past ones learned.

```
Tool use / edit  →  L0 episode (raw diff + symbols, or a tool observation)
                    ↓ every ~20 episodes
                 L1 session summary
                    ↓ clustered by topic
                 L2 topic cluster   ← instincts also live here
                    ↓ promoted
                 L3 life arc (permanent)
```

Memory is **per-project by default**: each project gets its own store under
`~/.claude/memory/projects/<id>/` (auto-detected from the working directory / git
root). Work in project A stays in A. A separate **global** store
(`~/.claude/memory/`) is used when you're not inside a project, and is where
cross-project **instincts** graduate (see below).

---

## How it works

| Hook | Fires when | What gets stored |
|---|---|---|
| `PreToolUse` / `PostToolUse` | Any tool runs | A tool-use **observation** (instinct engine); PostToolUse also lazily indexes edited/read files → L0 |
| `Stop` | Claude finishes a turn | Distills observations into instincts; corrections/frustration → L0 |
| `PreCompact` | Context window fills | Last conversation turns → L0, then full cascade |
| `SessionEnd` | Session closes | Conversation transcript → L0, then full cascade |

The cascade (`L0→L1→L2→L3`) runs automatically at `PreCompact` and `SessionEnd`.
Each layer has a decay half-life: **L0 = 1 day, L1 = 7 days, L2 = 30 days, L3 = permanent**.
Reinforcement (re-seeing the same content/pattern) bumps access and resets decay.

### Continuous-learning instincts

Tool-use observations are distilled into **instincts** — confidence-scored behaviors
(an episode with `category="instinct"` at L2). They `reinforce` on recurrence,
`evolve` into emitted skills/commands/agents, and `promote` project→global once a
signature is seen in ≥2 projects. See `../skills/memory/instincts.md`.

### Semantic search (opt-in)

`huh search` is keyword/structured by default. `huh search --semantic` uses
embeddings — **user-triggered only**, never on the automatic path. The provider is
configurable (`embedding_provider`: `mock` default, or `ollama` with a configurable
model + API route). A persistent vector index (sqlite) is on the roadmap; today the
mock keeps the path exercised and `ollama` computes on the fly.

---

## Installation

```bash
git clone git@github.com:ikouchiha47/huh
uv tool install -e ./huh/memory   # editable: tracks the repo
```

This installs three commands into `~/.local/bin/`:

| Command | Maps to | Purpose |
|---|---|---|
| `huh` | `lib.cli:main` | CLI — search, reflect, stats, prune, `instinct …` |
| `crisp-hook` | `lib.hooks:main` | hook entry point wired into `.claude/settings.json` |
| `crisp-sense` | `lib.crisp_sense:main` | standalone file analyser |

For **fish**, ensure `~/.local/bin` is on PATH: `fish_add_path ~/.local/bin`.

The `/memory` skill lives in `../skills/memory/` (install via the repo `Makefile`'s
`make link`, or copy it to `~/.claude/skills/memory/`).

---

## Wire into Claude Code

See **`HOOKS_CONFIG.md`** for the full setup. Minimal passive learning — add to
`~/.claude/settings.json` (`async` so observers add no latency and never block a tool):

```json
{
  "hooks": {
    "PreToolUse":  [{ "matcher": "*", "hooks": [{ "type": "command", "command": "\"$HOME/.local/bin/crisp-hook\" claude-pre-tool",  "async": true, "timeout": 10 }] }],
    "PostToolUse": [{ "matcher": "*", "hooks": [{ "type": "command", "command": "\"$HOME/.local/bin/crisp-hook\" claude-post-tool", "async": true, "timeout": 10 }] }],
    "Stop":        [{ "hooks": [{ "type": "command", "command": "\"$HOME/.local/bin/crisp-hook\" claude-stop", "async": true, "timeout": 10 }] }]
  }
}
```

After editing settings, open `/hooks` once (or restart) so Claude Code reloads them.

---

## CLI usage

```bash
huh stats                       # layer counts, cache size
huh search "JWT validation"     # keyword search; add --semantic for embeddings
huh reflect                     # manually trigger L0→L1→L2→L3 cascade
huh prune                       # remove decayed episodes
huh save "note" --permanent     # save a permanent note
huh instinct list               # learned behaviors for this project
huh instinct evolve             # emit a skill from high-confidence instincts
```

In Claude Code the skill is **`/memory`** (subcommands route to the `huh` CLI).

---

## Storage layout

Per-project store (the default), with a global store at the same shape:

```
~/.claude/memory/
  projects/<id>/        per-project store (layers/, cache/, config/, observations/, evolved/)
  layers/               global store (used outside a project; promoted instincts)
    l0/  raw episodes (.md, 1-day half-life)
    l1/  session summaries (.md, 7-day)
    l2/  topic clusters + instincts (.md, 30-day)
    l3/  life arcs (.md, permanent)
  cache/
    hashes.json         content-hash dedup index
    file_states.json    per-file change detection
    links.json          episode graph edges
  config/config.json
  observations/         append-only tool-use buffers (instinct engine)
  evolved/              skills/commands/agents emitted by `instinct evolve`
```

Episodes are plain markdown with YAML frontmatter — readable in any editor,
diff-friendly in git. A SQLite vector index is on the roadmap for semantic scale.

---

## Architecture

```
lib/
  hooks.py       Claude Code hook handlers + payload translation
  store.py       IMemoryStore interface + MD FileStore (+ confidence, update_episode)
  instincts.py   continuous-learning: observe → distill → reinforce → evolve → promote
  embeddings.py  pluggable embedding providers (mock default, ollama optional)
  analyzer.py    code symbol extractor (tree-sitter, regex fallback)
  reflector.py   L0→L1→L2→L3 consolidation pipeline
  retrieve.py    multi-layer search + graph expansion + reranking
  prune.py       Ebbinghaus decay pruning
  cli.py         huh CLI entry point
  crisp_sense.py standalone file analyser
  project_memory.py  per-project store resolution
```

The `IMemoryStore` interface makes the storage backend swappable — a `SQLiteStore`
(and a vector index) can be dropped in without changing anything else.

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
