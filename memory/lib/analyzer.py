"""Tree-sitter based code analysis for extracting functions, classes, and structure."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CodeElement:
    """Represents a code element (function, class, method, etc.)."""

    id: str
    name: str
    type: str  # function, class, method, module, variable
    language: str
    file_path: str
    start_line: int
    end_line: int
    signature: str = ""
    docstring: str = ""
    body: str = ""
    full_content: str = ""
    complexity: int = 1
    dependencies: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    hash: str = ""

    def compute_hash(self) -> str:
        """Compute hash of the element's body."""
        if not self.hash and self.body:
            self.hash = hashlib.sha256(self.body.encode()).hexdigest()[:16]
        return self.hash


class CodeAnalyzer:
    """Analyzes source code files to extract structure without tree-sitter fallback."""

    # Language-specific patterns
    PATTERNS = {
        "python": {
            "class": re.compile(r"^\s*class\s+(\w+)(?:\s*\(([^)]*)\))?:\s*"),
            "function": re.compile(
                r"^\s*def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*[^:]+)?:\s*"
            ),
            "async_function": re.compile(
                r"^\s*async\s+def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*[^:]+)?:\s*"
            ),
            "decorator": re.compile(r"^\s*@\s*(\w+(?:\.\w+)*)\s*$"),
            "import": re.compile(r"^\s*(?:import|from)\s+(\S+)"),
        },
        "javascript": {
            "class": re.compile(r"^\s*class\s+(\w+)\s*(?:extends\s+\w+)?\s*{?\s*$"),
            "function": re.compile(
                r"^\s*(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)\s*{?\s*$"
            ),
            "arrow_function": re.compile(
                r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>\s*{?\s*$"
            ),
            "method": re.compile(r"^\s*(\w+)\s*\(([^)]*)\)\s*{?\s*$"),
        },
        "typescript": {
            "class": re.compile(
                r"^\s*class\s+(\w+)\s*(?:extends\s+\w+)?\s*(?:implements\s+[^\s]+)?\s*{?\s*$"
            ),
            "function": re.compile(
                r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)\s*(?::\s*[^\s]+)?\s*{?\s*$"
            ),
            "arrow_function": re.compile(
                r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*(?::\s*[^\s]+)?\s*=>\s*{?\s*$"
            ),
        },
        "java": {
            "class": re.compile(
                r"^\s*(?:public|private|protected)?\s*(?:abstract\s+)?class\s+(\w+)\s*(?:extends\s+\w+)?\s*(?:implements\s+[^\s]+)?\s*{?\s*$"
            ),
            "method": re.compile(
                r"^\s*(?:public|private|protected|static|final|synchronized|native|abstract|transient)+[\s\w<>\[\]]*\s+(\w+)\s*\(([^)]*)\)\s*(?::\s*[^\s]+)?\s*{?\s*$"
            ),
        },
        "go": {
            "function": re.compile(
                r"^\s*func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(([^)]*)\)\s*(?:\([^)]*\))?\s*{?\s*$"
            ),
            "type": re.compile(r"^\s*type\s+(\w+)\s+struct\s*{?\s*$"),
        },
        "rust": {
            "function": re.compile(
                r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*[^\s]+)?\s*{?\s*$"
            ),
            "struct": re.compile(r"^\s*(?:pub\s+)?struct\s+(\w+)\s*{?\s*$"),
        },
        "c_cpp": {
            "function": re.compile(
                r"^\s*(?:static\s+)?(?:inline\s+)?(?:[\w:]+\s+)+\*?\s*(\w+)\s*\(([^)]*)\)\s*{?\s*$"
            ),
            "struct": re.compile(r"^\s*struct\s+(\w+)\s*{?\s*$"),
        },
    }

    LANGUAGE_EXTENSIONS = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".c": "c_cpp",
        ".cpp": "c_cpp",
        ".h": "c_cpp",
        ".hpp": "c_cpp",
    }

    def __init__(self):
        self.element_id_counter = 0

    def _get_language(self, file_path: str) -> Optional[str]:
        """Determine language from file extension."""
        ext = Path(file_path).suffix.lower()
        return self.LANGUAGE_EXTENSIONS.get(ext)

    def _next_id(self) -> str:
        """Generate unique element ID."""
        self.element_id_counter += 1
        return f"elem_{self.element_id_counter}"

    def _extract_python_structure(
        self, lines: List[str], file_path: str
    ) -> List[CodeElement]:
        """Extract Python code structure."""
        elements = []
        i = 0
        current_class = None
        current_decorators = []

        while i < len(lines):
            line = lines[i]
            stripped = line.rstrip()

            # Decorator
            dec_match = self.PATTERNS["python"]["decorator"].match(stripped)
            if dec_match:
                current_decorators.append(dec_match.group(1))
                i += 1
                continue

            # Class
            class_match = self.PATTERNS["python"]["class"].match(stripped)
            if class_match:
                class_name = class_match.group(1)
                bases = class_match.group(2) or ""
                start_line = i

                # Find class body
                indent = len(line) - len(line.lstrip())
                body_lines = []
                j = i + 1
                class_methods = []

                while j < len(lines):
                    next_line = lines[j]
                    if (
                        next_line.strip()
                        and not next_line.startswith(" " * (indent + 1))
                        and not next_line.startswith("\t")
                    ):
                        if next_line.strip().startswith("@"):
                            pass  # Decorator at same indent level
                        else:
                            break
                    body_lines.append(next_line)

                    # Check for methods inside class
                    method_match = self.PATTERNS["python"]["function"].match(
                        next_line.rstrip()
                    )
                    async_match = self.PATTERNS["python"]["async_function"].match(
                        next_line.rstrip()
                    )
                    if method_match or async_match:
                        match = method_match or async_match
                        method_name = match.group(1)
                        method_args = match.group(2)
                        method_start = j

                        # Find method body
                        method_indent = len(next_line) - len(next_line.lstrip())
                        method_body_lines = [next_line]
                        k = j + 1
                        while k < len(lines):
                            ml = lines[k]
                            if (
                                ml.strip()
                                and not ml.startswith(" " * (method_indent + 1))
                                and not ml.startswith("\t")
                            ):
                                if not ml.strip().startswith("@"):
                                    break
                            method_body_lines.append(ml)
                            k += 1

                        method_body = "".join(method_body_lines)
                        docstring = self._extract_docstring(method_body_lines)

                        elem = CodeElement(
                            id=self._next_id(),
                            name=method_name,
                            type="method",
                            language="python",
                            file_path=file_path,
                            start_line=method_start,
                            end_line=k - 1,
                            signature=f"def {method_name}({method_args})",
                            docstring=docstring,
                            body=method_body,
                            full_content=method_body,
                        )
                        class_methods.append(elem)
                        j = k - 1

                    j += 1

                class_body = "".join(body_lines)
                docstring = self._extract_docstring(body_lines)

                class_elem = CodeElement(
                    id=self._next_id(),
                    name=class_name,
                    type="class",
                    language="python",
                    file_path=file_path,
                    start_line=start_line,
                    end_line=i + len(body_lines),
                    signature=f"class {class_name}({bases})",
                    docstring=docstring,
                    body=class_body,
                    full_content=class_body,
                    dependencies=[bases] if bases else [],
                )
                elements.append(class_elem)
                elements.extend(class_methods)

                current_class = class_name
                i += len(body_lines)
                current_decorators = []
                continue

            # Function (module-level)
            func_match = self.PATTERNS["python"]["function"].match(stripped)
            async_match = self.PATTERNS["python"]["async_function"].match(stripped)
            if func_match or async_match:
                match = func_match or async_match
                func_name = match.group(1)
                func_args = match.group(2)
                start_line = i

                # Skip if inside class (already handled)
                if current_class:
                    i += 1
                    continue

                # Find function body
                indent = len(line) - len(line.lstrip())
                body_lines = [line]
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if (
                        next_line.strip()
                        and not next_line.startswith(" " * (indent + 1))
                        and not next_line.startswith("\t")
                    ):
                        if not next_line.strip().startswith("@"):
                            break
                    body_lines.append(next_line)
                    j += 1

                func_body = "".join(body_lines)
                docstring = self._extract_docstring(body_lines)

                elem = CodeElement(
                    id=self._next_id(),
                    name=func_name,
                    type="function",
                    language="python",
                    file_path=file_path,
                    start_line=start_line,
                    end_line=j - 1,
                    signature=f"def {func_name}({func_args})",
                    docstring=docstring,
                    body=func_body,
                    full_content=func_body,
                )
                elements.append(elem)

                i = j
                current_decorators = []
                continue

            i += 1

        return elements

    def _extract_docstring(self, lines: List[str]) -> str:
        """Extract docstring from lines."""
        if not lines:
            return ""
        # Look for triple-quoted string after first line
        in_docstring = False
        docstring_lines = []
        quote_char = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if i == 0:
                continue  # Skip def/class line

            # Check for opening triple quotes
            if '"""' in stripped or "'''" in stripped:
                quote = '"""' if '"""' in stripped else "'''"
                if not in_docstring:
                    in_docstring = True
                    quote_char = quote
                    # Extract content after opening quote
                    parts = stripped.split(quote, 1)
                    if len(parts) > 1:
                        content = parts[1]
                        if content.endswith(quote):
                            docstring_lines.append(content[:-3])
                            in_docstring = False
                        else:
                            docstring_lines.append(content)
                    continue
                else:
                    # Closing quote
                    if quote_char and quote in stripped:
                        parts = stripped.split(quote, 1)
                        docstring_lines.append(parts[0])
                        in_docstring = False
                    continue

            if in_docstring:
                docstring_lines.append(stripped)

        return "\n".join(docstring_lines).strip()

    def _extract_generic_structure(
        self, lines: List[str], file_path: str, language: str
    ) -> List[CodeElement]:
        """Generic structure extraction for non-Python languages."""
        elements = []
        if language not in self.PATTERNS:
            return elements

        patterns = self.PATTERNS[language]
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.rstrip()

            # Try each pattern type
            for elem_type, pattern in patterns.items():
                match = pattern.match(stripped)
                if match:
                    name = match.group(1)
                    args = match.group(2) if match.lastindex > 1 else ""
                    start_line = i

                    # Find body (simplified: look for matching braces)
                    body_lines = [line]
                    brace_count = line.count("{") - line.count("}")
                    j = i + 1

                    while j < len(lines) and brace_count > 0:
                        body_lines.append(lines[j])
                        brace_count += lines[j].count("{") - lines[j].count("}")
                        j += 1

                    if brace_count == 0 and j > i + 1:
                        # Include closing brace line
                        if j < len(lines):
                            body_lines.append(lines[j])
                            j += 1

                    body = "".join(body_lines)

                    elem = CodeElement(
                        id=self._next_id(),
                        name=name,
                        type=elem_type,
                        language=language,
                        file_path=file_path,
                        start_line=start_line,
                        end_line=j - 1,
                        signature=f"{elem_type} {name}",
                        body=body,
                        full_content=body,
                    )
                    elements.append(elem)

                    i = j - 1
                    break

            i += 1

        return elements

    def analyze_file(self, file_path: str) -> List[CodeElement]:
        """Analyze a source file and extract all code elements."""
        file_path = str(Path(file_path).resolve())
        language = self._get_language(file_path)

        if not language:
            return []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return []

        lines = content.splitlines()

        if language == "python":
            elements = self._extract_python_structure(lines, file_path)
        else:
            elements = self._extract_generic_structure(lines, file_path, language)

        # Compute hashes
        for elem in elements:
            elem.compute_hash()

        return elements

    def analyze_directory(
        self, directory: str, extensions: Optional[List[str]] = None
    ) -> Dict[str, List[CodeElement]]:
        """Analyze all source files in a directory."""
        directory = str(Path(directory).resolve())
        if extensions is None:
            extensions = list(self.LANGUAGE_EXTENSIONS.keys())

        results = {}
        for ext in extensions:
            for fp in Path(directory).rglob(f"*{ext}"):
                elements = self.analyze_file(str(fp))
                if elements:
                    results[str(fp)] = elements

        return results
