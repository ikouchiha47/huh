#!/usr/bin/env python3
"""
Crisp Sense — Media indexing for Claude Code.

Hooks into PreToolUse/PostToolUse to extract structured information
from files before Claude reads them, enabling fast symbol-table based
retrieval instead of full file reads.

Usage as hook:
  crisp-sense pre  --file /path/to/file.ts   # Check cache, return symbols if fresh
  crisp-sense post --file /path/to/file.ts   # Index file, update cache

Standalone:
  crisp-sense init /path/to/file.ts         # Initialize cache for file
  crisp-sense init-all                      # Index all source files in project
  crisp-sense status                        # Show cache statistics
"""
import sys
import os
import re
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path (so we can import lib.*)
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.indexers import get_default_registry
from lib.project_memory import ProjectMemoryManager

# ── Paths ─────────────────────────────────────────────────────────────────────

def _find_project_root() -> Path:
    """Find git root of cwd, fallback to cwd."""
    cwd = Path.cwd()
    for p in [cwd] + list(cwd.parents):
        if (p / ".git").exists():
            return p
    return cwd

PROJECT_ROOT = _find_project_root()

# Cache location: ~/.claude/code-memory/ (global) or per-project?
# Using global for now, can change to per-project later
CACHE_DIR = Path.home() / ".claude" / "code-memory"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Hashing ───────────────────────────────────────────────────────────────────

def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file content."""
    import hashlib
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as e:
        raise FileNotFoundError(f"Cannot read {file_path}: {e}")


# ── Cache path ────────────────────────────────────────────────────────────────

def cache_path(file_path: Path) -> Path:
    """Get cache file path for a source file.
    
    Cache format: ~/.claude/code-memory/{file_path_slug}.md
    
    Slug is relative path with separators replaced by double underscores.
    Example: src/ble/useBLE.ts → src__ble__useBLE.ts.md
    """
    try:
        rel = file_path.relative_to(PROJECT_ROOT)
    except ValueError:
        # File outside project, use absolute path slug
        rel = file_path
    
    slug = str(rel).replace("/", "__").replace("\\", "__").replace(" ", "_")
    return CACHE_DIR / f"{slug}.md"


def read_cache(cache: Path) -> dict:
    """Read cache file, return dict with hash, summary, symbol_tree."""
    if not cache.exists():
        return {}
    text = cache.read_text(encoding="utf-8")
    result = {"raw": text}

    for field in ("hash", "media_type", "summary", "question", "when_relevant"):
        m = re.search(rf"^{field}:[ \t]*(.*)", text, re.MULTILINE)
        if m:
            result[field] = m.group(1).strip()

    # triggers: YAML list
    triggers_match = re.search(r"^triggers:\n((?:  .*\n)*)", text, re.MULTILINE)
    if triggers_match:
        result["triggers"] = re.findall(r'- "?(.*?)"?\s*$', triggers_match.group(1), re.MULTILINE)

    # symbols JSON block
    for section, key in [("Symbols", "symbol_tree"), ("Hierarchy", "hierarchy")]:
        m = re.search(rf"## {section}\n```json\n(.*?)\n```", text, re.DOTALL)
        if m:
            try:
                result[key] = json.loads(m.group(1))
            except json.JSONDecodeError:
                result[key] = None

    # Symbol Docs: parse ### Name (type)\n<body> subsections
    symbol_docs: dict[str, str] = {}
    sym_docs_block = re.search(r"## Symbol Docs\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if sym_docs_block:
        block = sym_docs_block.group(1)
        for m in re.finditer(r"### (.+?)\n(.*?)(?=\n### |\Z)", block, re.DOTALL):
            name = m.group(1).strip()
            body = m.group(2).strip()
            if body and not body.startswith("<!--"):
                symbol_docs[name] = body
    result["symbol_docs"] = symbol_docs

    return result


def write_cache(cache: Path, index_result, summary: str = "", triggers: list = None, question: str = "", when_relevant: str = "") -> None:
    """Write index result to cache file."""
    cache.parent.mkdir(parents=True, exist_ok=True)

    try:
        rel = index_result.file_path.relative_to(PROJECT_ROOT)
    except ValueError:
        rel = index_result.file_path

    triggers_yaml = "\n".join(f"  - \"{t}\"" for t in (triggers or []))

    content = f"""---
file: {rel}
hash: {index_result.content_hash}
media_type: {index_result.media_type}
summary: {summary or ""}
question: {question or ""}
when_relevant: {when_relevant or ""}
triggers:
{triggers_yaml if triggers_yaml else "  []"}
---

## Mechanical Summary
{index_result.summary}

## Symbol Docs

<!-- crisp-sense doc-symbol adds entries here -->

## Hierarchy
```json
{json.dumps(index_result.hierarchy, indent=2)}
```

## Symbols
```json
{json.dumps(index_result.symbols, indent=2)}
```

## Metadata
```json
{json.dumps(index_result.metadata, indent=2)}
```
"""
    cache.write_text(content, encoding="utf-8")


def write_dir_index(dir_path: Path, entries: list) -> None:
    """Write/update directory index.md in code-memory cache.

    entries: list of dicts with keys: file, summary, media_type, symbols_count
    """
    try:
        rel = dir_path.relative_to(PROJECT_ROOT)
    except ValueError:
        rel = dir_path

    slug = str(rel).replace("/", "__").replace("\\", "__").replace(" ", "_")
    cache = CACHE_DIR / f"{slug}__index.md"
    cache.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Directory Index: {rel}",
        f"updated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Files",
        "",
    ]
    for e in sorted(entries, key=lambda x: x.get("file", "")):
        summary = e.get("summary", "").split("\n")[0][:100]
        lines.append(f"- **{e['file']}** ({e.get('media_type','?')}, {e.get('symbols_count',0)} symbols) — {summary}")

    lines += ["", "## Semantic Summary", "", "(not yet enriched — run `/huh index <dir>` to generate)"]

    cache.write_text("\n".join(lines), encoding="utf-8")


def enrich_cache(file_path: Path, summary: str = "", triggers: list = None, question: str = "", when_relevant: str = "") -> bool:
    """Add LLM-generated fields to an existing cache entry. Returns False if cache missing."""
    cache = cache_path(file_path)
    if not cache.exists():
        return False

    cached = read_cache(cache)
    if not cached:
        return False

    import re
    text = cache.read_text(encoding="utf-8")

    triggers_yaml = "\n".join(f"  - \"{t}\"" for t in (triggers or []))

    def replace_field(field, value, text):
        return re.sub(rf"^{field}:.*$", f"{field}: {value}", text, flags=re.MULTILINE)

    text = replace_field("summary", summary or cached.get("summary", ""), text)
    text = replace_field("question", question or cached.get("question", ""), text)
    text = replace_field("when_relevant", when_relevant or cached.get("when_relevant", ""), text)
    text = re.sub(r"^triggers:\n(  .*\n)*", f"triggers:\n{triggers_yaml if triggers_yaml else '  []'}\n", text, flags=re.MULTILINE)

    cache.write_text(text, encoding="utf-8")
    return True


def write_symbol_doc(file_path: Path, symbol_name: str, doc: str) -> bool:
    """Upsert a symbol's doc entry in the ## Symbol Docs section. Returns False if no cache."""
    cache = cache_path(file_path)
    if not cache.exists():
        return False

    text = cache.read_text(encoding="utf-8")

    section_header = f"### {symbol_name}\n"
    entry = f"### {symbol_name}\n{doc.rstrip()}\n"

    # Replace existing entry
    existing = re.search(
        rf"### {re.escape(symbol_name)}\n(.*?)(?=\n### |\n## |\Z)",
        text, re.DOTALL
    )
    if existing:
        text = text[:existing.start()] + entry + text[existing.end():]
    else:
        # Append into ## Symbol Docs block, before the next ## section
        insert_marker = re.search(r"## Symbol Docs\n(<!-- .*? -->\n)?", text)
        if insert_marker:
            pos = insert_marker.end()
            text = text[:pos] + "\n" + entry + text[pos:]
        else:
            # No Symbol Docs section — append before ## Hierarchy
            hier = text.find("\n## Hierarchy")
            if hier >= 0:
                text = text[:hier] + "\n\n## Symbol Docs\n\n" + entry + text[hier:]

    cache.write_text(text, encoding="utf-8")
    return True


def _collect_dir_entries(dir_path: Path) -> list:
    """Collect cache summary entries for all files in a directory."""
    entries = []
    registry = get_default_registry()
    for f in sorted(dir_path.iterdir()):
        if not f.is_file():
            continue
        if not registry.get_indexer(f):
            continue
        c = cache_path(f)
        cached = read_cache(c) if c.exists() else {}
        try:
            rel = f.relative_to(PROJECT_ROOT)
        except ValueError:
            rel = f
        summary = cached.get("summary", "")
        if not summary and "raw" in cached:
            import re
            m = re.search(r"## Mechanical Summary\n(.*?)(?=\n##|\Z)", cached["raw"], re.DOTALL)
            summary = m.group(1).strip()[:100] if m else ""
        entries.append({
            "file": str(rel),
            "summary": summary,
            "media_type": cached.get("media_type", "?"),
            "symbols_count": len(cached.get("symbol_tree") or []),
        })
    return entries


# ── Hook Handlers ─────────────────────────────────────────────────────────────

def handle_pre_tool_use():
    """PreToolUse hook: check cache, return symbol tree if fresh."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print(json.dumps({"error": "invalid input"}))
        return 1
    
    tool = data.get("tool", "")
    if tool != "Read":
        # Not a read operation, ignore
        print(json.dumps({"status": "ignored", "reason": f"tool={tool}, not Read"}))
        return 0
    
    file_path_str = data.get("input", {}).get("file_path", "")
    if not file_path_str:
        print(json.dumps({"error": "no file_path in input"}))
        return 1
    
    file_path = Path(file_path_str).resolve()

    # Skip cache files themselves
    if CACHE_DIR in file_path.parents or file_path.parent == CACHE_DIR:
        print(json.dumps({"status": "skip", "reason": "cache file"}))
        return 0

    # Get appropriate indexer
    registry = get_default_registry()
    indexer = registry.get_indexer(file_path)

    if not indexer:
        print(json.dumps({"status": "skip", "reason": "no suitable indexer"}))
        return 0
    
    # Check cache
    cache = cache_path(file_path)
    if not cache.exists():
        print(json.dumps({"status": "cache_miss", "skip_read": False}))
        return 0
    
    cached = read_cache(cache)
    current_hash = compute_file_hash(file_path)
    cached_hash = cached.get("hash", "")
    
    if current_hash == cached_hash and "symbol_tree" in cached:
        # Cache hit! Return structured data to Claude
        print(json.dumps({
            "status": "cache_hit",
            "skip_read": True,
            "symbol_tree": cached["symbol_tree"],
            "hierarchy": cached.get("hierarchy"),
            "summary": cached.get("summary", ""),
            "media_type": cached.get("media_type", indexer.index.__self__.__class__.__name__ if hasattr(indexer, '__self__') else "unknown"),
            "message": f"crisp-sense: using cached index for {file_path.name}"
        }))
        return 0
    else:
        # Cache stale or incomplete
        print(json.dumps({
            "status": "cache_miss",
            "skip_read": False,
            "message": f"crisp-sense: cache stale for {file_path.name}"
        }))
        return 0


def handle_post_tool_use():
    """PostToolUse hook: re-index file after it was read/written."""
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        print(json.dumps({"error": "invalid input"}))
        return 1
    
    tool = data.get("tool", "")
    if tool not in ["Read", "Write", "Edit", "MultiEdit"]:
        print(json.dumps({"status": "ignored", "reason": f"tool={tool}, not file-modifying"}))
        return 0
    
    file_path_str = data.get("input", {}).get("file_path", "")
    if not file_path_str:
        print(json.dumps({"error": "no file_path"}))
        return 1
    
    file_path = Path(file_path_str).resolve()

    # Skip cache files themselves
    if CACHE_DIR in file_path.parents or file_path.parent == CACHE_DIR:
        print(json.dumps({"status": "skip", "reason": "cache file"}))
        return 0

    # Get indexer
    registry = get_default_registry()
    indexer = registry.get_indexer(file_path)

    if not indexer:
        print(json.dumps({"status": "skip", "reason": "no suitable indexer"}))
        return 0

    # Index the file
    cache = cache_path(file_path)
    try:
        result = indexer.index(file_path)
    except Exception as e:
        print(json.dumps({
            "status": "error",
            "error": str(e),
            "file": str(file_path.relative_to(PROJECT_ROOT) if file_path.is_relative_to(PROJECT_ROOT) else file_path)
        }))
        return 1
    
    # Write cache (Layer 2 only — no Layer 3 save)
    try:
        write_cache(cache, result)
    except Exception as e:
        print(json.dumps({"status": "error", "error": f"Failed to write cache: {e}"}))
        return 1

    # Update parent directory index
    try:
        dir_entries = _collect_dir_entries(file_path.parent)
        write_dir_index(file_path.parent, dir_entries)
    except Exception:
        pass

    rel = str(file_path.relative_to(PROJECT_ROOT) if file_path.is_relative_to(PROJECT_ROOT) else file_path)
    print(json.dumps({
        "status": "indexed",
        "file": rel,
        "media_type": result.media_type,
        "symbols_count": len(result.symbols),
        "summary": result.summary[:100] + ("..." if len(result.summary) > 100 else ""),
        "cache_written": str(cache),
    }))
    return 0


def handle_init(args):
    """Initialize cache for a specific file."""
    file_path = args.file.resolve()
    registry = get_default_registry()
    indexer = registry.get_indexer(file_path)
    
    if not indexer:
        print(f"Error: No indexer for {file_path}")
        return 1
    
    try:
        result = indexer.index(file_path)
        cache = cache_path(file_path)
        write_cache(cache, result)
        print(f"Initialized {file_path} → {cache}")
        print(f"  Summary: {result.summary}")
        print(f"  Symbols: {len(result.symbols)}")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def handle_init_all():
    """Initialize cache for all supported files in project."""
    registry = get_default_registry()
    count = 0
    errors = []
    
    # Walk project directory
    for ext in ['.ts', '.tsx', '.js', '.jsx', '.py', '.java', '.go', '.rs',
                '.c', '.cpp', '.h', '.hpp', '.ino', '.md', '.markdown']:
        for file_path in PROJECT_ROOT.rglob(f"*{ext}"):
            # Skip ignored directories
            if any(part in file_path.parts for part in ['.git', 'node_modules', 'android', 'ios', 'build', 'dist', '.venv', '__pycache__']):
                continue
            
            try:
                indexer = registry.get_indexer(file_path)
                if indexer:
                    result = indexer.index(file_path)
                    cache = cache_path(file_path)
                    write_cache(cache, result)
                    count += 1
                    if count % 100 == 0:
                        print(f"  Indexed {count} files...")
            except Exception as e:
                errors.append(str(file_path))
    
    print(f"Indexed {count} files")
    if errors:
        print(f"Errors ({len(errors)}):")
        for err in errors[:10]:
            print(f"  {err}")
    return 0 if not errors else 1


def handle_status():
    """Show cache statistics."""
    caches = list(CACHE_DIR.glob("*.md"))
    if not caches:
        print("No cache files found.")
        return 0
    
    fresh = 0
    stale = 0
    total_size = 0
    
    for cache in caches:
        total_size += cache.stat().st_size
        try:
            cached = read_cache(cache)
            if "hash" in cached:
                # Derive original file path from cache filename
                rel_str = cache.stem.replace("__", "/").replace("_", " ")
                file_path = PROJECT_ROOT / rel_str
                if file_path.exists():
                    current = compute_file_hash(file_path)
                    if current == cached["hash"]:
                        fresh += 1
                    else:
                        stale += 1
                else:
                    stale += 1  # file missing
            else:
                stale += 1  # incomplete cache
        except Exception:
            stale += 1
    
    print(f"Cache directory: {CACHE_DIR}")
    print(f"Total files: {len(caches)}")
    print(f"Fresh: {fresh}")
    print(f"Stale/incomplete: {stale}")
    print(f"Disk size: {total_size / 1024:.1f} KB")
    return 0


def handle_grammars():
    """Show tree-sitter grammar install status."""
    from .ts_parser import grammar_status, GRAMMAR_REGISTRY
    rows = grammar_status()
    print("Tree-sitter grammar status:\n")
    any_missing = False
    for row in rows:
        mark = "✓" if row["installed"] else "✗"
        print(f"  {mark}  {row['key']:<14} {row['pkg']}")
        if not row["installed"]:
            any_missing = True
    if any_missing:
        missing_pkgs = sorted({row["pkg"] for row in rows if not row["installed"]})
        print(f"\nInstall missing grammars:")
        print(f"  uv run pip install {' '.join(missing_pkgs)}")
        print(f"\nOr install all at once:")
        all_pkgs = sorted({pkg for _, _, pkg in GRAMMAR_REGISTRY.values()})
        print(f"  uv run pip install {' '.join(all_pkgs)}")
    else:
        print("\nAll grammars installed.")
    return 0


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Media indexer for Claude Code hooks")
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # Hook mode (no subcommand) - reads from stdin
    # Can also be called as: crisp-sense hook (with CLAUDE_HOOK_EVENT set)
    
    # Init single file
    init_parser = subparsers.add_parser("init", help="Initialize cache for file")
    init_parser.add_argument("file", type=Path, help="File to index")

    # Enrich — add LLM-generated fields to existing cache entry
    enrich_parser = subparsers.add_parser("enrich", help="Add LLM summary/triggers/question to cache entry")
    enrich_parser.add_argument("file", type=Path, help="File to enrich")
    enrich_parser.add_argument("--summary", default="", help="LLM-generated semantic summary")
    enrich_parser.add_argument("--triggers", nargs="*", default=[], help="Trigger phrases for retrieval")
    enrich_parser.add_argument("--question", default="", help="Canonical question this file answers")
    enrich_parser.add_argument("--when-relevant", default="", help="When to load this into context")

    # Dir-index — rebuild directory index.md
    dir_parser = subparsers.add_parser("dir-index", help="Rebuild directory index.md")
    dir_parser.add_argument("dir", type=Path, help="Directory to index")
    
    # Init all
    subparsers.add_parser("init-all", help="Index all files in project")
    
    # Status
    subparsers.add_parser("status", help="Show cache statistics")

    # Grammars
    subparsers.add_parser("grammars", help="Show tree-sitter grammar install status")

    # Doc-symbol — write per-symbol documentation into cache
    doc_parser = subparsers.add_parser("doc-symbol", help="Write structured doc for a symbol into cache")
    doc_parser.add_argument("file", type=Path, help="Source file the symbol belongs to")
    doc_parser.add_argument("symbol", help="Symbol name (class, function, or method)")
    doc_parser.add_argument("doc", help="Structured documentation for the symbol")

    # Parse
    if len(sys.argv) >= 2 and sys.argv[1] in ["init", "init-all", "status"]:
        args = parser.parse_args()
    else:
        # Hook mode - consume remaining args but let handler do its own parsing
        args = parser.parse_args()
    
    # Dispatch
    if args.command == "init":
        return handle_init(args)
    elif args.command == "init-all":
        return handle_init_all()
    elif args.command == "status":
        return handle_status()
    elif args.command == "enrich":
        fp = args.file.resolve()
        ok = enrich_cache(fp, summary=args.summary, triggers=args.triggers, question=args.question, when_relevant=args.when_relevant)
        if ok:
            print(f"✓ Enriched {fp.name}")
        else:
            print(f"⚠ No cache entry for {fp} — run crisp-sense init {fp} first")
        return 0 if ok else 1
    elif args.command == "dir-index":
        dp = args.dir.resolve()
        entries = _collect_dir_entries(dp)
        write_dir_index(dp, entries)
        print(f"✓ Directory index written for {dp} ({len(entries)} files)")
        return 0
    elif args.command == "grammars":
        return handle_grammars()
    elif args.command == "doc-symbol":
        fp = args.file.resolve()
        ok = write_symbol_doc(fp, args.symbol, args.doc)
        if ok:
            print(f"✓ Symbol doc written: {fp.name}#{args.symbol}")
        else:
            print(f"⚠ No cache entry for {fp} — run crisp-sense init {fp} first")
        return 0 if ok else 1
    else:
        # Assume hook mode - check environment
        hook_event = os.environ.get("CLAUDE_HOOK_EVENT", "")
        if "PreToolUse" in hook_event:
            return handle_pre_tool_use()
        elif "PostToolUse" in hook_event:
            return handle_post_tool_use()
        else:
            # No command and not hook mode - print usage
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
