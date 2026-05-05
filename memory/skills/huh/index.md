# /huh index — Index a file into memory

Index a file at symbol + file level. Follows imports to check dependencies, writes per-symbol summaries for key elements, then a file summary, then a dir summary if the parent isn't indexed.

## Steps

### 1. Get structure

```bash
huh index --json <path>
```

Output fields: `summary` (mechanical), `symbols`, `hierarchy`, `metadata`, `imports`.

`imports` is a list of `{path, names, local, resolved?}`. Local imports with a `resolved` field point to actual files on disk.

### 2. Walk local imports

For each import where `local: true` and `resolved` exists:

```bash
huh search-path <resolved_path>
```

- If a **fresh** summary exists → read it, use it as context. Do NOT open the file.
- If **no result or stale** → note the file as unindexed. Add it to the index queue (step 5).

This gives you cross-file context before writing any summaries.

### 3. Write per-symbol summaries

For every **class** and every **non-trivial function** (body > 5 lines or name is a key export), write a structured description:

**For a class:**
```
Class: <Name> — <purpose sentence>

State: <fields and what they track>
Lifecycle: <construction → key transitions → teardown>
Key methods:
  - <method(sig)> — <what it does, side effects, preconditions if non-obvious>
  - ...
Invariants: <any constraints the caller must respect>
Used by: <files that import this class, from step 2>
```

**For a standalone function:**
```
<name>(params) → <return type>
Purpose: <what it computes or does>
Key logic: <algorithm, thresholds, or state it reads/writes>
Called by: <callers if known from sibling imports>
```

Key symbols to prioritize:
- The primary export (same name as file, or named `use<X>`)
- State machines and lifecycle owners (largest class, methods named `handle*`, `on*`, `_*`)
- Functions with hardcoded thresholds or constants (document the values and their rationale)
- Any function whose body contains a comment explaining WHY — extract that WHY

Save each to the Layer 2 cache (not episodic memory — stays in the file's wiki page):

```bash
crisp-sense doc-symbol <file> <SymbolName> "<structured description above>"
```

This writes/updates a `### SymbolName` subsection inside `## Symbol Docs` in the cache file. All symbol docs for a file live in one place — the `PreToolUse` hook returns the full wiki page on cache hit.

### 4. Write the file-level summary

Using the symbols, import context (from step 2), and per-symbol descriptions (step 3), write:

- **One sentence**: what is this file's role in the codebase?
- **Classes**: name + state + key lifecycle (2–3 sentences each)
- **Key functions**: name + what they compute/do + notable thresholds or constants
- **Dependencies**: which local modules it pulls from, what they provide, and why this file needs them
- **Exported interface**: what consumers of this file actually call (the public API surface)

Keep it under 300 words. Future sessions read this instead of opening the file — every sentence should earn its place.

Save to **both** Layer 2 (fast cache lookup) and Layer 3 (episodic, searchable):

```bash
crisp-sense enrich <path> \
  --summary "<file summary>" \
  --triggers "<trigger1>" "<trigger2>" "<trigger3>" "<trigger4>" \
  --question "<single canonical question this file answers>" \
  --when-relevant "<situation description>"
```

```bash
huh save-index --path <path> --level file --content "<same summary>"
```

Triggers are 4–6 short phrases a developer would type before needing this file. Examples: `"BLE connect"`, `"calibration flow"`, `"gesture routing"`.

Valid `--level` values:

| Level | Scope | When to use |
|---|---|---|
| `symbol` | Single function/class | Fine-grained: what does this specific symbol do |
| `file` | One source file | What does this file do, its exports and key logic |
| `dir` | A directory | What does this package/folder contain as a whole |
| `module` | A cross-dir module | A named subsystem spanning multiple dirs |
| `feature` | A product feature | End-to-end capability (e.g. "calibration flow") |
| `project` | The whole repo | Top-level architecture, major components, purpose |

### 5. Index unindexed imports (if any)

For each file from step 2 that had no fresh summary, run `/huh index <resolved_path>` recursively — but limit to **direct dependencies only** (do not recurse into their imports).

### 6. Dir-level summary (if not yet indexed)

```bash
huh search-path <parent_dir>
```

If no dir-level result → write a dir summary:
- One sentence: what does this directory contain as a whole?
- Key files and their roles (one phrase each)

```bash
huh save-index --path <parent_dir> --level dir --content "<dir summary>"
```

### 7. Report

Show: path indexed, symbol summaries saved (count), episode IDs from CLI, any unindexed imports queued.
