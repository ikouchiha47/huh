# AI Agent Episodic Memory Skill — Implementation Plan

## Research Summary

### The 4 Temporal Memory Types (CoALA Framework)
- **Working Memory** — volatile, current context window scratchpad
- **Episodic Memory** — timestamped specific events: what happened, when, who, outcome
- **Semantic Memory** — distilled facts/beliefs/preferences compressed from episodes
- **Procedural Memory** — learned action patterns, skill templates, tool-use sequences

Consolidation pipeline: episodic → semantic → procedural (raw → extracted → automated)

### The 5 Mechanism Families (arxiv 2603.07670)
- **Context-Resident Compression** — summarization, KV-cache, sliding window within context
- **Retrieval-Augmented Stores (RAS)** — vector + BM25 + graph retrieval from external DB
- **Reflective Self-Improvement** — agent periodically reviews history, generates summaries/insights
- **Hierarchical Virtual Context (HVC)** — MemGPT-style OS paging: L0 raw → L1 summaries → L2 clusters → L3 arcs
- **Policy-Learned Management** — RL-trained read/write/forget policies based on downstream task success

### Key Failure Modes
- [ ] Staleness — world changes, memory doesn't (addresses, preferences, env state)
- [ ] Memory Poisoning — adversarial injection of false persistent memories
- [ ] Hallucination Compounding — fabricated memory retrieved → used → creates more false memory
- [ ] Contradiction Accumulation — old + new conflicting facts both persist
- [ ] Context Overflow — too many retrieved memories bury signal in noise
- [ ] Retrieval Collapse — bad embeddings or wrong distance metric, relevant memory never surfaces
- [ ] Temporal Confusion — agent applies old lessons to wrong time context
- [ ] Scope Creep / Noise Accumulation — storing everything → signal-to-noise collapse

### What Data Goes Into Episodic Memory (Full Schema)
Every episode captures:
- **Content**: raw_input, reasoning_trace, tool_calls, raw_output, outcome
- **Behavioral Signals**: frustration_score, correction_applied, correction_delta, user_sentiment, retry_count, explicit_feedback
- **Causal Chain**: trigger_type, root_cause, impact, lesson
- **Context Snapshot**: active_task, emotional_state, expertise_level_inferred, recent_topics, environment (cwd/branch/language)
- **Memory Meta**: importance_score, access_count, decay_score, tags, layer (0-3), parent_id, permanent flag

### Pruning Strategy Stack
- **Write-time gate** — importance scoring + deduplication (cosine sim > 0.92 = skip) + PII scrub
- **Ebbinghaus decay** — `decay_score = e^(-t / half_life)` per layer (L0: 30d, L1: 180d, L2: 2yr, corrections: ∞)
- **Conflict detection** — find contradicting memories on write, timestamp-priority resolve
- **Access-based promotion/demotion** — accessed in 7d → boost; not accessed in 90d → archive
- **Consolidation** — every 20 episodes: reflection → L1 summary, accelerate L0 decay

### Key Breakthrough Papers
- CoALA (2309.02427) — 4-type taxonomy, foundational
- MemGPT (2310.08560) — hierarchical virtual context / OS paging model
- Memory for Autonomous LLM Agents (2603.07670) — 5 mechanism families
- MemOS (2505.22101) — memory as first-class OS resource with lifecycle
- MemMachine (2604.04853) — contextualized windowed retrieval (±3 neighbor expansion)
- A-MEM (Xu 2025) — Zettelkasten bidirectional typed links between episodes
- MemArchitect (2603.18330) — policy governance layer (pluggable rules before write)
- Mem0 (2504.19413) — production conflict detection + semantic fact merging

---

## Implementation Checklist

### Phase 0 — Design Decisions (discuss before building)
- [ ] How does a real user communicate signals (frustration, correction, preference)?
- [ ] How is the skill triggered — automatic hooks, explicit commands, or both?
- [ ] What is the minimal useful V1 vs the full vision?
- [ ] How does the skill integrate with Claude Code's existing memory system?
- [ ] Scope: per-project memory vs global user memory vs both?
- [ ] What happens on first run (cold start, bootstrapping)?
- [ ] How does the user *query* their own memory (inspect, audit, delete)?

### Phase 1 — Core Infrastructure
- [ ] Create `~/.claude/memory/` directory structure
- [ ] SQLite schema: episodes, episode_vecs (sqlite-vec), episode_fts (FTS5), episode_links, checkpoints, semantic_facts, procedures
- [ ] sqlite-vec extension setup + Python binding
- [ ] Embedding pipeline (local via sentence-transformers OR api-based)
- [ ] L0 episode write path with policy gate (importance scoring + dedup)
- [ ] Basic vector search retrieval (L0 only)
- [ ] Checkpoint write/read (task state snapshots)
- [ ] CLI tool: `memory write`, `memory search`, `memory checkpoint`

### Phase 2 — Intelligence Layer
- [ ] Behavioral signal extraction (frustration score heuristics, correction detection)
- [ ] Causal chain extraction (LLM call on episode to extract root_cause + lesson)
- [ ] FTS5 hybrid search (vector + BM25 combined score)
- [ ] Reflection loop — every 20 L0 episodes → generate L1 summary + extract semantic facts
- [ ] Ebbinghaus decay job (runs on session end)
- [ ] Access-frequency update (increment on retrieval)
- [ ] Conflict detection on write (semantic similarity vs existing facts)

### Phase 3 — Zoom Architecture
- [ ] L2 cluster generation (from L1 summaries per topic)
- [ ] L3 arc generation (user life-arc, long-run behavioral summary)
- [ ] 5-layer zoom retrieval: L3 → L2 → L1 → L0 → graph expansion
- [ ] A-MEM Zettelkasten link generation on write (typed: similar/caused/contradicts/corrected_by)
- [ ] MemMachine windowed expansion on retrieval (±3 neighbors in same session)
- [ ] Reranking formula: vector_sim*0.4 + recency*0.3 + importance*0.2 + access_freq*0.1

### Phase 4 — Production Hardening
- [ ] PII detection + scrubbing (regex + optional NER)
- [ ] Memory poisoning defense (provenance tracking, confidence scores per source)
- [ ] Staleness detection (time-sensitive tags auto-expire)
- [ ] Pruning job: decay update + archive low-score + hard delete ancient + orphan link cleanup
- [ ] User-facing audit: `memory list`, `memory inspect <id>`, `memory forget <id>`
- [ ] Multi-scope memory: per-project vs global user
- [ ] Export/import (JSON dump for backup/migration)

### Phase 5 — Advanced
- [ ] Procedural memory extraction from high-success episodes
- [ ] RL-based importance scoring (did this memory improve outcomes?)
- [ ] Multi-agent shared memory scope (team memory)
- [ ] Memory diff across time (how has X preference evolved?)
- [ ] Proactive memory surfacing (before user even asks, inject relevant past context)

---

## Technology Stack
```
sqlite3
  + sqlite-vec      (dense vector KNN, cosine distance)
  + FTS5            (sparse keyword / BM25)
  + json1           (JSON field queries)

Python:
  sentence-transformers  (local embeddings, no cost)
  OR anthropic/openai    (API embeddings, higher quality)

Optional:
  networkx               (in-memory graph traversal for A-MEM links)
```

## Directory Structure (target)
```
~/.claude/memory/
  global.db              # main SQLite database
  config.json            # thresholds, decay rates, embedding model choice
  checkpoints/           # task state snapshots
  exports/               # JSON dumps for backup

../huh/                  # the skill implementation repo
  memory/
    __init__.py
    schema.py            # DDL, migration
    embed.py             # embedding pipeline
    write.py             # write path + policy gate
    retrieve.py          # 5-layer zoom retrieval
    reflect.py           # reflection loop + consolidation
    prune.py             # decay + archival jobs
    checkpoint.py        # task state snapshots
    cli.py               # CLI entry point
  skill.py               # Claude Code skill entry point
  pyproject.toml
```

---

## Sources
- https://arxiv.org/abs/2309.02427 (CoALA)
- https://arxiv.org/abs/2310.08560 (MemGPT)
- https://arxiv.org/html/2603.07670v1 (5 mechanism families)
- https://arxiv.org/abs/2505.22101 (MemOS)
- https://arxiv.org/html/2604.04853v1 (MemMachine)
- https://arxiv.org/html/2603.18330 (MemArchitect)
- https://arxiv.org/html/2504.19413v1 (Mem0)
- https://github.com/asg017/sqlite-vec
- https://github.com/IAAR-Shanghai/Awesome-AI-Memory
