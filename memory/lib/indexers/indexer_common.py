"""Common types and interfaces for the composable indexing system.

This module defines the contract that all media indexers must follow.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class IndexResult:
    """Result of indexing a media file.
    
    Attributes:
        media_type: Type of media ("code", "markdown", "image", "audio", "text")
        file_path: Absolute path to the file
        content_hash: SHA256 hash of file content (64-char hex)
        summary: 2-3 sentence human-readable description
        hierarchy: Tree structure representing file organization
            - Code: {classes: [{methods: []}], functions: []}
            - Markdown: {heading: "Title", children: []}
            - Image: {width, height, format}
        symbols: Flat list of symbols/definitions with line numbers
            - [{name: "foo", type: "function", line_start: 10, line_end: 20, 
                signature: "def foo(x: int) -> str", docstring: "..."}]
        metadata: Additional keys (language, size_bytes, duration, etc.)
    """
    media_type: str
    file_path: Path
    content_hash: str
    summary: str
    hierarchy: Any  # Dict-like tree structure
    symbols: List[Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_cache_format(self, project_root: Path) -> str:
        """Convert to markdown cache format (like original code_memory.py)."""
        try:
            rel_path = self.file_path.relative_to(project_root)
        except ValueError:
            rel_path = self.file_path
        
        lines = [
            "---",
            f"file: {rel_path}",
            f"hash: {self.content_hash}",
            f"media_type: {self.media_type}",
            "---",
            "",
            "## Summary",
            self.summary,
            "",
            "## Hierarchy",
            "```json",
            self._json_dump(self.hierarchy),
            "```",
            "",
            "## Symbols",
            "```json",
            self._json_dump(self.symbols),
            "`"
        ]
        
        # Add media-specific sections
        if self.media_type == "code" and self.metadata.get("language"):
            lines.extend([
                "",
                "## Metadata",
                f"Language: {self.metadata['language']}",
                f"Symbols: {len(self.symbols)}",
            ])
        
        return "\n".join(lines)
    
    @staticmethod
    def _json_dump(obj: Any) -> str:
        """Pretty-print JSON for cache file."""
        import json
        return json.dumps(obj, indent=2, ensure_ascii=False)


class IMediaIndexer(Protocol):
    """Protocol (interface) for media indexers.
    
    Any class implementing this protocol can be plugged into the registry.
    This enables Liskov substitution - any indexer can replace another.
    """
    
    def can_index(self, file_path: Path, content_type: str = None) -> bool:
        """Return True if this indexer can handle the given file.
        
        Args:
            file_path: Path to the file
            content_type: MIME type if known (optional)
        
        Returns:
            True if this indexer should be used for this file
        """
        ...
    
    def index(self, file_path: Path, context: Optional[Dict[str, Any]] = None) -> IndexResult:
        """Extract structured information from the media file.
        
        Args:
            file_path: Path to the media file
            context: Optional context (e.g., store for episodic persistence)
            
        Returns:
            IndexResult containing summary, hierarchy, symbols, metadata
            
        Raises:
            FileNotFoundError: if file doesn't exist
            ValueError: if file format not supported
            IndexError: if indexing fails
        """
        ...
    
    def extract_episodes(self, index_result: IndexResult) -> List[Dict[str, Any]]:
        """Convert index result into episodic memory entries.
        
        Each episode represents a learnable unit (function, section, concept).
        These episodes can be stored in Crisp Engine for long-term memory.
        
        Args:
            index_result: The result from index()
            
        Returns:
            List of episode data dicts (not MemoryEpisode objects)
        """
        ...


# Helper functions
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


def is_source_file(file_path: Path) -> bool:
    """Check if file is a source code file."""
    CODE_EXTENSIONS = {
        '.ts', '.tsx', '.js', '.jsx', '.py', '.java', '.go', '.rs',
        '.c', '.cpp', '.h', '.hpp', '.ino', '.swift', '.kt', '.scala'
    }
    return file_path.suffix in CODE_EXTENSIONS


def is_text_file(file_path: Path) -> bool:
    """Check if file is readable text (UTF-8)."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            f.read(1024)  # Try reading first 1KB
        return True
    except (UnicodeDecodeError, OSError):
        return False
