# Distillery Hook Scripts

This directory contains Claude Code hook scripts for Distillery integration.

## Automatic Setup (recommended)

Run `/setup` after installing the Distillery plugin. It detects your plugin
installation scope (user or project) and configures hooks in the appropriate
`settings.json` automatically.

> **Why not plugin.json?** Plugin manifest hooks only support `SessionStart`
> and `Stop` events. `UserPromptSubmit` is silently ignored by the plugin
> system, so these hooks must be registered in `settings.json`.

## distillery-hooks.sh

A single **dispatcher script** that routes all Claude Code hook events to the
appropriate Distillery handler. Register this one script for `UserPromptSubmit`,
`PreCompact`, and `SessionStart` — no need to manage multiple hook entries.

### Hook Events

| Hook Event | Behaviour |
|---|---|
| `UserPromptSubmit` | Outputs a memory nudge every N prompts (default 30) |
| `PreCompact` | Placeholder — silently exits (future spec) |
| `SessionStart` | Delegates to `session-start-briefing.sh` for briefing injection |

### Prerequisites

- **HTTP mode**: Distillery MCP server running at a reachable URL (must be pre-started; the hook connects to it)
- **stdio mode**: `distillery-mcp` installed and on PATH (the hook launches it as a subprocess — no pre-running server required)
  _(required only for the `SessionStart` briefing; the `UserPromptSubmit` nudge works offline)_
- Python 3.11+ available on the system PATH (for `SessionStart` briefing)
- Claude Code with hook support

> **Note:** The SessionStart handler auto-detects how Distillery MCP is installed
> and uses the appropriate transport (HTTP or stdio). See the
> [Transport Resolution Order](#transport-resolution-order) section below.

### Manual Setup

If you prefer not to use `/setup`, configure hooks manually.

**1. Make the dispatcher executable** (already done if cloned from the repo):

```bash
chmod +x /path/to/distillery/scripts/hooks/distillery-hooks.sh
```

**2. Register the dispatcher in your settings.json:**

Choose the appropriate file based on desired scope:
- **User scope** (all projects): `~/.claude/settings.json`
- **Project scope** (this project only): `.claude/settings.json`

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash /absolute/path/to/distillery/scripts/hooks/distillery-hooks.sh"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash /absolute/path/to/distillery/scripts/hooks/distillery-hooks.sh"
          }
        ]
      }
    ]
  }
}
```

Replace `/absolute/path/to/distillery` with the actual path to your Distillery
installation.

**3. (Optional) Start the Distillery MCP server for SessionStart briefing:**

```bash
distillery-mcp --transport http --port 8000
```

If the MCP server is not running, `SessionStart` exits silently and `UserPromptSubmit`
nudges still work independently.

### Configuration

Configure all hooks via environment variables. Set these in your shell profile
(`~/.bashrc`, `~/.zshrc`) or in the Claude Code hook environment:

| Variable | Default | Description |
|---|---|---|
| `DISTILLERY_MCP_URL` | _(auto-detect)_ | MCP HTTP endpoint URL (skips auto-detection) |
| `DISTILLERY_MCP_COMMAND` | _(auto-detect)_ | MCP stdio command (skips auto-detection) |
| `DISTILLERY_NUDGE_INTERVAL` | `30` | Prompts between memory nudge outputs |
| `DISTILLERY_BRIEFING_LIMIT` | `5` | Recent entries in SessionStart briefing |
| `DISTILLERY_BEARER_TOKEN` | _(empty)_ | Bearer token if OAuth is enabled |

Example — nudge every 20 prompts, custom hosted URL:

```bash
export DISTILLERY_NUDGE_INTERVAL=20
export DISTILLERY_MCP_URL="https://distillery-mcp.fly.dev/mcp"
```

Example — force stdio transport (config-backed so the spawned server uses the
repo's normal wiring):

```bash
export DISTILLERY_MCP_COMMAND="env DISTILLERY_CONFIG=/path/to/distillery.yaml distillery-mcp"
```

> **Security note:** Do not commit `DISTILLERY_BEARER_TOKEN` or other secrets
> to version control. Use your shell profile or a secrets manager to set
> these values. The hook scripts themselves contain no credentials.

### Expected Behaviour

**UserPromptSubmit:** On each prompt, the dispatcher increments a per-session
counter in `/tmp/distillery-prompt-count-<session_id>`. Every `DISTILLERY_NUDGE_INTERVAL`
prompts it writes a reminder to stdout:

```text
[Distillery] You've exchanged 30 messages this session. Consider whether any decisions, insights, or corrections from this conversation should be stored with /distill.
```

All other prompts produce no output. The counter file is created automatically
on the first prompt and cleaned up on reboot (lives in `/tmp`).

**PreCompact:** Silently exits. Auto-extraction is planned for a future spec.

**SessionStart:** Delegates to `session-start-briefing.sh` in the same directory.
If that script is not present or not executable, exits silently with no output.

### Troubleshooting

**Nudge never fires:**
- Check `/tmp/distillery-prompt-count-<session_id>` exists and increments
- Verify `DISTILLERY_NUDGE_INTERVAL` is a positive integer (non-zero, non-empty)

**SessionStart produces no output:**
- **HTTP transport**: Check the MCP server accepts JSON-RPC probes — the hook
  does NOT use a `/health` sibling route (some deployments 404 on it, see #347).
  Test directly with the same `initialize` handshake the hook uses
  (`_build_init_msg()` in `session_start_briefing.py`):
  `curl -s -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"distillery-hook-probe","version":"1"}}}' "$DISTILLERY_MCP_URL"`
  Verify `DISTILLERY_MCP_URL` is correct.
- **stdio transport**: Check `distillery-mcp` is on PATH: `which distillery-mcp`; ensure the package is installed (`pip install distillery-mcp`)
- Ensure `session-start-briefing.sh` is present and executable in the same directory
- If the endpoint is unreachable, the hook writes a `[Distillery] briefing disabled — ...`
  line to stderr. Set `DISTILLERY_BRIEFING_QUIET=1` to silence.

**Hook not executing:**
- Verify the script path in `settings.json` is absolute
- Check the script is executable: `ls -la scripts/hooks/distillery-hooks.sh`
- Check Claude Code logs for hook execution errors

---

## session-start-briefing.sh

A `SessionStart` hook that injects a condensed Distillery briefing as a system
reminder at the start of every Claude Code session. This gives Claude awareness
of recent knowledge entries and stale items for the current project without
requiring a manual `/briefing` invocation.

The shell script is a thin wrapper that delegates to `session_start_briefing.py`,
which handles dynamic MCP transport resolution across HTTP, stdio, and
auto-detected configurations.

> This script is called automatically by `distillery-hooks.sh` for `SessionStart`
> events. You only need to register it separately if you do not use the dispatcher.

### Prerequisites

- **HTTP mode**: a Distillery MCP server running at a reachable URL (auto-detected)
- **stdio mode**: `distillery-mcp` installed so the hook can launch it as a subprocess (no pre-running server required)
- Python 3.11+ available on the system PATH

### Transport Resolution Order

The briefing hook auto-detects how Distillery MCP is installed using this
priority order (first reachable wins):

| Priority | Source | Transport |
|----------|--------|-----------|
| 1 | `DISTILLERY_MCP_URL` env var | HTTP |
| 2 | `DISTILLERY_MCP_COMMAND` env var | stdio |
| 3 | `.mcp.json` at repo root (walks up from cwd) | per config |
| 4a | `.claude/settings.json` at project root (current format) | per config |
| 4b | `~/.claude/settings.json` global (current format) | per config |
| 5 | `~/.claude.json` → `projects[<cwd>].mcpServers` (legacy) | per config |
| 6 | `~/.claude.json` → top-level `mcpServers` (legacy) | per config |
| 7 | `~/.claude/plugins/**/.claude-plugin/plugin.json` | per config |
| 8 | `distillery-mcp` on PATH | stdio |
| 9 | `http://localhost:8000/mcp` | HTTP |

For steps 3-6, the resolver looks for any `mcpServers` key containing
"distill" (case-insensitive). Each matching entry can be either a URL-based
(HTTP) or command-based (stdio) server configuration.

After resolving a transport, the hook probes it for reachability:
- **HTTP**: JSON-RPC `initialize` handshake against `/mcp` with a 2-second timeout
  (no sibling `/health` route required — FastMCP deployments do not expose one)
- **stdio**: subprocess `initialize` handshake with a 3-second timeout

If the resolved server is unreachable, the hook exits silently with code 0.

### Configuration

Configure the hook via environment variables. Set these in your shell profile
(`~/.bashrc`, `~/.zshrc`) or in the Claude Code hook environment:

| Variable | Default | Description |
|---|---|---|
| `DISTILLERY_MCP_URL` | _(auto-detect)_ | MCP HTTP endpoint URL (skips auto-detection) |
| `DISTILLERY_MCP_COMMAND` | _(auto-detect)_ | MCP stdio command (skips auto-detection) |
| `DISTILLERY_BRIEFING_LIMIT` | `5` | Number of recent entries to include |
| `DISTILLERY_BEARER_TOKEN` | _(empty)_ | Bearer token if OAuth is enabled |

Example — force hosted URL:

```bash
export DISTILLERY_MCP_URL="https://distillery-mcp.fly.dev/mcp"
export DISTILLERY_BRIEFING_LIMIT="10"
```

Example — force stdio transport (config-backed so the spawned server uses the
repo's normal wiring):

```bash
export DISTILLERY_MCP_COMMAND="env DISTILLERY_CONFIG=/path/to/distillery.yaml distillery-mcp"
```

> **Security note:** Do not commit `DISTILLERY_BEARER_TOKEN` or other secrets
> to version control. Use your shell profile or a secrets manager to set
> these values. The hook scripts contain no credentials.

### Expected Behavior

When a Claude Code session starts, the hook:

1. Reads the `hook_event_name`, `session_id`, and `cwd` from the hook JSON on stdin
2. Derives the project name from the git root basename (or `cwd` basename if not in a git repo)
3. Performs a 2-second health check to the MCP server
4. If the server is unreachable — exits silently with no output (no disruption)
5. If reachable — fetches recent entries (`distillery_list(limit=5)`) and stale knowledge (`distillery_list(stale_days=30, limit=10)`) — `distillery_stale` was consolidated into `distillery_list` via the `stale_days` parameter
6. Formats a condensed summary (max 20 lines) and writes it to stdout

Claude Code injects the stdout as a system reminder, giving the LLM context
about prior decisions and stale knowledge without any explicit prompting.

### Sample Output

When the MCP server is reachable and entries exist:

```text
[Distillery] Project: distillery
Recent (5): Implemented corrections chain with entry_relations, FastMCP 3.1 migration guide, ...
Stale (2): Sprint planning notes, DuckDB VSS index rebuild...
```

When the MCP server is unreachable: no output (silent exit).

### Troubleshooting

**Hook produces no output:**
- **HTTP transport**: Verify `DISTILLERY_MCP_URL` is correct and the server
  accepts JSON-RPC probes — the hook does NOT use a `/health` sibling route
  (FastMCP deployments don't expose one; some return 404). Exercise the same
  `initialize` handshake the hook uses:
  `curl -s -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"distillery-hook-probe","version":"1"}}}' "$DISTILLERY_MCP_URL"`
- **stdio transport**: Check `distillery-mcp` is on PATH: `which distillery-mcp`; ensure the package is installed (`pip install distillery-mcp`)
- Check the server logs for errors

**Authentication errors:**
- Set `DISTILLERY_BEARER_TOKEN` if the server requires OAuth
- Ensure the token has not expired

**Hook not executing:**
- Verify the script path in `settings.json` is absolute
- Check the script is executable: `ls -la scripts/hooks/session-start-briefing.sh`
- Check Claude Code logs for hook execution errors
