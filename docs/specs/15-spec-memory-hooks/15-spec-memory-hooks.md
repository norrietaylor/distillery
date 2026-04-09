# 15-spec-memory-hooks

## Introduction/Overview

Add a Claude Code hook script that periodically nudges the LLM to store important session knowledge. The UserPromptSubmit hook fires a gentle reminder every N prompts, catching information that would otherwise go unstored. Together with the SessionStart hook from spec 14, this covers the core session lifecycle automation from #191. PreCompact auto-extraction is deferred to a future spec.

Refs: [#191](https://github.com/norrietaylor/distillery/issues/191)

## Goals

1. Remind the LLM periodically to consider storing session knowledge, catching information that would otherwise go unstored
2. Provide a ready-to-install hook dispatcher script that routes Claude Code hook events
3. Lay the groundwork for future hooks (PreCompact, etc.) via the dispatcher pattern

## User Stories

- As a Claude Code user, I want periodic reminders to store knowledge so the session doesn't end with nothing captured
- As a developer setting up Distillery, I want a single dispatcher script I can register in `settings.json` that handles all hook events

## Demoable Units of Work

### Unit 1: Hook dispatcher and UserPromptSubmit nudge

**Purpose:** Create a single dispatcher script that routes hook events, and implement the periodic memory nudge that fires every N prompts.

**Functional Requirements:**

- The script shall be placed at `scripts/hooks/distillery-hooks.sh` as a single dispatcher
- The script shall read hook JSON from stdin, parsing `hook_event_name`, `session_id`, and `cwd`
- The script shall dispatch to handler functions based on `hook_event_name`: `UserPromptSubmit`, `PreCompact`, `SessionStart` (delegates to briefing hook from spec 14)
- The script shall use `set -euo pipefail` and exit silently on any error (hooks must never block the user)
- For `UserPromptSubmit`:
  - The script shall maintain a per-session prompt counter in `/tmp/distillery-prompt-count-$SESSION_ID`
  - The script shall output a memory nudge to stdout every 30 prompts (configurable via `DISTILLERY_NUDGE_INTERVAL`, default 30)
  - The nudge text shall be: `"[Distillery] You've exchanged {N} messages this session. Consider whether any decisions, insights, or corrections from this conversation should be stored with /distill."`
  - The script shall output nothing on non-nudge prompts (silent pass-through)
  - The counter file shall be created on first prompt and incremented atomically
- The script shall include a `DISTILLERY_MCP_URL` env var (default `http://localhost:8000/mcp`) for the MCP endpoint
- The script shall include a setup section in `scripts/hooks/README.md` explaining `settings.json` registration for all three hook events

**Proof Artifacts:**

- File: `scripts/hooks/distillery-hooks.sh` exists, is executable, handles UserPromptSubmit
- CLI: `echo '{"hook_event_name":"UserPromptSubmit","session_id":"test-123"}' | DISTILLERY_NUDGE_INTERVAL=1 bash scripts/hooks/distillery-hooks.sh` outputs nudge text
- CLI: Running the above 29 times with `DISTILLERY_NUDGE_INTERVAL=30` produces no output, then the 30th produces the nudge
- File: `scripts/hooks/README.md` documents setup for all hook events

### Unit 2: Integration test script

**Purpose:** Provide a test harness that validates hook behavior without requiring a live MCP server or Claude CLI.

**Functional Requirements:**

- The test script shall be placed at `scripts/hooks/test-hooks.sh`
- The test script shall verify:
  - UserPromptSubmit counter increments and fires at the configured interval
  - UserPromptSubmit outputs nothing on non-nudge prompts
  - SessionStart delegates correctly (or skips if briefing hook not present)
  - Unknown hook events are silently ignored (exit 0)
  - Counter file is created and cleaned up
- The test script shall be runnable with `bash scripts/hooks/test-hooks.sh` and report pass/fail

**Proof Artifacts:**

- File: `scripts/hooks/test-hooks.sh` exists and is executable
- CLI: `bash scripts/hooks/test-hooks.sh` exits 0 with all tests passing

## Non-Goals (Out of Scope)

- **PreCompact auto-extraction**: deferred to a future spec. Requires Haiku integration and MCP HTTP store calls — more complex than the nudge hook
- **Server-side changes**: no new MCP tools, migrations, or protocol changes
- **SessionStart hook implementation**: covered in spec 14 (briefing). The dispatcher routes to it but doesn't reimplement it
- **Windows support**: hooks are bash scripts targeting macOS/Linux

## Design Considerations

### Hook JSON Schema (from Claude Code)

```json
{
  "hook_event_name": "PreCompact|UserPromptSubmit|SessionStart",
  "session_id": "uuid-string",
  "transcript_path": "/path/to/conversation.txt",
  "cwd": "/path/to/working/directory"
}
```

### settings.json Registration

```json
{
  "hooks": {
    "UserPromptSubmit": [{"type": "command", "command": "bash /path/to/distillery-hooks.sh"}],
    "PreCompact": [{"type": "command", "command": "bash /path/to/distillery-hooks.sh"}],
    "SessionStart": [{"type": "command", "command": "bash /path/to/distillery-hooks.sh"}]
  }
}
```

## Repository Standards

- **Script location**: `scripts/hooks/` directory
- **Bash style**: `set -euo pipefail`, POSIX-compatible where possible, proper quoting
- **Commit format**: `feat(hooks): add UserPromptSubmit memory nudge`, `feat(hooks): add PreCompact auto-extraction`
- **Documentation**: `scripts/hooks/README.md` with setup, configuration, and troubleshooting

## Technical Considerations

- **Prompt counter**: uses `/tmp/distillery-prompt-count-$SESSION_ID` files. Atomic increment via `flock` to handle concurrent hook invocations. Auto-cleaned on reboot.
- **Silent failure**: all error paths exit 0 and write to stderr. A hook that blocks or errors disrupts the user's session.
- **Dispatcher extensibility**: the dispatcher uses a case statement on `hook_event_name`. Adding PreCompact later is a new case branch — no structural changes needed.

## Security Considerations

- `DISTILLERY_BEARER_TOKEN` (if used for future MCP HTTP hooks) should not be committed to version control. Document in README.
- The nudge hook outputs only static text — no sensitive data exposure.

## Success Metrics

- UserPromptSubmit nudge fires reliably every 30 prompts with zero false triggers
- Hook completes in under 1 second (it's just a counter check and optional stdout)
- Silent failure on all error paths — hooks never block the user's session

## Open Questions

No open questions at this time.
