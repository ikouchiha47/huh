"""Code media indexer using Crisp Engine's CodeAnalyzer.

Extracts functions, classes, methods, and their relationships from
source code files. Supports tree-sitter (if available) or regex fallback.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from .indexer_common import IMediaIndexer, IndexResult, compute_file_hash, is_source_file


class CodeIndexer(IMediaIndexer):
    """Indexer for source code files.
    
    Extracts:
    - Functions (module-level and methods)
    - Classes with their methods
    - Constants and variables
    - Docstrings and signatures
    - Complexity metrics (if available)
    
    Generates:
    - Summary: type/name count description
    - Hierarchy: nested class/method structure
    - Symbols: flat list with line numbers
    """
    
    # Order matters: more specific first
    SUPPORTED_EXTENSIONS = {
        '.ts', '.tsx', '.js', '.jsx',  # JavaScript/TypeScript
        '.py',                         # Python
        '.java',                       # Java
        '.go',                         # Go
        '.rs',                         # Rust
        '.c', '.cpp', '.h', '.hpp',   # C/C++
        '.swift',                      # Swift
        '.kt',                         # Kotlin
        '.scala',                      # Scala
        '.ino',                        # Arduino
    }
    
    def can_index(self, file_path: Path, content_type: str = None) -> bool:
        """Check if file is a recognized source code type."""
        return is_source_file(file_path)
    
    def index(self, file_path: Path, context: Optional[Dict[str, Any]] = None) -> IndexResult:
        """Extract symbols and generate summary from source code."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Use Crisp Engine's CodeAnalyzer
        analyzer = CodeAnalyzer()
        elements = analyzer.analyze_file(str(file_path))
        
        # Build hierarchy from elements
        hierarchy = self._build_hierarchy(elements)
        
        # Convert elements to symbol dicts
        symbols = [self._element_to_symbol(e) for e in elements]
        
        # Generate summary
        summary = self._generate_summary(elements, file_path)
        
        # Metadata
        metadata = {
            "language": file_path.suffix.lstrip('.'),
            "element_count": len(elements),
            "file_size_bytes": file_path.stat().st_size,
        }
        
        # Add complexity stats if available
        complexities = [e.metadata.get("complexity", 1) for e in elements if hasattr(e, 'metadata')]
        if complexities:
            metadata["avg_complexity"] = sum(complexities) / len(complexities)
        
        return IndexResult(
            media_type="code",
            file_path=file_path,
            content_hash=compute_file_hash(file_path),
            summary=summary,
            hierarchy=hierarchy,
            symbols=symbols,
            metadata=metadata
        )
    
    def _build_hierarchy(self, elements: List[Any]) -> Dict[str, Any]:
        """Build nested hierarchy from flat element list.
        
        Groups classes with their methods, functions at module level.
        """
        classes = {}
        functions = []
        standalone = []
        
        for elem in elements:
            if elem.type == "class":
                classes[elem.name] = {
                    "name": elem.name,
                    "line_start": elem.start_line,
                    "line_end": elem.end_line,
                    "signature": elem.signature,
                    "docstring": elem.docstring or "",
                    "methods": [],
                    "nested_classes": [],
                }
            elif elem.type == "method":
                # Find parent class (look for enclosing class in nearby elements)
                parent = self._find_parent_class(elem, elements)
                if parent and parent.name in classes:
                    classes[parent.name]["methods"].append(self._element_to_symbol(elem, include_body=False))
                else:
                    standalone.append(self._element_to_symbol(elem))
            elif elem.type == "function":
                functions.append(self._element_to_symbol(elem))
            else:
                standalone.append(self._element_to_symbol(elem))
        
        # Build final hierarchy
        hierarchy = {
            "classes": list(classes.values()),
            "functions": functions,
            "standalone": standalone,
        }
        
        return hierarchy
    
    def _find_parent_class(self, method_elem: Any, all_elements: List[Any]) -> Optional[Any]:
        """Find the class that likely contains this method."""
        # Simple heuristic: look for class that encloses method's line range
        method_end = method_elem.end_line
        for elem in all_elements:
            if elem.type == "class":
                if elem.start_line < method_elem.start_line and elem.end_line >= method_end:
                    return elem
        return None
    
    def _element_to_symbol(self, elem: Any, include_body: bool = True) -> Dict[str, Any]:
        """Convert CodeElement to symbol dict."""
        symbol = {
            "id": elem.id,
            "name": elem.name,
            "type": elem.type,
            "line_start": elem.start_line,
            "line_end": elem.end_line,
            "signature": elem.signature,
            "docstring": elem.docstring or "",
        }
        
        if include_body and hasattr(elem, 'body'):
            symbol["body"] = elem.body[:500]  # truncate large bodies
        
        # Include any additional metadata
        if hasattr(elem, 'metadata') and elem.metadata:
            symbol["metadata"] = elem.metadata
        
        return symbol
    
    def _generate_summary(self, elements: List[Any], file_path: Path) -> str:
        """Generate 2-3 sentence summary of the file."""
        if not elements:
            return f"{file_path.name} - no code elements detected"
        
        # Count by type
        by_type = {}
        for elem in elements:
            by_type[elem.type] = by_type.get(elem.type, 0) + 1
        
        # Build description
        parts = []
        if "class" in by_type:
            parts.append(f"{by_type['class']} class(es)")
        if "function" in by_type:
            parts.append(f"{by_type['function']} function(s)")
        if "method" in by_type:
            parts.append(f"{by_type['method']} method(s)")
        if "constant" in by_type:
            parts.append(f"{by_type['constant']} constant(s)")
        
        if parts:
            summary = f"{file_path.name} defines " + ", ".join(parts) + "."
            if len(elements) > 10:
                summary += f" Total: {len(elements)} symbols extracted."
            return summary
        else:
            return f"{file_path.name} - {len(elements)} symbols found"

    def extract_episodes(self, index_result: IndexResult) -> List[Dict[str, Any]]:
        """Convert code symbols into episodic memory entries.
        
        Each class/function becomes a learnable episode with:
        - Signature as content
        - Importance based on complexity/publicness
        - Linked to file source
        """
        episodes = []
        file_str = str(index_result.file_path)
        timestamp = self._now_iso()
        
        for symbol in index_result.symbols:
            # Only create episodes for non-trivial symbols
            if symbol["type"] in ("class", "function", "method"):
                importance = 0.5
                if symbol["type"] == "class":
                    importance = 0.7
                if len(symbol.get("docstring", "")) > 50:
                    importance += 0.2
                
                episode = {
                    "id": f"code_{index_result.content_hash[:8]}_{symbol['name']}",
                    "layer": 0,
                    "timestamp": timestamp,
                    "title": f"{symbol['type'].title()}: {symbol['name']}",
                    "content": f"```{index_result.metadata.get('language', '')}\n{symbol['signature']}\n```\n\n{symbol.get('docstring', 'No documentation.')}",
                    "category": "code_element",
                    "tags": [symbol["type"], index_result.metadata.get("language", "")],
                    "importance": importance,
                    "source_type": "code",
                    "source_path": file_str,
                    "source_hash": index_result.content_hash,
                    "context_snapshot": {
                        "line_start": symbol["line_start"],
                        "line_end": symbol["line_end"],
                        "file": index_result.file_path.name,
                    },
                }
                episodes.append(episode)
        
        return episodes
    
    @staticmethod
    def _now_iso() -> str:
        """Current timestamp in ISO format."""
        from datetime import datetime
        try:
            from datetime import timezone
            return datetime.now(timezone.utc).isoformat()
        except ImportError:
            return datetime.utcnow().isoformat() + "Z"
