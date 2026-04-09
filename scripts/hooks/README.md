# Distillery Hook Scripts

This directory contains Claude Code hook scripts for Distillery integration.

## distillery-hooks.sh (recommended)

A single **dispatcher script** that routes all Claude Code hook events to the
appropriate Distillery handler. Register this one script for `UserPromptSubmit`,
`PreCompact`, and `SessionStart` in `~/.claude/settings.json` — no need to
manage multiple hook entries.

### Hook Events

| Hook Event | Behaviour |
|---|---|
| `UserPromptSubmit` | Outputs a memory nudge every N prompts (default 30) |
| `PreCompact` | Placeholder — silently exits (future spec) |
| `SessionStart` | Delegates to `session-start-briefing.sh` for briefing injection |

### Prerequisites

- Distillery MCP server running with **HTTP transport** (`distillery-mcp --transport http`)
  (required only for the `SessionStart` briefing; the `UserPromptSubmit` nudge works offline)
- `curl` available on the system PATH (for `SessionStart` briefing)
- `flock` available on the system PATH (for atomic counter — standard on Linux; on macOS install via `brew install util-linux` or use an alternative such as `lockf` or coreutils)
- Claude Code with hook support (`~/.claude/settings.json`)

> **Note:** The SessionStart handler targets the HTTP MCP transport, not stdio.
> Hooks run as shell commands outside of an MCP session, so they must
> communicate with the server over HTTP.

### Setup

**1. Make the dispatcher executable** (already done if cloned from the repo):

```bash
chmod +x /path/to/distillery/scripts/hooks/distillery-hooks.sh
```

**2. Register the dispatcher in `~/.claude/settings.json`:**

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "type": "command",
        "command": "/absolute/path/to/distillery/scripts/hooks/distillery-hooks.sh"
      }
    ],
    "PreCompact": [
      {
        "type": "command",
        "command": "/absolute/path/to/distillery/scripts/hooks/distillery-hooks.sh"
      }
    ],
    "SessionStart": [
      {
        "type": "command",
        "command": "/absolute/path/to/distillery/scripts/hooks/distillery-hooks.sh"
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
| `DISTILLERY_MCP_URL` | `http://localhost:8000/mcp` | MCP HTTP endpoint URL |
| `DISTILLERY_NUDGE_INTERVAL` | `30` | Prompts between memory nudge outputs |
| `DISTILLERY_BRIEFING_LIMIT` | `5` | Recent entries in SessionStart briefing |
| `DISTILLERY_BEARER_TOKEN` | _(empty)_ | Bearer token if OAuth is enabled |

Example — nudge every 20 prompts, custom port:

```bash
export DISTILLERY_NUDGE_INTERVAL=20
export DISTILLERY_MCP_URL="http://localhost:9000/mcp"
```

> **Security note:** Do not commit `DISTILLERY_BEARER_TOKEN` or other secrets
> to version control. Use your shell profile or a secrets manager to set
> these values. The hook scripts themselves contain no credentials.

### Expected Behaviour

**UserPromptSubmit:** On each prompt, the dispatcher increments a per-session
counter in `/tmp/distillery-prompt-count-<session_id>`. Every `DISTILLERY_NUDGE_INTERVAL`
prompts it writes a reminder to stdout:

```
[Distillery] You've exchanged 30 messages this session. Consider whether any decisions, insights, or corrections from this conversation should be stored with /distill.
```

All other prompts produce no output. The counter file is created automatically
on the first prompt and cleaned up on reboot (lives in `/tmp`).

**PreCompact:** Silently exits. Auto-extraction is planned for a future spec.

**SessionStart:** Delegates to `session-start-briefing.sh` in the same directory.
If that script is not present or not executable, exits silently with no output.

### Troubleshooting

**Nudge never fires:**
- Ensure `flock` is installed (`which flock`)
- Check `/tmp/distillery-prompt-count-<session_id>` exists and increments
- Verify `DISTILLERY_NUDGE_INTERVAL` is not accidentally set to a large value

**SessionStart produces no output:**
- Check the MCP server is running: `curl http://localhost:8000/health`
- Verify `DISTILLERY_MCP_URL` is correct
- Ensure `session-start-briefing.sh` is present and executable in the same directory

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

> This script is called automatically by `distillery-hooks.sh` for `SessionStart`
> events. You only need to register it separately if you do not use the dispatcher.

### Prerequisites

- Distillery MCP server running with **HTTP transport** (`distillery-mcp --transport http`)
- `curl` available on the system PATH
- Claude Code with hook support (`~/.claude/settings.json`)

> **Note:** The hook targets the HTTP MCP transport, not stdio. Hooks run as
> shell commands outside of an MCP session, so they must communicate with the
> server over HTTP.

### Setup

**1. Make the script executable** (already done if cloned from the repo):

```bash
chmod +x /path/to/distillery/scripts/hooks/session-start-briefing.sh
```

**2. Register the hook in `~/.claude/settings.json`:**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "/absolute/path/to/distillery/scripts/hooks/session-start-briefing.sh"
      }
    ]
  }
}
```

Replace `/absolute/path/to/distillery` with the actual path to your Distillery
installation.

**3. Start the Distillery MCP server with HTTP transport:**

```bash
distillery-mcp --transport http --port 8000
```

### Configuration

Configure the hook via environment variables. Set these in your shell profile
(`~/.bashrc`, `~/.zshrc`) or in the Claude Code hook environment:

| Variable | Default | Description |
|---|---|---|
| `DISTILLERY_MCP_URL` | `http://localhost:8000/mcp` | MCP HTTP endpoint URL |
| `DISTILLERY_BRIEFING_LIMIT` | `5` | Number of recent entries to include |
| `DISTILLERY_BEARER_TOKEN` | _(empty)_ | Bearer token if OAuth is enabled |

Example — custom port and more entries:

```bash
export DISTILLERY_MCP_URL="http://localhost:9000/mcp"
export DISTILLERY_BRIEFING_LIMIT="10"
```

Example — with OAuth bearer token:

```bash
export DISTILLERY_BEARER_TOKEN="your-token-here"
```

> **Security note:** Do not commit `DISTILLERY_BEARER_TOKEN` or other secrets
> to version control. Use your shell profile or a secrets manager to set
> these values. The hook script itself contains no credentials.

### Expected Behavior

When a Claude Code session starts, the hook:

1. Reads the `hook_event_name`, `session_id`, and `cwd` from the hook JSON on stdin
2. Derives the project name from the git root basename (or `cwd` basename if not in a git repo)
3. Performs a 2-second health check to the MCP server
4. If the server is unreachable — exits silently with no output (no disruption)
5. If reachable — fetches recent entries (`distillery_list`) and stale knowledge (`distillery_stale`)
6. Formats a condensed summary (max 20 lines) and writes it to stdout

Claude Code injects the stdout as a system reminder, giving the LLM context
about prior decisions and stale knowledge without any explicit prompting.

### Sample Output

When the MCP server is reachable and entries exist:

```
[Distillery] Project: distillery
Recent (5): Implemented corrections chain with entry_relations, FastMCP 3.1 migration guide, ...
Stale (2): Sprint planning notes, DuckDB VSS index rebuild...
```

When the MCP server is unreachable: no output (silent exit).

### Troubleshooting

**Hook produces no output:**
- Check the MCP server is running: `curl http://localhost:8000/health`
- Verify `DISTILLERY_MCP_URL` is correct
- Check the server logs for errors

**Authentication errors:**
- Set `DISTILLERY_BEARER_TOKEN` if the server requires OAuth
- Ensure the token has not expired

**Hook not executing:**
- Verify the script path in `settings.json` is absolute
- Check the script is executable: `ls -la scripts/hooks/session-start-briefing.sh`
- Check Claude Code logs for hook execution errors