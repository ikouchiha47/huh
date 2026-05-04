#!/usr/bin/env python3
"""CLI tool for memory inspection and management.

Usage:
    memory save <content>          Save explicit memory
    memory search <query>          Search memory
    memory show <id>               Show episode details
    memory forget <id>             Delete episode
    memory stats                   Show statistics
    memory reflect                 Run consolidation
    memory prune                   Run pruning
    memory export                  Export to JSON
    memory list [--layer=L]        List episodes
    memory projects                List all projects
    memory switch <project_id>     Switch to project's memory
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.project_memory import ProjectMemoryManager, get_memory_store
from lib.store import MemoryEpisode, MemoryStore
from lib.reflector import MemoryReflector
from lib.prune import PruningService
from lib.retrieve import RetrievalOrchestrator


def get_store(project_root: str = None):
    """Get memory store, auto-detecting project from cwd if not specified."""
    if project_root:
        manager = ProjectMemoryManager()
        return manager.get_store_for_project(project_root)
    else:
        # Auto-detect from current directory
        return get_memory_store()


def cmd_save(args):
    """Save explicit memory."""
    store = get_store()

    episode_id = f"manual_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    episode = MemoryEpisode(
        id=episode_id,
        session_id="cli_session",
        timestamp=datetime.now(timezone.utc).isoformat(),
        layer=0,
        title=args.title or "Manual memory",
        content=args.content,
        category=args.category or "manual",
        importance=args.importance or 0.7,
        tags=args.tags or [],
        trigger_type="manual",
        is_permanent=args.permanent or False,
    )

    if store.save_episode(episode):
        print(f"✓ Saved episode: {episode.id}")
    else:
        print(f"⚠ Duplicate detected, not saved")


def cmd_search(args):
    """Search memory."""
    store = get_store()
    from lib.retrieve import RetrievalOrchestrator

    orchestrator = RetrievalOrchestrator(store)
    results = orchestrator.search(args.query, limit=args.limit)

    if not results:
        print("No results found.")
        return

    print(f"\nFound {len(results)} results:\n")
    for episode, score in results:
        print(f"--- [{episode.layer}] Score: {score:.2f} ---")
        print(f"ID: {episode.id}")
        print(f"Title: {episode.title}")
        print(f"Category: {episode.category}")
        print(f"Tags: {', '.join(episode.tags) if episode.tags else 'none'}")
        print(f"Importance: {episode.importance:.2f}")
        print(f"Decay: {episode.decay_score:.2f}")
        if episode.correction_applied:
            print(f"⚠️ CORRECTION: {episode.correction_delta}")
        if episode.lesson:
            print(f"Lesson: {episode.lesson}")
        print(f"\n{episode.content[:300]}{'...' if len(episode.content) > 300 else ''}")
        print()


def cmd_show(args):
    """Show episode details."""
    store = get_store()
    episode = store.get_episode(args.id)

    if not episode:
        print(f"Episode not found: {args.id}")
        return

    print(f"\n{'='*60}")
    print(f"Episode: {episode.id}")
    print(f"{'='*60}")
    print(f"Layer: {episode.layer}")
    print(f"Session: {episode.session_id}")
    print(f"Timestamp: {episode.timestamp}")
    print(f"Title: {episode.title}")
    print(f"Category: {episode.category}")
    print(f"Tags: {', '.join(episode.tags) if episode.tags else 'none'}")
    print(f"Importance: {episode.importance:.2f}")
    print(f"Frustration: {episode.frustration_score:.2f}")
    print(f"Correction: {episode.correction_applied}")
    print(f"Permanent: {episode.is_permanent}")
    print(f"Access count: {episode.access_count}")
    print(f"Decay score: {episode.decay_score:.2f}")

    if episode.source_type:
        print(f"Source: {episode.source_type}")
    if episode.source_path:
        print(f"Source path: {episode.source_path}")
    if episode.source_hash:
        print(f"Source hash: {episode.source_hash}")
    if episode.root_cause:
        print(f"Root cause: {episode.root_cause}")
    if episode.impact:
        print(f"Impact: {episode.impact}")
    if episode.lesson:
        print(f"Lesson: {episode.lesson}")

    # Links
    links = store.get_links(episode.id)
    if links:
        print(f"\nLinked episodes:")
        for link in links:
            print(f"  → {link[0]} ({link[1]}, strength: {link[2]:.2f})")

    if episode.parent_id:
        print(f"\nParent: {episode.parent_id}")
    if episode.linked_ids:
        print(f"Linked IDs: {', '.join(episode.linked_ids)}")

    print(f"\n{'='*60}")
    print("Content:")
    print(f"{'='*60}")
    print(episode.content)
    print(f"{'='*60}\n")


def cmd_forget(args):
    """Delete episode."""
    store = get_store()
    if store.delete_episode(args.id):
        print(f"✓ Deleted episode: {args.id}")
    else:
        print(f"⚠ Episode not found: {args.id}")


def cmd_stats(args):
    """Show statistics."""
    store = get_store()
    stats = store.get_stats()

    print(f"\nMemory Store Statistics")
    print(f"{'='*40}")
    print(f"Total episodes: {stats['total']}")
    print(f"\nBy layer:")
    for layer, count in stats["layers"].items():
        print(f"  {layer}: {count}")
    print(f"\nHash cache size: {stats.get('hash_cache_size', 0)}")
    print(f"File states: {stats.get('file_states_size', 0)}")
    print(f"Links: {stats.get('links', 0)}")

    # Recent episodes
    print(f"\nRecent L0 episodes:")
    recent = store.list_episodes(layer=0)[:5]
    for ep in recent:
        print(f"  {ep.id[:16]}... | {ep.title[:30]}... | {ep.category}")
    print()


def cmd_list(args):
    """List episodes."""
    store = get_store()
    layer = int(args.layer) if args.layer else None
    episodes = store.list_episodes(layer=layer)

    print(f"\nEpisodes ({len(episodes)} total):\n")
    for ep in episodes:
        marker = "⭐" if ep.is_permanent else "⚠" if ep.correction_applied else ""
        print(
            f"{marker} [{ep.layer}] {ep.id[:16]}... | {ep.title[:40]} | {ep.category} | decay: {ep.decay_score:.2f}"
        )
    print()


def cmd_reflect(args):
    """Run consolidation."""
    store = get_store()
    reflector = MemoryReflector(store)

    print("Running consolidation...")
    result = reflector.consolidate(max_l0_per_batch=args.batch_size)

    print(f"\nConsolidation complete:")
    print(f"  L1 created: {result['l1_created']}")
    print(f"  L2 created: {result['l2_created']}")
    print(f"  L3 created: {result['l3_created']}")


def cmd_prune(args):
    """Run pruning."""
    store = get_store()
    pruner = PruningService(store)

    print("Running pruning...")
    result = pruner.prune()

    print(f"\nPruning complete:")
    print(f"  Decay scores updated: {result['updated_decay']}")
    print(f"  Conflicts resolved: {result['conflicts_resolved']}")
    print(f"  Episodes archived: {result['archived']}")
    print(f"  Ancient deleted: {result['deleted']}")


def cmd_export(args):
    """Export memory to JSON."""
    store = get_store()

    all_episodes = []
    for layer in range(4):
        episodes = store.list_episodes(layer=layer)
        for ep in episodes:
            all_episodes.append(
                {
                    "id": ep.id,
                    "layer": ep.layer,
                    "timestamp": ep.timestamp,
                    "title": ep.title,
                    "category": ep.category,
                    "tags": ep.tags,
                    "importance": ep.importance,
                    "content": ep.content,
                    "decay_score": ep.decay_score,
                }
            )

    output = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total": len(all_episodes),
        "episodes": all_episodes,
    }

    path = (
        Path(args.output)
        if args.output
        else Path.home()
        / ".claude"
        / "memory"
        / "exports"
        / f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"✓ Exported {len(all_episodes)} episodes to {path}")


def cmd_projects(args):
    """List all projects with memory stores."""
    # Use global store to list projects
    manager = ProjectMemoryManager()
    projects = manager.list_projects()
    
    if not projects:
        print("No projects found.")
        return
    
    print(f"\nProjects ({len(projects)} total):\n")
    for p in projects:
        print(f"  📁 {p['name']}")
        print(f"     ID:       {p['project_id']}")
        print(f"     Root:     {p['root']}")
        print(f"     Episodes: {p['episode_count']}")
        if p.get('created_at'):
            print(f"     Created:  {p['created_at']}")
        print()


def cmd_switch(args):
    """Switch memory context to a project."""
    manager = ProjectMemoryManager()
    store = manager.get_store_for_project_id(args.project_id)
    
    if not store:
        print(f"Project not found: {args.project_id}")
        print("Use 'memory projects' to see available projects.")
        return
    
    stats = store.get_stats()
    print(f"\nSwitched to project: {args.project_id}")
    print(f"  Episodes: {stats['total']} total")
    print(f"  Layers:  L0={stats['layers'].get('l0',0)}, L1={stats['layers'].get('l1',0)}, "
          f"L2={stats['layers'].get('l2',0)}, L3={stats['layers'].get('l3',0)}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Memory management CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Save
    save_parser = subparsers.add_parser("save", help="Save memory")
    save_parser.add_argument("content", help="Memory content")
    save_parser.add_argument("--title", help="Title")
    save_parser.add_argument("--category", help="Category")
    save_parser.add_argument("--importance", type=float, help="Importance (0-1)")
    save_parser.add_argument("--tags", nargs="*", help="Tags")
    save_parser.add_argument("--permanent", action="store_true", help="Mark permanent")

    # Search
    search_parser = subparsers.add_parser("search", help="Search memory")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=20, help="Result limit")

    # Show
    show_parser = subparsers.add_parser("show", help="Show episode")
    show_parser.add_argument("id", help="Episode ID")

    # Forget
    forget_parser = subparsers.add_parser("forget", help="Delete episode")
    forget_parser.add_argument("id", help="Episode ID")

    # Stats
    subparsers.add_parser("stats", help="Show statistics")

    # List
    list_parser = subparsers.add_parser("list", help="List episodes")
    list_parser.add_argument("--layer", help="Filter by layer")

    # Reflect
    reflect_parser = subparsers.add_parser("reflect", help="Run consolidation")
    reflect_parser.add_argument(
        "--batch-size", type=int, default=20, help="L0 batch size"
    )

    # Prune
    subparsers.add_parser("prune", help="Run pruning")

    # Export
    export_parser = subparsers.add_parser("export", help="Export memory")
    export_parser.add_argument("--output", help="Output file path")

    # Projects
    subparsers.add_parser("projects", help="List all projects")

    # Switch
    switch_parser = subparsers.add_parser("switch", help="Switch to project memory")
    switch_parser.add_argument("project_id", help="Project ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "save": cmd_save,
        "search": cmd_search,
        "show": cmd_show,
        "forget": cmd_forget,
        "stats": cmd_stats,
        "list": cmd_list,
        "reflect": cmd_reflect,
        "prune": cmd_prune,
        "export": cmd_export,
        "projects": cmd_projects,
        "switch": cmd_switch,
    }

    try:
        commands[args.command](args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
