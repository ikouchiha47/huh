# Claude Code Hook Configuration

This file documents how to configure Crisp Engine hooks in Claude Code.

## Hook Events Supported

| Event | When It Fires | What Crisp Engine Does |
|-------|---------------|----------------------|
| `SessionEnd` | Claude session closes | Creates checkpoint + triggers consolidation if ≥20 L0 episodes |
| `Stop` | Claude finishes a turn | Analyzes for corrections/frustration/tool failures |
| `FileChange` | File is written/edited | Captures diff, extracts code elements, stores as L0 |
| `ToolFailure` | Tool call errors | Records failure with high importance |

## Installation

### 1. Copy Hook Handler

```bash
# Ensure the hook handler is executable
chmod +x /Users/darksied/dev/ideas/huh/memory/lib/hooks.py

# Or install as command
ln -s /Users/darksied/dev/ideas/huh/memory/memory_cli.py /usr/local/bin/memory
```

### 2. Configure `.claude/settings.json`

Create or edit `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {},
  "effortLevel": "medium",
  "skipDangerousModePermissionPrompt": true,
  "hooks": {
    "SessionEnd": {
      "type": "command",
      "description": "Create memory checkpoint at session end",
      "command": "memory",
      "args": ["hook", "SessionEnd"],
      "timeout": 30000
    },
    "Stop": {
      "type": "agent",
      "description": "Detect corrections and frustration",
      "agent": "memory",
      "matcher": "correction|frustration|failure"
    },
    "FileChange": {
      "type": "command",
      "description": "Capture file edits",
      "command": "memory",
      "args": ["hook", "FileChange"],
      "timeout": 15000
    },
    "ToolFailure": {
      "type": "command",
      "description": "Record tool failures",
      "command": "memory",
      "args": ["hook", "ToolFailure"],
      "timeout": 10000
    }
  }
}
```

**Hook types:**
- `command` — Runs external command, passes JSON via stdin
- `agent` — Invokes Claude agent with specific prompt/matcher
- `http` — Sends HTTP POST to endpoint

### 3. Project-Specific Hooks

In your project directory, create `.claude/settings.json`:

```json
{
  "hooks": {
    "FileChange": {
      "command": "memory",
      "args": ["capture-file", "--project", "myproject"]
    }
  }
}
```

Project settings merge with global settings.

---

## How Hooks Work

### Hook Invocation Format

Claude Code sends JSON to the command's stdin:

```json
{
  "hook_event_name": "FileChange",
  "timestamp": "2026-05-01T12:30:00Z",
  "session_id": "sess_abc123",
  "data": {
    "file_path": "/project/src/auth.py",
    "change_type": "edit",
    "diff": "@@ -10,7 +10,7 @@\n-def verify(token):\n+def verify(token: str) -> bool:",
    "project_root": "/project"
  }
}
```

**Crisp Engine hook handler** reads stdin, processes event, writes JSON result to stdout:

```json
{
  "event": "FileChange",
  "status": "ok",
  "episode_id": "file_20260501_124552",
  "code_elements": 2,
  "duplicate": false
}
```

---

## Testing Hooks

### Manual Hook Test

```bash
# Simulate SessionEnd
echo '{"hook_event_name":"SessionEnd","session_id":"test_123"}' | \
  python3 /Users/darksied/dev/ideas/huh/memory/lib/hooks.py

# Simulate FileChange
echo '{"hook_event_name":"FileChange","session_id":"test_123","data":{"file_path":"/tmp/test.py","change_type":"edit","diff":"+"}}' | \
  python3 /Users/darksied/dev/ideas/huh/memory/lib/hooks.py

# Simulate ToolFailure
echo '{"hook_event_name":"ToolFailure","session_id":"test_123","data":{"tool_name":"read","error":"File not found"}}' | \
  python3 /Users/darksied/dev/ideas/huh/memory/lib/hooks.py
```

### Auto-Test Mode

```bash
cd /Users/darksied/dev/ideas/huh/memory
python3 -m lib.hooks --test
```

Runs all hook simulations and reports success/failure.

---

## Hook Payload Reference

### SessionEnd
```json
{
  "hook_event_name": "SessionEnd",
  "session_id": "string",
  "timestamp": "ISO8601",
  "duration_seconds": 1205
}
```

**Crisp Engine action:**
1. Count L0 episodes for this session
2. Create checkpoint episode (always)
3. If count ≥ 20: run L0→L1 consolidation

---

### Stop
```json
{
  "hook_event_name": "Stop",
  "session_id": "string",
  "timestamp": "ISO8601",
  "message": "User's latest message",
  "tool_outputs": [...],
  "turn_number": 42
}
```

**Crisp Engine action:**
1. Run correction detection (regex patterns)
2. Run frustration detection (regex patterns)
3. Scan tool outputs for failures
4. Create L0 episodes for each detected signal

---

### FileChange
```json
{
  "hook_event_name": "FileChange",
  "session_id": "string",
  "timestamp": "ISO8601",
  "data": {
    "file_path": "string",
    "change_type": "create|edit|delete|rename",
    "diff": "string (git diff format)",
    "old_content": "string (optional)",
    "new_content": "string (optional)",
    "project_root": "string"
  }
}
```

**Crisp Engine action:**
1. Hash file content → content_hash
2. Check file_states (has this file changed?)
   - If unchanged → increment access on existing episode
   - If changed → continue
3. Extract code elements via CodeAnalyzer
4. Create L0 episode with diff + code elements
5. Update file_states[path_hash] = content_hash
6. Add A-MEM links to similar episodes

---

### ToolFailure
```json
{
  "hook_event_name": "ToolFailure",
  "session_id": "string",
  "timestamp": "ISO8601",
  "data": {
    "tool_name": "string",
    "error": "string",
    "tool_input": {...},
    "retry_count": 0
  }
}
```

**Crisp Engine action:**
1. Create L0 failure episode
2. Tag with tool name
3. Set importance=0.8 (high)
4. Set frustration_score=0.7
5. Store root_cause=error message

---

## Hook Filtering & Rate Limiting

### Per-Hook Throttling

To avoid spam, hooks can be rate-limited:

```python
# In hooks.py, add decorator or check:
LAST_HOOK_TIMES = {}

def should_fire(hook_name, cooldown_seconds):
    now = time.time()
    last = LAST_HOOK_TIMES.get(hook_name, 0)
    if now - last < cooldown_seconds:
        return False
    LAST_HOOK_TIMES[hook_name] = now
    return True

# Example cooldowns:
# - FileChange: 2s (rapid edits coalesced)
# - Stop: 0s (every turn)
# - SessionEnd: 0s (always)
# - ToolFailure: 1s (burst protection)
```

---

## Debugging Hook Issues

### 1. Check Hook Registration

```bash
# Verify Claude sees hooks
claude-code --list-hooks
# Should show: SessionEnd, Stop, FileChange, ToolFailure
```

### 2. Check Permissions

```bash
# Ensure hook script is executable
ls -la /Users/darksied/dev/ideas/huh/memory/lib/hooks.py
# Should have: -rwxr-xr-x

# Or if using wrapper:
chmod +x /usr/local/bin/memory
```

### 3. Test Hook Manually

```bash
# Pipe test JSON to handler
cat test_payload.json | python3 lib/hooks.py
```

### 4. View Hook Logs

Crisp Engine logs to `~/.claude/memory/logs/` (if enabled):

```bash
tail -f ~/.claude/memory/logs/hooks.log
```

---

## Advanced: Custom Hook Handlers

You can write custom hook handlers in any language. The contract:

**Input:** JSON on stdin
**Output:** JSON on stdout (with `"status": "ok"` or `"status": "error"`)

Example (bash):
```bash
#!/bin/bash
read INPUT
echo "{\"status\":\"ok\",\"received\":$INPUT}" > /tmp/hook_out.json
```

Configure:
```json
{
  "hooks": {
    "FileChange": {
      "type": "command",
      "command": "/path/to/custom_hook.sh"
    }
  }
}
```

---

## Integration with Crisp Engine Flow

```python
# hooks.py entry point
def main():
    data = json.load(sys.stdin)
    event = data.get("hook_event_name")
    
    store = MemoryStore()  # global or per-project
    handler = MemoryHookHandler(store)
    
    if event == "SessionEnd":
        result = handler.handle_session_end(data)
    elif event == "Stop":
        result = handler.handle_stop(data)
    elif event == "FileChange":
        result = handler.handle_file_change(data)
    elif event == "ToolFailure":
        result = handler.handle_tool_failure(data)
    
    print(json.dumps(result))
```

Each handler:
1. Extracts relevant info from event
2. Creates MemoryEpisode with appropriate metadata
3. Calls `store.save_episode(episode)`
4. Returns result dict

---

## Performance Considerations

### Hook Latency Targets

| Hook | Target Latency | Current |
|------|---------------|---------|
| FileChange | <50ms | ~20ms |
| Stop | <30ms | ~5ms |
| ToolFailure | <20ms | ~3ms |
| SessionEnd | <2s | ~500ms (due to consolidation) |

### Optimization Strategies

1. **Batch FileChange** — Coalesce rapid edits into one episode
2. **Async Processing** — Offload to background thread (except ToolFailure)
3. **Lazy Analysis** — Defer code analysis to reflection phase
4. **Cache Code Elements** — Don't re-extract unchanged functions

---

## Troubleshooting

**Hooks not firing?**
1. Check `~/.claude/settings.json` syntax (use JSON validator)
2. Ensure `command` paths are absolute or in PATH
3. Test manually: `echo '{}' | python3 lib/hooks.py`

**Duplicates?**
- Verify hash_cache is being updated
- Check content hashing includes full episode body

**No episodes created?**
- Enable debug logging: set `DEBUG=1` environment variable
- Check `~/.claude/memory/cache/hashes.json` for activity

**Permissions error?**
- Ensure `~/.claude/memory/` is writable
- Ensure hook scripts are executable

---

## Next Steps (Phase 5)

- [ ] Add hook for `PreToolUse` (capture intent before tool call)
- [ ] Add hook for `CwdChanged` (track working directory changes)
- [ ] Add hook for `ShellCommand` (capture terminal commands)
- [ ] Implement `AutoConsolidate` background job
- [ ] Add `MemoryHooks` config section for tuning thresholds

---

**Reference:** Original plan at `.kilo/plans/1777628646712-crisp-engine.md`
