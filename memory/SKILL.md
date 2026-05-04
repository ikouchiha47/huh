---
name: memory
version: "1.0.0"
description: "Episodic memory system with layered knowledge base (L0-L3) and storage-agnostic architecture"
author: "Crisp Engine"
license: MIT
user-invocable: true
disable-model-invocation: false
allowed-tools: [Bash, Read, Write, Edit, Task]
context:
  - type: shell
    command: "ls ~/.claude/memory/layers/l0/ 2>/dev/null | wc -l"
    description: "Count L0 episodes"
  - type: shell
    command: "python3 -c \"from lib.store import MemoryStore; s=MemoryStore('~/.claude/memory'); print(s.get_stats())\" 2>/dev/null || echo 'Memory not initialized'"
    description: "Get memory stats"
---

# Crisp Engine — Episodic Memory System

A **SOLID-compliant**, storage-agnostic episodic memory system for AI agents. Implements layered knowledge (L0→L1→L2→L3), automatic deduplication via content hashing, and 5-layer zoom retrieval.

## Architecture Principles

### SOLID Design
- **Single Responsibility**: Each class has one job (store, analyze, reflect, retrieve, prune)
- **Open/Closed**: Open for extension (new storage backends), closed for modification
- **Liskov Substitution**: Any `IMemoryStore` implementation is swappable
- **Interface Segregation**: Small, focused interfaces
- **Dependency Inversion**: Domain depends on abstractions, not concretions

### Storage Abstraction
The `IMemoryStore` interface abstracts all storage operations. Default implementation uses **MD files with YAML frontmatter** (human-readable, git-friendly). Can be swapped for SQLite, Notion, Obsidian, or any custom API without touching domain logic.

### Layered Knowledge Base
- **L0 — Raw Episodes**: Individual interactions (30-day half-life)
- **L1 — Session Summaries**: ~20 L0 episodes → summary (180-day half-life)
- **L2 — Topic Clusters**: Cross-session topics (2-year half-life)
- **L3 — Life-Arcs**: Long-term patterns (permanent)

### 5-Layer Zoom Retrieval
Query flow: L3 → L2 → L1 → L0 → Graph expansion. Composite reranking: vector×0.4 + recency×0.3 + importance×0.2 + access×0.1.

## Commands

### `/memory save` — Save Explicit Memory
```
/memory save "Learned that JWT algorithm must match key type (HS256 vs RS256)" --category bugfix --importance 0.9 --tags auth,jwt --permanent
```

**Options:**
- `--title` — Episode title
- `--category` — Category (bug, fix, decision, preference, etc.)
- `--importance` — 0.0 to 1.0 (default: 0.7)
- `--tags` — Space-separated tags
- `--permanent` — Mark as permanent (bypasses decay)

**Use when:** You learn something important, fix a bug, or want to remember a decision.

### `/memory search` — Search Memory
```
/memory search "authentication bug" --layer l0 --limit 20
```

**Options:**
- `--layer` — Filter by layer (l0, l1, l2, l3)
- `--limit` — Max results (default: 20)

**Use when:** Looking for past experiences, similar bugs, or related decisions.

### `/memory show` — Show Episode Details
```
/memory show ep_20260501_abc123
```

**Use when:** Inspecting a specific memory episode.

### `/memory forget` — Delete Episode
```
/memory forget ep_old_id
```

**Use when:** Removing incorrect or obsolete memories.

### `/memory list` — List Episodes
```
/memory list --layer l0
```

**Options:**
- `--layer` — Filter by layer

**Use when:** Browsing memory contents.

### `/memory stats` — Show Statistics
```
/memory stats
```

**Use when:** Checking memory health and size.

### `/memory reflect` — Run Consolidation
```
/memory reflect --batch-size 20
```

**Options:**
- `--batch-size` — L0 episodes per L1 batch (default: 20)

**Use when:** Manually triggering L0→L1→L2→L3 consolidation.

### `/memory prune` — Run Pruning
```
/memory prune
```

**What it does:**
1. Updates decay scores (Ebbinghaus forgetting curve)
2. Detects and resolves semantic conflicts
3. Archives low-value episodes (decay < 0.05)
4. Deletes ancient archives (>365 days)

**Use when:** Managing memory size and quality.

### `/memory export` — Export to JSON
```
/memory export --output /path/to/export.json
```

**Options:**
- `--output` — Output file path (default: timestamped in exports/)

**Use when:** Backing up or migrating memory.

## Auto-Triggers

The system automatically captures and processes memories via Claude Code hooks:

### SessionEnd
- **When:** Claude Code session ends
- **Action:** Creates checkpoint + runs consolidation if ≥20 L0 episodes
- **Config:** `.claude/settings.json` → `"hooks": {"SessionEnd": {...}}`

### Stop
- **When:** Claude finishes a turn
- **Action:** Analyzes for corrections/frustration/tool failures
- **Config:** `.claude/settings.json` → `"hooks": {"Stop": {...}}`

### FileChange
- **When:** File is written/edited
- **Action:** Captures diff, extracts code elements, stores as L0 episode
- **Config:** `.claude/settings.json` → `"hooks": {"FileChange": {...}}`

### ToolFailure
- **When:** Tool call errors
- **Action:** Records failure with high importance (0.8)
- **Config:** `.claude/settings.json` → `"hooks": {"ToolFailure": {...}}`

## Memory File Format

Episodes are stored as MD files with YAML frontmatter:

```markdown
---
id: ep_20260501_abc123
session_id: sess_20260501_xyz
layer: 0
timestamp: 2026-05-01T15:30:00Z
title: Fixed auth bug
content_hash: a1b2c3d4e5...
source_type: file
source_path: /project/src/auth.py
source_hash: f6e7d8c9...
tags: [bugfix, auth]
category: bug
importance: 0.85
frustration_score: 0.7
correction_applied: true
correction_delta: "Wrong JWT algorithm"
user_sentiment: negative
lesson: "Verify JWT algorithm matches key type"
access_count: 3
last_accessed: 2026-05-01T16:00:00Z
decay_score: 0.95
is_permanent: true
linked_ids: [ep_prev1, ep_prev2]
---

Detailed description of the interaction...
```

## Deduplication & Change Detection

### Content Hashing
- SHA256 of episode content → `content_hash`
- Hash cache maps `content_hash → episode_id`
- Duplicates update access count instead of creating new episodes

### File Change Detection
- SHA256 of source file → `source_hash`
- File state cache maps `file_path → last_hash`
- Unchanged files link to existing episodes (no spam)

## Implementation Details

### Directory Structure
```
~/.claude/memory/
  layers/
    l0/          # Raw episodes (1 file = 1 interaction)
    l1/          # Session summaries
    l2/          # Topic clusters
    l3/          # Life-arcs
  cache/
    hashes.json          # content_hash → episode_id
    file_states.json     # file_path → last_hash
    links.json           # A-MEM graph edges
  config/
    config.json          # Decay rates, thresholds
  exports/               # JSON dumps
```

### Core Modules
- **`store.py`** — `IMemoryStore` interface + `MDFileStore` implementation
- **`analyzer.py`** — Tree-sitter/regex code analysis (Python, JS, TS, Java, Go, Rust)
- **`reflector.py`** — L0→L1→L2→L3 consolidation
- **`retrieve.py`** — 5-layer zoom search
- **`prune.py`** — Ebbinghaus decay, conflict detection
- **`hooks.py`** — Claude Code event handlers
- **`cli.py`** — Command-line interface

### AI Agent Implementation (No Code)
An AI agent can implement this system **without writing Python**:
1. Read the `IMemoryStore` interface contract
2. Choose backend (Notion, Obsidian, Airtable, etc.)
3. Map methods to backend operations
4. Register via config: `"store_type": "notion"`

## Configuration

Edit `~/.claude/memory/config/config.json`:

```json
{
  "decay_half_life_days": {
    "l0": 30,
    "l1": 180,
    "l2": 730,
    "l3": 2190
  },
  "importance_threshold": 0.3,
  "similarity_threshold": 0.92,
  "reflection_interval": 20,
  "pii_scrubbing": true
}
```

## Hook Configuration

Edit `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionEnd": {
      "type": "command",
      "command": "memory",
      "args": ["auto-checkpoint"]
    },
    "Stop": {
      "type": "agent",
      "agent": "memory",
      "matcher": "correction|frustration"
    },
    "FileChange": {
      "type": "command",
      "command": "memory",
      "args": ["capture-file"]
    }
  }
}
```

## Success Metrics

- ✅ Zero setup: First session works without configuration
- ✅ <100ms retrieval time for typical queries (<1K episodes)
- ✅ <1s consolidation for 20 L0 → L1
- ✅ No context overflow (auto-limits to ~10K tokens)
- ✅ 90%+ dedup rate on repeated file reads
- ✅ Storage-agnostic: MD ↔ SQLite swap without domain changes
- ✅ AI agent can implement via config + no-code backend

## Examples

### Save a bug fix
```
/memory save "Fixed null pointer in user service - added null check before accessing profile" --category bugfix --importance 0.8 --tags null-safety,user-service --permanent
```

### Search for related issues
```
/memory search "null pointer" --layer l0 --limit 10
```

### Review session
```
/memory list --layer l0
/memory stats
```

### Consolidate memories
```
/memory reflect
```

### Clean up old memories
```
/memory prune
```

## Troubleshooting

**Memory not saving?**
- Check `~/.claude/memory/` exists and is writable
- Run `memory stats` to verify store is functional

**Search too slow?**
- Reduce `--limit` parameter
- Filter by `--layer` to narrow scope

**Too many duplicates?**
- Check `cache/hashes.json` for corruption
- Run `memory prune` to clean up

**Hooks not firing?**
- Verify `.claude/settings.json` has correct hook config
- Check Claude Code hook permissions

## License

MIT — Use freely in personal and commercial projects.

---

**Built with ❤️ for AI agents that remember.**