# Crisp Engine Architecture — How It Actually Works

## Directory Structure

```
~/.claude/memory/              # GLOBAL — all projects share this
  layers/
    l0/                         # Raw episodes (all projects mixed)
      ep_20260501_proj1_auth.md
      ep_20260501_proj2_ui.md
    l1/                         # Session summaries
    l2/                         # Topic clusters
    l3/                         # Life-arcs
  cache/
    hashes.json                # content_hash → episode_id (global dedup)
    file_states.json           # file_path → last_hash (per-file tracking)
    links.json                 # A-MEM graph (global across all projects)
  config/
    config.json                # Settings (global)
  exports/

PROJECT_ROOT/.claude/          # PER-PROJECT config
  settings.json                # Hook configuration (per-project)
  commands/
  skills/
```

**Key Point:** Memory is **global** across all projects, but episodes are tagged with `source_path` and `session_id` to identify which project they belong to.

---

## Data Flow: How Episodes Are Created

### 1. Trigger Sources (4 Ways)

```
┌─────────────────┐
│  User Action    │ → "remember that JWT bug" → /memory save
├─────────────────┤
│  Claude Hook    │ → SessionEnd → checkpoint
│  (Auto)         │ → FileChange → diff capture
│                 │ → Stop → correction detection
├─────────────────┤
│  Code Analysis  │ → Analyzer extracts functions/classes
│  (Passive)      │ → Creates code element episodes
└─────────────────┘
```

### 2. Episode Creation Pipeline

```
Raw Input
    ↓
[Policy Gate]
    ├─ Importance scoring (heuristic or LLM)
    ├─ PII detection (scrub emails/keys)
    ├─ If importance < 0.3 AND no correction → DISCARD
    ↓
[Content Hash]
    ├─ SHA256(content) → content_hash
    ├─ Check hash_cache[content_hash]
    ├─ If exists → UPDATE existing (access_count++)
    └─ Return early (no new episode)
    ↓
[File State Check] (if source_type=file)
    ├─ Get file_path → file_states[file_path]
    ├─ Compute current file hash
    ├─ If last_hash == current_hash → LINK to existing episode
    └─ Return early (no new episode)
    ↓
[Write L0 Episode]
    ├─ Extract code elements (tree-sitter or regex)
    ├─ Compute embeddings (optional)
    ├─ Write to layers/l0/{id}.md
    ├─ Update hash_cache[content_hash] = id
    └─ Update file_states[file_path] = hash
    ↓
[Generate Links] (A-MEM)
    ├─ Find top-5 similar L0 episodes (Jaccard/keyword)
    ├─ Infer link_type: similar/caused/contradicts/corrected_by
    └─ store.add_link(source, target, type, strength)
    ↓
[Reflection Trigger?]
    ├─ If L0_count % 20 == 0 → Create L1 summary
    ├─ Extract lessons → embed in L1
    └─ Mark L0.parent_id = L1.id
    ↓
DONE
```

---

## Layer Semantics: What Goes Where

### L0 — Raw Episodes (30-day half-life)
**Granularity:** Single interaction or file change

**Captures:**
| Source | What's stored | Example |
|--------|--------------|---------|
| User says "fix bug" | Conversation snippet + analysis | "User reported null pointer in auth.py" |
| File saved | Diff + code elements | Changed lines, affected functions |
| Tool output | Success/failure + context | `git status` output |
| Manual save | User's explicit memory | "Remember: use RS256 not HS256" |
| Correction detected | User said "no/wrong" | "That's incorrect" → correction episode |

**Fields:**
- `content`: Full text of interaction
- `source_type`: file/chat/tool/manual
- `source_path`: `/path/to/file.py` (if applicable)
- `source_hash`: SHA256 of file at time of capture
- `code_elements`: List of extracted function/class IDs
- `frustration_score`: 0.0-1.0 if user expressed frustration
- `correction_applied`: True if user corrected Claude
- `trigger_type`: user_request/error_recovery/reaction/etc.

---

### L1 — Session Summaries (180-day half-life)
**Granularity:** ~20 L0 episodes from same session

**Generated when:**
- SessionEnd hook fires AND ≥20 L0 episodes in session
- Manual `/memory reflect` command
- Consolidation job runs

**Content:**
```markdown
# Session Summary

**Generated from 23 episodes**
**Date range:** 2026-05-01 to 2026-05-01

## Bug Fixes
- Episodes: 8
- Key lessons:
  - Verify JWT algorithm matches key type
  - Always validate token before parsing
- Corrections applied: 2

## Code Elements Analyzed
- `validate_token()` in auth.py
- `verify_jwt()` in middleware.py

---

Linked episodes: ep_001, ep_002, ..., ep_020
```

**Purpose:** Condense 20+ raw interactions into 1-2 paragraph summary. L0 episodes link to L1 via `parent_id`.

---

### L2 — Topic Clusters (2-year half-life)
**Granularity:** Cross-session topic grouping

**Generated when:**
- ≥10 L1 summaries share a common category/tag
- Manual promotion

**Example:** All "auth" related sessions cluster into "Authentication System"

**Content:**
```markdown
# Cluster: Authentication System

**12 session summaries** spanning 2026-03 to 2026-05

## Evolution
- **2026-03-15**: Implemented basic JWT login
- **2026-04-02**: Added refresh tokens
- **2026-05-01**: Fixed algorithm mismatch bug

## Recurring Patterns
- Always validate before parsing
- Use RS256 for production, HS256 for dev
- Store JWT ID in Redis for revocation
```

**Purpose:** Track topic evolution over time. L1 summaries link to L2 via `parent_id`/`linked_ids`.

---

### L3 — Life-Arcs (Permanent)
**Granularity:** Long-term behavioral patterns

**Generated when:**
- ≥3 L2 clusters exist
- Manual creation

**Example:** "Backend Development Style", "Security-First Mindset", "API Design Evolution"

**Content:**
```markdown
# Life Arc: Security-First Mindset

**5 topic clusters**: Auth → Rate Limiting → Input Validation → Audit Logging → Encryption

## Meta-Lessons
- Pattern: User reports bugs → I add validation → similar bugs disappear
- Preference: Explicit checks over implicit assumptions
- Growth: Started with basic auth, now using zero-trust patterns
```

**Purpose:** Capture meta-learning, preference evolution, skill development trajectory.

---

## Change Detection & Deduplication

### Content Hashing (Episode-level)
```python
# Every episode gets SHA256 of its content
content = "Fixed JWT bug by changing HS256 to RS256"
content_hash = sha256(content)
# → "a1b2c3d4..."

# hash_cache.json maps:
#   "a1b2c3d4..." → "ep_20260501_abc123"

# On save:
if content_hash in hash_cache:
    existing_id = hash_cache[content_hash]
    existing = get_episode(existing_id)
    existing.access_count += 1  # Just update access
    return False  # Duplicate, not saved
```

**Result:** Identical content → same episode ID reused. No duplicates.

---

### File State Tracking (File-level)
```python
# file_states.json maps:
#   "/project/src/auth.py" → "f6e7d8c9..."  (last seen hash)

# On file change:
current_hash = sha256(read(file_path))
last_hash = file_states.get(file_path)

if last_hash == current_hash:
    # File unchanged! Link to existing episode
    existing_id = find_episode_for_file(file_path)
    if existing_id:
        increment_access(existing_id)
        return False  # Skip write
else:
    # File changed → create new episode
    file_states[file_path] = current_hash
    create_new_episode()
```

**Result:** Reading same file 100× → only 1 episode (first capture). Subsequent reads just increment access count.

---

## Code Analysis: What Gets Extracted

### Tree-sitter (Optional, Preferred)
```python
# Full AST parsing
import tree_sitter
import tree_sitter_python as tspython

# Parse file → AST
tree = parser.parse(bytes(content, "utf8"))
root = tree.root_node

# Extract: functions, classes, methods, imports, variables
# Accurate even with complex syntax, decorators, generics
```

**Currently:** Regex-based (no external deps). Sufficient for Phase 1.

---

### Code Element Extraction

**Input:** `src/auth.py`
```python
def validate_token(token: str) -> bool:
    """Validates JWT signature."""
    # Implementation...
    return True

class JWTManager:
    def __init__(self, secret: str):
        self.secret = secret
```

**Extracted elements:**
```yaml
code_elements:
  - id: elem_1
    name: validate_token
    type: function
    language: python
    file_path: /src/auth.py
    start_line: 1
    end_line: 5
    signature: "def validate_token(token: str) -> bool"
    docstring: "Validates JWT signature."
    body: |
      def validate_token(token: str) -> bool:
          # Implementation...
          return True
    hash: "e3b0c..."          # SHA256 of body
    complexity: 2
    dependencies: ["jwt", "redis"]
    
  - id: elem_2
    name: JWTManager
    type: class
    file_path: /src/auth.py
    start_line: 7
    end_line: 12
    signature: "class JWTManager"
    body: |
      class JWTManager:
          def __init__(self, secret: str):
              self.secret = secret
    ...
```

**Stored in episode:**
```yaml
context_snapshot:
  code_elements:
    - elem_1
    - elem_2
  changed_files:
    /src/auth.py: "f6e7d8c..."
```

---

## Retrieval: 5-Layer Zoom

### Query Flow

```
User: "How do I fix JWT validation?"

Step 1: L3 Search (Life-Arcs)
  → Query: "JWT validation"
  → Results: 0 arcs match
  → Continue to L2

Step 2: L2 Search (Topic Clusters)
  → Query: "JWT validation"
  → Match: "Authentication System" cluster (score: 0.82)
  → Inject cluster context
  → Continue to L1

Step 3: L1 Search (Session Summaries)
  → Query: "JWT validation"
  → Top summaries:
      • "Fixed JWT algorithm bug" (score: 0.91)
      • "Added token validation" (score: 0.87)
  → Inject summaries
  → Continue to L0

Step 4: L0 Search (Raw Episodes)
  → Keyword search across all L0
  → Top episodes:
      ep_123: "Changed HS256 → RS256" (score: 4.2)
      ep_456: "Added validate_token()" (score: 3.8)
  → Filter: decay_score > 0.1
  → Boost: correction episodes ×2
  → Windowed expansion: ±3 neighbor episodes
  → Results: 15 episodes

Step 5: Graph Expansion (A-MEM Links)
  → For each retrieved episode:
    → Follow `linked_ids` where strength > 0.7
    → Add causally-related episodes
  → Results: +8 linked episodes

Step 6: Composite Reranking
  score = (vector_sim × 0.4) +
          (recency × 0.3) +
          (importance × 0.2) +
          (access_freq × 0.1)

  Where:
  - vector_sim: keyword match score (or embedding cosine)
  - recency: exp(-days_since / 30)
  - importance: episode.importance (0-1)
  - access_freq: min(2.0, 1.0 + 0.1 × access_count)

Step 7: Context Injection
  → Take top-10 episodes
  → Truncate to 10K tokens
  → Inject into Claude's context window
```

---

## Diffs and Changes: Where Are They Stored?

### File Change Episode Structure

When a file is edited:

```python
# Hook: FileChange (PostToolUse on Write/Edit)
event_data = {
    "file_path": "/project/src/auth.py",
    "change_type": "edit",
    "diff": "@@ -10,7 +10,7 @@\n-def verify(token):\n+def verify(token: str) -> bool:",
    "session_id": "sess_123"
}

# Handler creates episode:
episode = MemoryEpisode(
    id="file_20260501_124552",
    session_id="sess_123",
    timestamp="2026-05-01T12:45:52Z",
    layer=0,
    title="File change: auth.py",
    content="## File Change\n\n**File:** auth.py\n\n```diff\n{diff}\n```\n\n## Code Elements Affected\n- `verify_token()` (modified)",
    source_type="file",
    source_path="/project/src/auth.py",
    source_hash="f6e7d8c9a1b2...",  # SHA256 of NEW file content
    category="code",
    importance=0.6,
    tags=["file_change", "modified", "python"],
    context_snapshot={
        "change_type": "edit",
        "diff_size": 157,
        "code_elements": ["elem_001"],
        "lines_changed": 1
    }
)
```

**Storage location:** `~/.claude/memory/layers/l0/file_20260501_124552.md`

**Dedup logic:** If the same diff is seen again (same content_hash), it's a duplicate → access count increments, no new file created.

---

## Impact Layers: What Gets Stored at Each Level?

### Impact Assessment (Automatic)

Each episode gets an `importance` score computed by:

```python
def compute_importance(episode) -> float:
    score = 0.5  # base
    
    # Boost for corrections
    if episode.correction_applied:
        score += 0.4
    
    # Boost for frustration (negative learning)
    if episode.frustration_score > 0.5:
        score += 0.2
    
    # Boost for lessons learned
    if episode.lesson:
        score += 0.3
    
    # Boost for code changes (lines added/removed)
    if episode.context_snapshot.get("diff_size", 0) > 0:
        score += 0.2
    
    # Boost for high complexity changes
    if episode.context_snapshot.get("complexity", 0) > 5:
        score += 0.1
    
    return min(1.0, score)
```

**Impact tiers:**
- **High (0.8-1.0):** Corrections, lessons, major refactors
- **Medium (0.5-0.7):** Regular bug fixes, feature additions
- **Low (0.3-0.4):** Minor edits, documentation
- **Discarded (<0.3):** Trivial changes, no learning value

---

## Changing Layers: Promotion & Demotion

### L0 → L1 Promotion

**Trigger:** `L0_count % 20 == 0` (every 20 episodes) OR manual `/memory reflect`

**Process:**
```python
def consolidate_to_l1(l0_batch: List[MemoryEpisode]) -> MemoryEpisode:
    # Batch size: 20 L0 episodes (same session_id)
    batch = l0_batch[:20]
    
    # Group by category
    categories = defaultdict(list)
    for ep in batch:
        categories[ep.category or "uncategorized"].append(ep)
    
    # Build summary content
    summary_lines = ["# Session Summary", ""]
    for category, eps in categories.items():
        lessons = [ep.lesson for ep in eps if ep.lesson]
        summary_lines.append(f"## {category.title()}")
        summary_lines.append(f"- Episodes: {len(eps)}")
        if lessons:
            summary_lines.append("- Key lessons:")
            for lesson in lessons[:5]:
                summary_lines.append(f"  • {lesson}")
    
    # Create L1 episode
    l1 = MemoryEpisode(
        id=f"l1_{timestamp}",
        layer=1,
        title=f"Summary: {', '.join(categories.keys())}",
        content="\n".join(summary_lines),
        category="summary",
        importance=0.7,
        linked_ids=[ep.id for ep in batch],
        is_permanent=False,  # L1 decays in 180 days
    )
    
    # Link back
    for ep in batch:
        ep.parent_id = l1.id
        store._write_raw(ep)  # Update L0 with parent link
    
    return l1
```

**Result:** 20 L0 episodes → 1 L1 summary. Original L0 episodes kept (not deleted), just linked.

---

### L1 → L2 Promotion

**Trigger:** ≥10 L1 summaries with common topic

**Process:**
```python
# Group L1 summaries by common tags/categories
clusters = defaultdict(list)
for l1 in all_l1_summaries:
    main_category = l1.context_snapshot.get("categories", ["general"])[0]
    clusters[main_category].append(l1)

# For each cluster with ≥10 summaries:
for topic, summaries in clusters.items():
    if len(summaries) >= 10:
        l2 = generate_l2_cluster(summaries[:10], topic)
        store.save_episode(l2)  # layer=2
```

**Result:** 10 L1 summaries → 1 L2 cluster (topic-level synthesis).

---

### L2 → L3 Promotion

**Trigger:** ≥3 L2 clusters exist

**Process:**
```python
l2_clusters = store.list_episodes(layer=2)[:3]
l3 = generate_l3_arc(
    [c.id for c in l2_clusters],
    arc_name="Personal Development"
)
store.save_episode(l3)  # layer=3, is_permanent=True
```

**Result:** 3 topic clusters → 1 life-arc (meta-patterns).

---

## Decay & Archival

### Ebbinghaus Forgetting Curve

```python
def compute_decay(episode, now):
    half_life = config[f"half_life_l{episode.layer}"]  # L0:30, L1:180, L2:730, L3:∞
    
    days_since = (now - last_accessed).days
    decay = 0.5 ** (days_since / half_life)
    
    # Access boost: each access adds 10% decay resistance
    if episode.access_count > 0:
        decay *= min(2.0, 1.0 + 0.1 * episode.access_count)
    
    return clamp(decay, 0.0, 1.0)
```

**Example:**
- L0 episode, last accessed 60 days ago, accessed 3 times:
  ```
  decay = 0.5 ** (60/30) = 0.5² = 0.25
  access_boost = min(2.0, 1.0 + 0.1×3) = 1.3
  final_decay = 0.25 × 1.3 = 0.325
  ```

---

### Archival Strategy

```
Pruning runs on:
1. SessionEnd hook
2. Manual /memory prune
3. Scheduled (future)

Steps:
1. Update decay scores for ALL episodes
2. Archive L0/L1 with decay < 0.05 AND not accessed in 90 days
   → Move to layers/l0/archived/ subdirectory
3. Delete archives older than 365 days
4. Resolve conflicts (contradictory episodes)
   → Keep newer/higher importance, archive the other
```

**Recovery:** Archived files can be manually restored from `~/.claude/memory/layers/l0/archived/`.

---

## Project Navigation & Scoping

### Per-Project vs Global

**Global store:** `~/.claude/memory/` (shared)

**Per-project config:**
- `PROJECT_ROOT/.claude/settings.json` — hooks configuration
- `PROJECT_ROOT/.claude/rules/` — project-specific rules
- `PROJECT_ROOT/AGENTS.md` — always-on project instructions

**Episode source tracking:**
```yaml
source_path: /Users/darksied/dev/ideas/wristturn/wristturn.ino
session_id: sess_20260501_xyz
```

You can filter by project:
```bash
# Show all episodes from current project
memory list | grep "$(pwd)"

# Show episodes for specific file
memory search "auth" --filter source_path=/project/src/auth.py
```

---

## Summary

1. **1 global store** (`~/.claude/memory/`) holds all projects' memories
2. Episodes tagged with `source_path` to identify project
3. Dedup works globally (same content across projects → shared episode)
4. File state tracking is per-file (absolute path)
5. Layers apply globally (L0→L1 consolidation doesn't care about project boundaries)
6. You can filter by project in queries via `source_path` tag

**Why global?** Allows cross-project learning:
- Bug fix in Project A → applies to similar bug in Project B
- Patterns across projects become L2/L3 arcs
- One memory system for all your work

**If you want per-project isolation:**
Set up separate store paths:
```bash
# In project A
export CLAUDE_MEMORY_PATH=~/.claude/memory/project_a

# In project B
export CLAUDE_MEMORY_PATH=~/.claude/memory/project_b
```
