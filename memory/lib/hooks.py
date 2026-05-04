"""Claude Code hook handlers for automatic memory capture.

Handles two call styles:

  Internal (Crisp Engine format) — hook_event_name field in JSON:
    FileChange, Stop, SessionEnd, ToolFailure

  Claude Code native — routed via sys.argv[1]:
    claude-post-tool   ← PostToolUse (Write/Edit/MultiEdit)
    claude-stop        ← Stop
    claude-session-end ← SessionEnd
    claude-pre-compact ← PreCompact

Install as `crisp-hook` via pyproject.toml entry point, then wire in
.claude/settings.json using "command": "crisp-hook".
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.analyzer import CodeAnalyzer
from lib.store import MemoryEpisode, MemoryStore

SOURCE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".c", ".cpp", ".h", ".ino"}


class MemoryHookHandler:
    """Handles Claude Code hook events for automatic memory capture."""

    def __init__(self, store: MemoryStore):
        self.store = store
        self.analyzer = CodeAnalyzer()

    # ── Claude Code native translators ────────────────────────────────────────

    def handle_claude_post_tool(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Translate PostToolUse payload → FileChange handler."""
        tool = data.get("tool_name", "")
        if tool not in ("Write", "Edit", "MultiEdit"):
            return {"status": "ignored", "reason": f"tool {tool} not tracked"}

        tool_input = data.get("tool_input", {})
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return {"status": "ignored", "reason": "no file_path"}

        if Path(file_path).suffix not in SOURCE_EXTENSIONS:
            return {"status": "ignored", "reason": "extension not tracked"}

        diff = self._git_diff(file_path)
        change_type = "create" if tool == "Write" else "edit"

        return self.handle_file_change({
            "session_id": data.get("session_id", "unknown"),
            "file_path": file_path,
            "change_type": change_type,
            "diff": diff,
        })

    def handle_claude_stop(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Translate Stop payload → Stop handler."""
        # Claude Code Stop payload already has session_id and message
        return self.handle_stop({
            "session_id": data.get("session_id", "unknown"),
            "message": data.get("message", ""),
            "tool_outputs": data.get("tool_outputs", []),
        })

    def handle_claude_transcript(self, data: Dict[str, Any], event: str) -> Dict[str, Any]:
        """Handle SessionEnd or PreCompact — capture transcript then cascade consolidation.

        Reads the JSONL transcript, saves last N turns as an L0 conversation
        episode, then runs the full L0→L1→L2→L3 cascade.
        """
        session_id = data.get("session_id", "unknown")
        transcript_path = data.get("transcript_path", "")

        result: Dict[str, Any] = {"event": event, "session_id": session_id}

        if transcript_path and Path(transcript_path).exists():
            context, turn_count = self._read_transcript(Path(transcript_path))
            if context and turn_count >= 3:
                ep = self._conversation_episode(session_id, context, turn_count)
                self.store.save_episode(ep)
                result["conversation_episode"] = ep.id
                result["turns_captured"] = turn_count

        # Full cascade: L0→L1→L2→L3
        from lib.reflector import MemoryReflector
        reflector = MemoryReflector(self.store)
        consolidation = reflector.consolidate()
        result["consolidation"] = consolidation

        return result

    # ── Internal Crisp Engine handlers ────────────────────────────────────────

    def handle_session_end(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle SessionEnd (internal format) — checkpoint + full cascade."""
        session_id = event_data.get("session_id", "unknown")
        all_episodes = self.store.list_episodes(layer=0)
        session_episodes = [ep for ep in all_episodes if ep.session_id == session_id]
        self._create_checkpoint(session_id, session_episodes)

        from lib.reflector import MemoryReflector
        reflector = MemoryReflector(self.store)
        consolidation = reflector.consolidate()

        return {
            "event": "SessionEnd",
            "session_id": session_id,
            "l0_count": len(session_episodes),
            "consolidation": consolidation,
        }

    def handle_stop(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Stop — detect corrections and frustration, save as L0."""
        message = event_data.get("message", "")
        tool_outputs = event_data.get("tool_outputs", [])
        result: Dict[str, Any] = {"event": "Stop"}

        correction = self._detect_correction(message, tool_outputs)
        if correction:
            ep = self._create_correction_episode(correction, event_data)
            self.store.save_episode(ep)
            result["correction"] = {"episode_id": ep.id}

        frustration = self._detect_frustration(message)
        if frustration:
            ep = self._create_frustration_episode(frustration, event_data)
            self.store.save_episode(ep)
            result["frustration"] = {"episode_id": ep.id}

        failures = self._detect_tool_failures(tool_outputs)
        for failure in failures:
            ep = self._create_failure_episode(failure, event_data)
            self.store.save_episode(ep)
        if failures:
            result["failures"] = len(failures)

        return result

    def handle_file_change(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle FileChange — capture diff + symbols as L0 episode."""
        file_path = event_data.get("file_path", "")
        if not file_path:
            return {"event": "FileChange", "error": "no file_path"}

        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
            content_hash = self.store.compute_hash(content)
        except Exception as e:
            return {"event": "FileChange", "error": str(e)}

        if self.store.get_file_state(file_path) == content_hash:
            return {"event": "FileChange", "unchanged": True}

        diff = event_data.get("diff", "")
        change_type = event_data.get("change_type", "edit")
        session_id = event_data.get("session_id", "unknown")

        code_elements = []
        if Path(file_path).suffix in SOURCE_EXTENSIONS:
            try:
                code_elements = self.analyzer.analyze_file(file_path)
            except Exception:
                pass

        lines = [f"File changed: {file_path}", f"Change type: {change_type}", ""]
        if diff:
            lines += ["## Diff", f"```diff\n{diff[:2000]}\n```", ""]
        if code_elements:
            lines += ["## Code Elements"] + [
                f"- `{e.signature}` ({e.type})" for e in code_elements[:15]
            ] + [""]

        episode_id = f"file_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        episode = MemoryEpisode(
            id=episode_id,
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            layer=0,
            title=f"File change: {Path(file_path).name}",
            content="\n".join(lines),
            source_type="file",
            source_path=file_path,
            source_hash=content_hash,
            category="code",
            importance=0.6,
            tags=["file_change", Path(file_path).suffix.lstrip(".")],
            context_snapshot={
                "change_type": change_type,
                "code_elements": len(code_elements),
                "diff_size": len(diff),
            },
        )

        saved = self.store.save_episode(episode)
        self.store.set_file_state(file_path, content_hash)
        return {"event": "FileChange", "episode_id": episode_id if saved else None, "duplicate": not saved}

    def handle_tool_failure(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle ToolFailure — save as high-importance L0 episode."""
        tool_name = event_data.get("tool_name", "unknown")
        error = event_data.get("error", "")
        tool_input = event_data.get("tool_input", {})

        content = f"Tool failure: {tool_name}\n\nError: {error}\n"
        if tool_input:
            content += f"\nInput: {json.dumps(tool_input, indent=2)}\n"

        episode_id = f"failure_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        episode = MemoryEpisode(
            id=episode_id,
            session_id=event_data.get("session_id", "unknown"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            layer=0,
            title=f"Tool failure: {tool_name}",
            content=content,
            source_type="tool",
            category="failure",
            importance=0.8,
            tags=["failure", tool_name],
            trigger_type="error_recovery",
            frustration_score=0.7,
            context_snapshot={"tool_name": tool_name, "error": error},
        )
        self.store.save_episode(episode)
        return {"event": "ToolFailure", "episode_id": episode_id}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _git_diff(self, file_path: str) -> str:
        """Get git diff for a file against HEAD."""
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD", "--", file_path],
                capture_output=True, text=True, timeout=5,
                cwd=str(Path(file_path).parent),
            )
            diff = result.stdout.strip()
            if not diff:
                # Unstaged new file
                result = subprocess.run(
                    ["git", "diff", "--", file_path],
                    capture_output=True, text=True, timeout=5,
                    cwd=str(Path(file_path).parent),
                )
                diff = result.stdout.strip()
            return diff
        except Exception:
            return ""

    def _read_transcript(self, path: Path, max_turns: int = 30) -> tuple:
        """Read JSONL transcript, return (markdown_text, turn_count)."""
        turns: List[str] = []
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = entry.get("message", {})
                    role = msg.get("role", "") if isinstance(msg, dict) else entry.get("role", "")
                    content = msg.get("content", "") if isinstance(msg, dict) else entry.get("content", "")

                    if role not in ("user", "assistant"):
                        continue

                    if isinstance(content, list):
                        content = "\n".join(
                            b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )

                    if isinstance(content, str) and content.strip():
                        label = "User" if role == "user" else "Assistant"
                        turns.append(f"**{label}:** {content.strip()}")
        except Exception:
            return "", 0

        recent = turns[-max_turns:]
        text = "\n\n".join(recent)
        if len(text) > 15000:
            text = text[-15000:]
        return text, len(recent)

    def _conversation_episode(self, session_id: str, context: str, turn_count: int) -> MemoryEpisode:
        """Create an L0 episode from a conversation transcript."""
        episode_id = f"conv_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        return MemoryEpisode(
            id=episode_id,
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            layer=0,
            title=f"Conversation: {session_id[:12]}",
            content=f"# Conversation Transcript\n\n{context}",
            source_type="conversation",
            category="conversation",
            importance=0.7,
            tags=["conversation", "transcript"],
            context_snapshot={"turns": turn_count},
        )

    def _detect_correction(self, message: str, tool_outputs: list) -> Optional[Dict]:
        msg = message.lower()
        patterns = [
            r"\bno\b", r"\bwrong\b", r"\bdon'?t\b", r"\bincorrect\b",
            r"\bthat'?s wrong\b", r"\bnot right\b", r"\bfix\b",
        ]
        for p in patterns:
            if re.search(p, msg):
                return {"type": "explicit", "message": message, "pattern": p}
        for output in tool_outputs:
            if isinstance(output, dict) and output.get("error"):
                return {"type": "tool_error", "error": output["error"]}
        return None

    def _detect_frustration(self, message: str) -> Optional[Dict]:
        msg = message.lower()
        patterns = [r"\bugh\b", r"\bagain\b", r"\bstill\b", r"\bnot working\b",
                    r"\bdoesn'?t work\b", r"\bargh\b", r"\bfrustrat\b", r"\bannoying\b"]
        matches = [p for p in patterns if re.search(p, msg)]
        if matches:
            return {"patterns": matches, "message": message, "score": min(1.0, len(matches) * 0.3)}
        return None

    def _detect_tool_failures(self, tool_outputs: list) -> list:
        return [o for o in tool_outputs
                if isinstance(o, dict) and (o.get("error") or o.get("status") == "error")]

    def _create_correction_episode(self, correction: Dict, event_data: Dict) -> MemoryEpisode:
        delta = correction.get("message") or correction.get("error", "")
        return MemoryEpisode(
            id=f"correction_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            session_id=event_data.get("session_id", "unknown"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            layer=0, title="Correction applied",
            content=f"User correction: {delta}",
            category="correction", importance=1.0,
            tags=["correction", "learning"],
            correction_applied=True, correction_delta=delta,
            is_permanent=True, trigger_type="reaction",
            user_sentiment="negative",
            lesson=f"Learned from correction: {delta[:100]}",
        )

    def _create_frustration_episode(self, frustration: Dict, event_data: Dict) -> MemoryEpisode:
        return MemoryEpisode(
            id=f"frustration_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            session_id=event_data.get("session_id", "unknown"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            layer=0, title="User frustration detected",
            content=f"Signals: {', '.join(frustration['patterns'])}\n\n{frustration['message']}",
            category="frustration", importance=0.7,
            tags=["frustration"], frustration_score=frustration["score"],
            user_sentiment="negative", trigger_type="reaction",
            lesson="User experienced frustration — consider different approach",
        )

    def _create_failure_episode(self, failure: Dict, event_data: Dict) -> MemoryEpisode:
        tool_name = failure.get("tool_name", "unknown")
        error = failure.get("error", "")
        return MemoryEpisode(
            id=f"failure_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            session_id=event_data.get("session_id", "unknown"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            layer=0, title=f"Tool failure: {tool_name}",
            content=f"Error: {error}\nTool: {tool_name}",
            category="failure", importance=0.8,
            tags=["failure", tool_name],
            trigger_type="error_recovery", root_cause=error,
            lesson=f"Tool {tool_name} failed — investigate root cause",
        )

    def _create_checkpoint(self, session_id: str, episodes: list):
        categories: Dict[str, int] = {}
        for ep in episodes:
            cat = ep.category or "uncategorized"
            categories[cat] = categories.get(cat, 0) + 1

        content = f"Session checkpoint: {session_id}\nTotal: {len(episodes)}\n\n"
        content += "\n".join(f"- {c}: {n}" for c, n in categories.items())

        self.store.save_episode(MemoryEpisode(
            id=f"checkpoint_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            layer=0, title=f"Checkpoint: {session_id}",
            content=content, category="checkpoint", importance=0.5,
            tags=["checkpoint"],
            context_snapshot={"episode_count": len(episodes), "categories": categories},
        ))


def main():
    """Entry point for crisp-hook command.

    Routing:
      crisp-hook claude-post-tool    ← PostToolUse (Write/Edit/MultiEdit)
      crisp-hook claude-stop         ← Stop
      crisp-hook claude-session-end  ← SessionEnd
      crisp-hook claude-pre-compact  ← PreCompact
      crisp-hook                     ← internal format (hook_event_name field)
    """
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, EOFError, ValueError):
        print(json.dumps({"error": "invalid stdin"}))
        return

    base_path = Path.home() / ".claude" / "memory"
    store = MemoryStore(str(base_path))
    handler = MemoryHookHandler(store)

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    result: Dict[str, Any] = {"status": "ok"}

    try:
        if cmd == "claude-post-tool":
            result.update(handler.handle_claude_post_tool(data))

        elif cmd == "claude-stop":
            result.update(handler.handle_claude_stop(data))

        elif cmd == "claude-session-end":
            result.update(handler.handle_claude_transcript(data, "SessionEnd"))

        elif cmd == "claude-pre-compact":
            result.update(handler.handle_claude_transcript(data, "PreCompact"))

        else:
            # Internal Crisp Engine format
            event = data.get("hook_event_name", "")
            if event == "SessionEnd":
                result.update(handler.handle_session_end(data))
            elif event == "Stop":
                result.update(handler.handle_stop(data))
            elif event == "FileChange":
                result.update(handler.handle_file_change(data))
            elif event == "ToolFailure":
                result.update(handler.handle_tool_failure(data))
            else:
                result["status"] = "ignored"

    except Exception as e:
        import traceback
        result["status"] = "error"
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
