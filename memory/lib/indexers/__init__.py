"""Registry for media indexers with Liskov-compliant composition.

This module provides the IndexerRegistry class that manages
multiple IMediaIndexer implementations and selects the appropriate
one for a given file.

Design principles:
- Single Responsibility: Registry only selects/dispatches, doesn't index
- Open/Closed: New indexers can be added without modifying registry
- Liskov: All indexers implement IMediaIndexer → swappable
- Dependency Inversion: Depends on IMediaIndexer abstraction, not concretions
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from .indexer_common import IMediaIndexer, IndexResult


class IndexerRegistry:
    """Registry that holds available media indexers.
    
    Supports:
    - Registration of new indexers at runtime
    - Automatic selection based on file type
    - Fallback chain (first match wins)
    - Extensibility (third-party indexers can be added)
    """
    
    def __init__(self):
        """Initialize registry with default indexers."""
        self._indexers: List[IMediaIndexer] = []
        self._register_defaults()
    
    def _register_defaults(self):
        """Register built-in indexers in order of preference."""
        # Import here to avoid circular dependencies
        from .code_indexer import CodeIndexer
        from .markdown_indexer import MarkdownIndexer
        from .text_indexer import TextIndexer
        from .image_indexer import ImageIndexer
        from .audio_indexer import AudioIndexer
        
        # Order matters: more specific first, general fallback last
        self.register(CodeIndexer())
        self.register(MarkdownIndexer())
        self.register(ImageIndexer())
        self.register(AudioIndexer())
        self.register(TextIndexer())  # fallback for any readable text
    
    def register(self, indexer: IMediaIndexer):
        """Register an indexer with the registry.
        
        Args:
            indexer: An instance of a class implementing IMediaIndexer
            
        Note:
            Indexers are checked in registration order (first match wins).
            Register more specific indexers before general ones.
        """
        self._indexers.append(indexer)
    
    def unregister(self, indexer_type: type):
        """Remove all indexers of a given type."""
        self._indexers = [idx for idx in self._indexers if not isinstance(idx, indexer_type)]
    
    def get_indexer(self, file_path: Path, content_type: str = None) -> Optional[IMediaIndexer]:
        """Find the first indexer that can handle the given file.
        
        Args:
            file_path: Path to the file to index
            content_type: MIME type if known (optional, for disambiguation)
            
        Returns:
            An IMediaIndexer instance, or None if no suitable indexer found
            
        Example:
            >>> registry = IndexerRegistry()
            >>> indexer = registry.get_indexer(Path("foo.ts"))
            >>> if indexer:
            >>>     result = indexer.index(Path("foo.ts"))
        """
        for indexer in self._indexers:
            try:
                if indexer.can_index(file_path, content_type):
                    return indexer
            except Exception:
                # If can_index raises, treat as "cannot handle"
                continue
        return None
    
    def index_file(self, file_path: Path, context: Optional[Dict[str, Any]] = None) -> Optional[IndexResult]:
        """Convenience method: get appropriate indexer and index the file.
        
        Args:
            file_path: Path to the file to index
            context: Optional dict with 'store' key for episode persistence
            
        Returns:
            IndexResult if successful, None if no indexer found
            
        Raises:
            Any exception from indexer.index() propagates up.
        """
        indexer = self.get_indexer(file_path)
        if indexer is None:
            return None
        
        result = indexer.index(file_path, context)
        
        # If context provided, also create episodic memories
        if context and "store" in context and hasattr(indexer, "extract_episodes"):
            episodes = indexer.extract_episodes(result)
            store = context["store"]
            for ep_data in episodes:
                # Create MemoryEpisode from dict
                from ..store import MemoryEpisode
                ep = MemoryEpisode(**ep_data)
                store.save_episode(ep)
        
        return result
    
    def list_supported_types(self) -> List[str]:
        """Return list of file extensions this registry can handle.
        
        Note: This is a best-effort inspection. Not all indexers
        may implement explicit extension lists.
        """
        extensions = set()
        for indexer in self._indexers:
            if hasattr(indexer, 'SUPPORTED_EXTENSIONS'):
                extensions.update(indexer.SUPPORTED_EXTENSIONS)
        return sorted(extensions)
    
    def clear(self):
        """Remove all registered indexers."""
        self._indexers.clear()


# Global singleton registry (convenient for CLI tools)
_default_registry = None

def get_default_registry() -> IndexerRegistry:
    """Get or create the global default registry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = IndexerRegistry()
    return _default_registry
