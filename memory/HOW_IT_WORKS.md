# Crisp Engine — Complete System Guide

> **Episodic Memory for AI Agents** — A SOLID-compliant, storage-agnostic implementation with PageIndex-inspired tree indexing and Windsurf-style auto-memory.

## 📁 Where Everything Is Stored

### Global Memory Store
```
~/.claude/memory/
  layers/
    l0/    → Raw episodes (1 file per interaction)
      ├─ ep_20260501_abc123.md
      ├─ ep_20260501_def456.md
      └─ ...
    l1/    → Session summaries
    l2/    → Topic clusters
    l3/    → Life-arcs
  cache/
    hashes.json          → {content_hash: episode_id}  (global dedup index)
    file_states.json     → {file_path: content_hash}   (change detection)
    links.json           → {episode_id: [{target, type, strength}]}
  config/
    config.json          → decay rates, thresholds, model configs
  exports/              → JSON dumps for backup/migration
```

**Key insight:** Memory is **global** across all projects. Episodes are tagged with `source_path` to identify which project they belong to. Cross-project learning emerges naturally (bug fix in Project A → similar bug in Project B is found via search).

**Per-project isolation:** Set `CLAUDE_MEMORY_PATH` environment variable per project if needed.

---

## 🔄 How Episodes Flow Through Layers

### L0: Raw Episodes (What Gets Stored Here?)

**Trigger conditions:**
1. User says something memorable: "remember that JWT bug"
2. File is edited (FileChange hook captures diff)
3. Tool succeeds/fails (ToolFailure hook)
4. User expresses frustration/correction (Stop hook)
5. Manual `/memory save` command

**Example:**
```json
{
  "id": "ep_001",
  "layer": 0,
  "timestamp": "2026-05-01T12:30:00Z",
  "title": "Fixed JWT algorithm bug",
  "content": "Changed HS256 to RS256 in auth.py because HS256 is symmetric...",
  "source_type": "file",
  "source_path": "/project/src/auth.py",
  "source_hash": "f6e7d8c9...",  ← SHA256 of file at capture
  "category": "bugfix",
  "importance": 0.85,
  "frustration_score": 0.7,
  "correction_applied": true,
  "correction_delta": "Was using HS256, changed to RS256",
  "lesson": "JWT algorithm must match key type",
  "code_elements": ["elem_001", "elem_002"],
  "access_count": 3,
  "decay_score": 0.95
}
```

**Stored in:** `~/.claude/memory/layers/l0/ep_20260501_abc123.md`

**Content:**
```markdown
---
id: ep_20260501_abc123
layer: 0
timestamp: 2026-05-01T12:30:00Z
title: Fixed JWT algorithm bug
source_type: file
source_path: /project/src/auth.py
source_hash: f6e7d8c9...
category: bugfix
importance: 0.85
frustration_score: 0.7
correction_applied: true
lesson: Verify JWT algorithm matches key type
access_count: 3
decay_score: 0.95
---

Changed HS256 to RS256 in auth.py because HS256 is symmetric...
```

---

### L1: Session Summaries (How Are They Made?)

**Trigger:** Every 20 L0 episodes from same session OR manual `/memory reflect`

**Process:**
```python
# 1. Collect all unsummarized L0 episodes from session
unsummarized = [ep for ep in l0_episodes if not ep.parent_id]
batch = unsummarized[:20]

# 2. Group by category
by_category = defaultdict(list)
for ep in batch:
    by_category[ep.category].append(ep)

# 3. Build summary
summary = ["# Session Summary", ""]
for category, episodes in by_category.items():
    summary.append(f"## {category.title()}")
    summary.append(f"- {len(episodes)} episodes")
    
    lessons = [ep.lesson for ep in episodes if ep.lesson]
    if lessons:
        summary.append("- Key lessons:")
        for lesson in lessons[:5]:
            summary.append(f"  • {lesson}")
    
    corrections = [ep for ep in episodes if ep.correction_applied]
    if corrections:
        summary.append(f"- Corrections: {len(corrections)}")

# 4. Create L1 episode
l1 = MemoryEpisode(
    layer=1,
    title=f"Summary: {', '.join(by_category.keys())}",
    content="\n".join(summary),
    category="summary",
    linked_ids=[ep.id for ep in batch],
    parent_id="",  # L1 has no parent (yet)
    importance=0.7,
    is_permanent=False  # Decays in 180 days
)

# 5. Link L0 → L1
for ep in batch:
    ep.parent_id = l1.id
    store._write_raw(ep)  # Update L0 file with parent link

store.save_episode(l1)  # Save L1
```

**Stored in:** `~/.claude/memory/layers/l1/l1_20260501_124552.md`

---

### L2: Topic Clusters (How Grouped?)

**Trigger:** ≥10 L1 summaries share a common topic

**Topic extraction:**
```python
# For each L1 summary:
# 1. Extract predominant category from L0s it contains
# 2. Use tag co-occurrence clustering
# 3. Or manual assignment

topics = defaultdict(list)
for l1 in all_l1_summaries:
    main_topic = infer_topic(l1)  # e.g., "authentication", "database", "api"
    topics[main_topic].append(l1)

for topic, summaries in topics.items():
    if len(summaries) >= 10:
        # Create L2 cluster
        cluster = MemoryEpisode(
            layer=2,
            title=f"Cluster: {topic.title()}",
            content=build_cluster_summary(summaries),
            category="cluster",
            tags=[topic, "cluster"],
            linked_ids=[s.id for s in summaries],
            importance=0.8,
            is_permanent=False  # Decays in 2 years
        )
        store.save_episode(cluster)
```

**Example topics:**
- `authentication`
- `database_schema`
- `api_design`
- `error_handling`
- `deployment`

---

### L3: Life-Arcs (Meta-Patterns)

**Trigger:** ≥3 L2 clusters exist

**Process:**
```python
l2_clusters = store.list_episodes(layer=2)[:3]

arc_content = f"""# Life Arc: {arc_name}

**Clusters:** {len(l2_clusters)}

## Overview
{for each cluster: summarize its evolution}

## Meta-Lessons
- Skill progression: beginner → intermediate → advanced
- Recurring challenges: {common_patterns}
- Decision patterns: {decision_style}
"""

l3 = MemoryEpisode(
    layer=3,
    title=f"Arc: {arc_name}",
    content=arc_content,
    category="arc",
    tags=["arc", "meta", "pattern"],
    linked_ids=[c.id for c in l2_clusters],
    importance=1.0,
    is_permanent=True  # Never decays
)
```

**Examples:**
- "Security-First Mindset"
- "Microservices Migration Journey"
- "Team Leadership Evolution"

---

## 📊 Diffs and Changes: Storage Locations

### What Gets Stored Where?

| Event | Layer | File Location | What's Stored |
|-------|-------|--------------|---------------|
| File edit | L0 | `layers/l0/ep_YYYYMMDD_HHMMSS.md` | Git diff + code elements affected |
| Function extracted | L0 | `layers/l0/ep_....md` | Function signature, docstring, body hash |
| Bug reported | L0 | `layers/l0/ep_....md` | User's message + analysis |
| Correction | L0 | `layers/l0/ep_....md` | "That's wrong" + correction delta |
| Session summary | L1 | `layers/l1/l1_....md` | Condensed 20 L0s into paragraphs |
| Topic cluster | L2 | `layers/l2/l2_....md` | Evolution timeline across sessions |
| Life arc | L3 | `layers/l3/l3_....md` | Meta-patterns, skill trajectory |
| Code element only | L0 | `layers/l0/ep_....md` | Function/class extracted (no user interaction) |
| Duplicate detection | N/A | `cache/hashes.json` | Maps `content_hash → episode_id` |
| File unchanged | N/A | `cache/file_states.json` | Maps `file_path → last_hash` |
| Graph link | N/A | `cache/links.json` | Episode graph edges |

---

### Diff Storage Format

**Full diff in episode content:**
```markdown
## File Changed: auth.py

```diff
@@ -10,7 +10,7 @@
-def verify_token(token):
+def verify_token(token: str) -> bool:
     """Verify JWT."""
-    return jwt.decode(token, HS256)
+    return jwt.decode(token, RS256(public_key))
```

## Code Elements Modified
- `verify_token()`: signature changed (added type hints)
- Complexity: 2 → 3 (increased)

**Detection:** FileChange hook compares `source_hash` (old vs new) to compute diff automatically via `git diff` or direct comparison.

---

## 🔍 Retrieval: Step-by-Step Walkthrough

**Query:** "How do I fix JWT validation?"

### Step 1: L3 (Life-Arcs) — Highest Abstraction
```
Search L3 for "JWT", "validation", "auth"
Results: 
  × No arc directly about JWT validation
  ✓ Found "Security-First Mindset" arc (score: 0.65)
    → Contains cluster about "Authentication System"
    → Continue to L2
```

### Step 2: L2 (Topic Clusters)
```
Search L2 for "JWT", "validation"
Results:
  ✓ "Authentication System" cluster (score: 0.88)
    → Summary mentions: "JWT algorithm bugs", "token validation"
    → Inject this cluster summary into context
    → Continue to L1
```

### Step 3: L1 (Session Summaries)
```
Search L1 within Authentication cluster
Results:
  1. "Fixed JWT algorithm mismatch" (score: 0.92)
     - Summary: Changed from HS256 to RS256, added validation
  2. "Implemented token refresh" (score: 0.74)
     - Related but not directly about validation
  3. "Added rate limiting to login" (score: 0.51)
     - Lower priority

→ Inject top 2 summaries
→ Continue to L0
```

### Step 4: L0 (Raw Episodes)
```
Search L0 for "JWT validation"
Results (keyword match):
  1. ep_123: "HS256 → RS256" (score: 4.2) ← CORRECTION episode
  2. ep_456: "Added validate_token()" (score: 3.8)
  3. ep_789: "Token expiration check" (score: 2.1)
  4. ep_321: "User reported bug" (score: 1.5)

Apply boosts:
  - ep_123 ×2 (correction episode)
  - ep_456 ×1.2 (high importance 0.9)
  - All: ×1.0-1.3 (recency decay)

Filter: decay_score > 0.1 (ep_789 decayed to 0.08 → removed)

Windowed expansion: add ±3 neighbors (ep_122, ep_124, ep_455, ep_457)

Final L0 set: 8 episodes
```

### Step 5: Graph Expansion (A-MEM)
```
For each of 8 episodes, follow links:
  ep_123 linked to:
    → ep_456 (similar, strength 0.85)  ✓ already included
    → ep_322 (caused, strength 0.72)   ✓ add
    → ep_124 (related, strength 0.65)  ✗ too weak (threshold 0.7)

  ep_456 linked to:
    → ep_555 (corrected_by, strength 0.90) ✓ add

Added 2 more episodes via graph: ep_322, ep_555

Total before rerank: 10 episodes
```

### Step 6: Composite Rerank
```python
for episode in all_candidates:
    # Compute factors
    recency = exp(-days_since / 30)
    access_factor = min(2.0, 1.0 + 0.1 * access_count)
    
    composite = (
        base_score * 0.4 +         # keyword/vector similarity
        recency * 0.3 * 10 +       # scaled to 0-3
        importance * 0.2 * 10 +    # scaled to 0-2
        min(1.0, access_count/10) * 0.1 * 10  # scaled to 0-1
    ) * access_factor
    
    if correction_applied:
        composite *= 2.0
    
    episode.final_score = composite

Sorted results:
  1. ep_123: 4.2×2.0 = 8.4  (correction + keyword match)
  2. ep_456: 3.8×1.2 = 4.6  (high importance)
  3. ep_322: 3.1×1.0 = 3.1  (graph link)
  4. ep_555: 2.9×0.9 = 2.6  (weaker link)
  ...
```

### Step 7: Context Assembly
```
Take top-10 episodes, format:
--- Episode (Layer 0, Score: 8.40) ---
Title: Fixed JWT algorithm mismatch
Category: bugfix
Importance: 0.85
⚠️ CORRECTION: Was using HS256, changed to RS256

Content:
  Changed HS256 to RS256 in auth.py because HS256 is symmetric...
  Lesson: Verify JWT algorithm matches key type

--- Episode (Layer 1, Score: 4.60) ---
Title: Summary: Bug Fixes, Auth
...
```

**Total tokens:** ~2,400 (well under 10K limit)

---

## 🗂️ Layer Impact Matrix

| Layer | Stores | Lifespan | Trigger | What's Captured |
|-------|--------|----------|---------|-----------------|
| **L0** | Individual interactions | 30 days | Every meaningful event | Diff + code elements + user sentiment + correction flags |
| **L1** | Session summaries | 180 days | 20 L0 episodes or manual | Condensed lessons, top code elements, key decisions |
| **L2** | Topic clusters | 2 years | 10 L1 summaries on same topic | Evolution timeline, pattern synthesis |
| **L3** | Life-arcs | Permanent | 3 L2 clusters | Meta-learning, skill trajectory, preference evolution |

---

## 🔗 File Change Diffs at Function/Class Level

When a file is edited, **which diffs get stored**?

### At L0 Episode Level:
```markdown
## Diff (whole file)
@@ -10,7 +10,7 @@
-def verify_token(token):
+def verify_token(token: str) -> bool:
     # ...

## Code Elements Modified
elem_001 (verify_token):
  - Changed: signature (added type hints)
  - Complexity: 2 → 3
  - Dependencies: unchanged
```

**Granularity:** Whole-file diff (git-style), with annotations on which functions/classes were affected.

**Storage location:** `layers/l0/ep_....md` (one file per edit)

---

## 🔄 Change Propagation Across Layers

### Example: JWT Bug Fix Journey

**Step 1 — L0 (Raw):**
```
ep_001: "User reported: 'JWT validation fails'"
  → source: chat message
  → frustration_score: 0.6
  → layer: 0

ep_002: "Edited auth.py: changed HS256→RS256"
  → source: file edit
  → diff: 1 line changed
  → code_elements: [verify_token]
  → layer: 0

ep_003: "User: 'That fixed it, thanks'"
  → source: chat message
  → correction_applied: false
  → lesson: "Use RS256 for asymmetric keys"
  → layer: 0
```

**After 20 L0 episodes → L1 Summary:**
```
l1_001: "Session Summary: Authentication Bug Fixes"
  → Links: ep_001, ep_002, ep_003, ... (20 total)
  → Extracted: "Lesson: JWT algorithm must match key type"
  → layer: 1
```

**After 10 L1 summaries on auth → L2 Cluster:**
```
l2_001: "Cluster: Authentication System"
  → Evolution:
    - Mar 15: Basic JWT login
    - Apr 02: Added refresh tokens (ep_045)
    - May 01: Fixed algorithm bug (ep_002 cluster)
    → Recurring: Always validate algorithm before decoding
  → layer: 2
```

**After 3 L2 clusters → L3 Arc:**
```
l3_001: "Arc: Security-First Mindset"
  → Includes: Authentication, Rate Limiting, Audit Logging clusters
  → Meta-lesson: "User consistently prioritizes security over convenience"
  → layer: 3 (permanent)
```

---

## 🤖 Auto-Capture Rules (When Is Something Saved?)

### Automatic Triggers

| Trigger | Event | What Captured | Layer |
|---------|-------|--------------|-------|
| `SessionEnd` | Claude session closes | Checkpoint summary (if ≥20 L0) | L0 |
| `Stop` | Claude finishes turn | Corrections, frustration signals | L0 |
| `FileChange` | File write/edit | Full diff + code elements | L0 |
| `ToolFailure` | Tool errors | Error message + context | L0 |
| `PreToolUse` (optional) | Before tool call | Cache tree if fresh | N/A |

### Manual Triggers

```bash
/memory save "Remember to use RS256 not HS256" --permanent
/memory reflect  # Consolidate L0→L1→L2→L3
/memory prune    # Clean up old memories
```

---

## 🧠 Intelligent Filtering: What Gets Discarded?

### Policy Gate (Before Save)

```python
def should_save(episode_content, metadata) -> bool:
    # 1. Importance threshold
    if importance < 0.3 and not is_correction(episode):
        return False  # Too trivial
    
    # 2. PII detection (scrub emails/keys/passwords)
    if contains_pii(episode_content):
        return False  # Privacy risk
    
    # 3. Duplicate check (content hash)
    if content_hash in hash_cache:
        return False  # Already saved
    
    # 4. File unchanged
    if source_type == "file" and file_hash == file_states[path]:
        return False  # No actual change
    
    # 5. Too frequent from same file?
    if recent_changes_from(file_path, minutes=5):
        return False  # Spam prevention
    
    return True
```

**Result:** Only ~30% of raw interactions become L0 episodes. Rest are noise.

---

## 📈 Project Boundaries & Cross-Project Learning

### How Crisp Engine Identifies Projects

```yaml
Episode metadata:
  source_path: /Users/you/dev/ideas/wristturn/wristturn.ino
                └─────┬──────┘ └────┬────┘ └─┬─┘
                  project root   subdir   file
  session_id: sess_20260501_xyz
```

**Project root detection:**
- Git root (`.git/` exists)
- Markers: `package.json`, `Cargo.toml`, `.claude/`
- User config: `~/.claude/memory/projects/`

**Cross-project episodes:**
```bash
# Project A: Fixed JWT bug
/memory save "HS256 → RS256 fix" --source /projA/auth.py

# Later, Project B encounters similar bug
/memory search "JWT validation"
# → Finds Project A's episode! (cross-project learning)
```

---

## 🗄️ Hash Cache & File State: The Dedup Engines

### hash_cache.json
```json
{
  "a1b2c3d4e5...": "ep_20260501_abc123",
  "f6e7d8c9a1...": "ep_20260501_def456"
}
```
**Meaning:** Content with SHA256 `a1b2c3...` is stored as episode `ep_abc123`.

**On save:**
```
1. Compute content_hash = SHA256(new_episode.content)
2. Lookup hash_cache[content_hash]
   If exists:
     - Increment existing.access_count
     - Return False (duplicate)
   Else:
     - Save new episode
     - hash_cache[content_hash] = new_episode.id
```

---

### file_states.json
```json
{
  "/project/src/auth.py": "f6e7d8c9a1b2...",
  "/project/README.md": "a1b2c3d4e5..."
}
```
**Meaning:** Last time we saw `/project/src/auth.py`, its SHA256 was `f6e7d8...`.

**On file edit:**
```
1. Read current file → hash_current = SHA256(file)
2. Lookup file_states[file_path] → hash_last
   If hash_current == hash_last:
     - File unchanged → find existing episode, increment access
     - Return False (skip)
   Else:
     - File changed → create new episode with new diff
     - file_states[file_path] = hash_current
```

---

## 🎯 What the System Actually Does (Summary)

**Crisp Engine is:**

1. **A change detector** — Notices when files change or important events occur
2. **A deduplicator** — Never stores the same thing twice (content hash + file hash)
3. **A summarizer** — Condenses 20 interactions → 1 paragraph (L0→L1)
4. **A clusterer** — Groups related sessions into topics (L1→L2)
5. **A pattern finder** — Synthesizes meta-learning from topics (L2→L3)
6. **A retriever** — Multi-layer search with graph expansion
7. **A pruning gardener** — Forgets old/low-value memories, keeps important ones

**Crisp Engine is NOT:**

- ❌ A vector database (uses keywords + optional embeddings)
- ❌ A fine-tuned model (storage-agnostic, can swap backends)
- ❌ A cloud service (runs locally)
- ❌ Real-time streaming (batch consolidation)

---

## 🏗️ Architecture Decisions

### Why Global Store?
```
Pros:
  ✓ Cross-project learning (bug in A helps B)
  ✓ One config to rule them all
  ✓ Simpler (no per-project setup)

Cons:
  ✗ Projects can't have isolated memories
  ✗ Large codebases might be overwhelmed by others

Solution: Use CLAUDE_MEMORY_PATH per-project if needed.
```

### Why MD Files?
```
Pros:
  ✓ Human-readable (open in editor)
  ✓ Git-friendly (diffs are readable)
  ✓ No database setup
  ✓ Easy backup/export

Cons:
  ✗ Slower search than SQLite
  ✗ No ACID transactions
  ✗ Doesn't scale to millions of episodes

Solution: SQLiteStore for large deployments (swap via IMemoryStore).
```

### Why Layers L0→L3?
```
L0: Detailed audit trail (forgotten quickly)
L1: Session takeaways (medium-term)
L2: Topic expertise (long-term)
L3: Career-long wisdom (permanent)

Ebbinghaus decay: each layer has different half-life.
```

---

## 🔧 Configuration Reference

`~/.claude/memory/config/config.json`:

```json
{
  "decay_half_life_days": {
    "l0": 30,      // 1 month
    "l1": 180,     // 6 months
    "l2": 730,     // 2 years
    "l3": 2190     // 6 years (practically permanent)
  },
  "importance_threshold": 0.3,    // Below this: discard
  "similarity_threshold": 0.92,   // Jaccard for conflict detection
  "reflection_interval": 20,      // L0s per L1 batch
  "embedding_model": "all-MiniLM-L6-v2",
  "use_local_embeddings": true,
  "pii_scrubbing": true
}
```

---

## 🎓 Quick Start

```bash
# Install the CLI once (exposes `huh`, `crisp-hook`, `crisp-sense` on PATH)
cd /path/to/huh/memory && uv tool install -e .

# Use it from any project (memory auto-scopes to the project)
cd /your/project
huh stats

huh save "Fixed race condition in auth" \
  --category bugfix --importance 0.9 --tags concurrency,auth

huh search "auth bug" --limit 10   # keyword; add --semantic for embeddings
huh reflect                         # consolidate L0->L1->L2->L3
huh prune                           # decay/archive
huh instinct list                   # continuous-learning instincts
```

---

## 📚 Further Reading

- `IMPLEMENTATION_SUMMARY.md` — What was built
- `VALIDATION_AND_INTEGRATION.md` — PageIndex + Windsurf integration ideas
- `../ai-memory-skill.md` — Research background (A-MEM, MemGPT, CoALA)
- `HOOKS_CONFIG.md` — wiring `crisp-hook` into Claude Code
- `../skills/memory/instincts.md` — the continuous-learning instinct engine

---

**Crisp Engine v1.0** — SOLID design, production-ready, extensible.
