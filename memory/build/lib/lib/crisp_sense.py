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
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path (so we can import lib.*)
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.indexers import get_default_registry
from lib.project_memory import ProjectMemoryManager

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name == "tools" else SCRIPT_DIR

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
    
    # Extract hash from frontmatter
    import re
    m = re.search(r"^hash:\s*(\S+)", text, re.MULTILINE)
    if m:
        result["hash"] = m.group(1)
    
    # Extract summary
    summary_match = re.search(r"## Summary\n(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if summary_match:
        result["summary"] = summary_match.group(1).strip()
    
    # Extract symbol tree
    tree_match = re.search(r"## Symbol Tree\n```json\n(.*?)\n```", text, re.DOTALL)
    if tree_match:
        try:
            result["symbol_tree"] = json.loads(tree_match.group(1))
        except json.JSONDecodeError:
            result["symbol_tree"] = None
    
    # Extract hierarchy
    hierarchy_match = re.search(r"## Hierarchy\n```json\n(.*?)\n```", text, re.DOTALL)
    if hierarchy_match:
        try:
            result["hierarchy"] = json.loads(hierarchy_match.group(1))
        except json.JSONDecodeError:
            result["hierarchy"] = None
    
    return result


def write_cache(cache: Path, index_result) -> None:
    """Write index result to cache file."""
    cache.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        rel = index_result.file_path.relative_to(PROJECT_ROOT)
    except ValueError:
        rel = index_result.file_path
    
    content = f"""---
file: {rel}
hash: {index_result.content_hash}
media_type: {index_result.media_type}
---

## Summary
{index_result.summary}

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
    
    # Write cache
    try:
        write_cache(cache, result)
    except Exception as e:
        print(json.dumps({
            "status": "error",
            "error": f"Failed to write cache: {e}"
        }))
        return 1
    
    # Optionally store in Crisp Engine episodic memory
    try:
        from lib.store import MemoryStore
        store = MemoryStore(str(Path.home() / ".claude" / "memory"))
        if hasattr(indexer, 'extract_episodes'):
            episodes = indexer.extract_episodes(result)
            for ep_data in episodes:
                from lib.store import MemoryEpisode
                ep = MemoryEpisode(**ep_data)
                store.save_episode(ep)
    except Exception:
        # Don't fail if episodic storage unavailable
        pass
    
    print(json.dumps({
        "status": "indexed",
        "file": str(file_path.relative_to(PROJECT_ROOT) if file_path.is_relative_to(PROJECT_ROOT) else file_path),
        "media_type": result.media_type,
        "symbols_count": len(result.symbols),
        "summary": result.summary[:100] + ("..." if len(result.summary) > 100 else ""),
        "cache_written": str(cache),
    }))
    return 0


def handle_init():
    """Initialize cache for a specific file."""
    parser = argparse.ArgumentParser(description="Initialize cache for file")
    parser.add_argument("file", type=Path, help="File to index")
    args = parser.parse_args()
    
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


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Media indexer for Claude Code hooks")
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # Hook mode (no subcommand) - reads from stdin
    # Can also be called as: crisp-sense hook (with CLAUDE_HOOK_EVENT set)
    
    # Init single file
    init_parser = subparsers.add_parser("init", help="Initialize cache for file")
    init_parser.add_argument("file", type=Path, help="File to index")
    
    # Init all
    subparsers.add_parser("init-all", help="Index all files in project")
    
    # Status
    subparsers.add_parser("status", help="Show cache statistics")
    
    # Parse
    if len(sys.argv) >= 2 and sys.argv[1] in ["init", "init-all", "status"]:
        args = parser.parse_args()
    else:
        # Hook mode - consume remaining args but let handler do its own parsing
        args = parser.parse_args()
    
    # Dispatch
    if args.command == "init":
        return handle_init()
    elif args.command == "init-all":
        return handle_init_all()
    elif args.command == "status":
        return handle_status()
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
