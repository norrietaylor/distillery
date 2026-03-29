# Distillery — Claude Code Plugin

The Distillery plugin packages all ten knowledge-base skills (`/distill`, `/recall`, `/pour`,
`/bookmark`, `/minutes`, `/classify`, `/watch`, `/radar`, `/tune`, `/setup`) for distribution
and installation via the Claude Code plugin mechanism.  Once installed, the skills are available
in every project without copying files.

## Plugin Manifest

The plugin manifest is located at [`.claude-plugin/plugin.json`](../.claude-plugin/plugin.json).
The repository also serves as its own marketplace via [`.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json),
enabling direct installation from the GitHub repo.

The manifest specifies:

- **Skills directory** — auto-discovered from `.claude/skills/`
- **MCP server dependency** — local stdio transport with configurable environment variables

## Installation

### Option 1 — Claude Code plugin install (recommended)

```bash
# Add the Distillery marketplace (one-time setup)
claude plugin marketplace add norrietaylor/distillery

# Install the plugin
claude plugin install distillery
```

This installs the skill definitions globally and configures the MCP server
(see [MCP Configuration](#mcp-configuration) below).

### Option 2 — Manual install (copy skills)

Copy the skills directory into any project that should have access to the skills:

```bash
# From inside the target project
mkdir -p ~/.claude/skills
cp -r /path/to/distillery/.claude/skills/* ~/.claude/skills/
```

Or clone this repo and symlink:

```bash
git clone https://github.com/norrietaylor/distillery.git ~/.claude/distillery
ln -s ~/.claude/distillery/.claude/skills/distill   ~/.claude/skills/distill
ln -s ~/.claude/distillery/.claude/skills/recall    ~/.claude/skills/recall
ln -s ~/.claude/distillery/.claude/skills/pour      ~/.claude/skills/pour
ln -s ~/.claude/distillery/.claude/skills/bookmark  ~/.claude/skills/bookmark
ln -s ~/.claude/distillery/.claude/skills/minutes   ~/.claude/skills/minutes
ln -s ~/.claude/distillery/.claude/skills/classify  ~/.claude/skills/classify
```

## MCP Configuration

The skills require the Distillery MCP server.  Choose one of the three transport options:

### Transport A — Local stdio (recommended)

Runs the MCP server as a subprocess.  Requires Python 3.11+ and a local Distillery installation.

**1. Install Distillery:**

```bash
pip install distillery
# Or, for the latest development version:
pip install git+https://github.com/norrietaylor/distillery.git
```

**2. Create `~/.distillery/distillery.yaml`:**

```yaml
storage:
  backend: duckdb
  database_path: ~/.distillery/distillery.db

embedding:
  provider: jina
  model: jina-embeddings-v3
  dimensions: 1024
  api_key_env: JINA_API_KEY
```

See [`distillery.yaml.example`](../distillery.yaml.example) for all configuration options,
including the OpenAI embedding provider.

**3. Set your API key:**

```bash
export JINA_API_KEY=jina_...
# Or add to your shell profile (.bashrc / .zshrc)
```

**4. Add to `~/.claude/settings.json`:**

```json
{
  "mcpServers": {
    "distillery": {
      "command": "distillery-mcp",
      "env": {
        "JINA_API_KEY": "${JINA_API_KEY}",
        "DISTILLERY_CONFIG": "${DISTILLERY_CONFIG}"
      }
    }
  }
}
```

If `DISTILLERY_CONFIG` is unset, Distillery looks for `distillery.yaml` in the current
working directory, then falls back to built-in defaults.

---

### Transport B — Team HTTP (GitHub OAuth)

Connect to a team-hosted Distillery instance secured with GitHub OAuth.  No local
installation or API key required — authentication uses your GitHub account.

**Add to `~/.claude/settings.json`:**

```json
{
  "mcpServers": {
    "distillery": {
      "transport": "http",
      "url": "https://your-distillery-host.example.com/mcp"
    }
  }
}
```

On first use, Claude Code opens a browser for GitHub OAuth login.  After
authorization, all 17 MCP tools are available through the remote server.

See [team-setup.md](team-setup.md) for the full team member guide and
[deployment.md](deployment.md) for operator setup (GitHub OAuth App
registration, environment variables, server configuration).

### Transport C — Hosted demo (unauthenticated)

Connect to the shared demonstration server.  No local installation or API key required.

**Add to `~/.claude/settings.json`:**

```json
{
  "mcpServers": {
    "distillery": {
      "transport": "http",
      "url": "https://able-red-cougar.fastmcp.app/mcp"
    }
  }
}
```

> **Note:** The hosted instance is a shared demonstration server.  Do not store sensitive or
> proprietary knowledge there.

---

## Remote Auto-Poll Setup (Hosted / Team HTTP only)

When using a hosted or team HTTP transport, you can enable **remote auto-polling** so feed
sources are polled automatically even when Claude Code is not running.  This uses Claude Code's
scheduled remote agents (triggers) which run on Anthropic's infrastructure on a cron schedule.

### Prerequisites

Remote triggers need an **MCP connector** registered at claude.ai to connect to your
Distillery server.  Without this, `/watch add` falls back to local cron polling (which only
runs while Claude Code is active).

### Step 1 — Register the MCP Connector

1. Open **https://claude.ai/settings/connectors**
2. Click **"Add connector"**
3. Enter the Distillery MCP server URL:
   - Hosted demo: `https://able-red-cougar.fastmcp.app/mcp`
   - Team HTTP: your team's Distillery URL (e.g. `https://distillery.yourcompany.com/mcp`)
4. Name it: `distillery`
5. Click **Save**

This generates a `connector_uuid` that Claude Code uses when creating scheduled triggers.

### Step 2 — Run `/setup`

After registering the connector, run the setup wizard in Claude Code:

```text
/setup
```

The wizard detects your transport, finds the registered connector, and creates a scheduled
trigger that polls all feed sources every hour.  You can manage triggers at
https://claude.ai/code/scheduled.

### Step 3 — Verify

Check that the trigger was created:

```text
/watch list
```

You should see your feed sources and a note about the active remote trigger.

### What if I skip this?

If you don't register the MCP connector, everything still works — but auto-polling falls back
to a local cron job that only fires while Claude Code is running.  You can always register the
connector later and run `/setup` again.

---

## Verifying the Setup

After saving the settings file, restart Claude Code or reload MCP servers.
Then check that Distillery is connected:

```text
distillery_status
```

You should see a JSON response with `"status": "ok"`.

You can also run the CLI health check directly:

```bash
distillery health
```

## Available Skills

| Skill | Trigger phrases | Description |
|-------|----------------|-------------|
| `/distill` | "capture this", "save knowledge", "log learnings" | Capture session decisions and insights with duplicate detection |
| `/recall` | "what do we know about", "search knowledge" | Semantic search with provenance |
| `/pour` | "synthesize", "what's the full picture on" | Multi-pass retrieval and synthesis with citations |
| `/bookmark` | "bookmark", "save this link", "store this URL" | Fetch a URL, summarize, and store |
| `/minutes` | "meeting notes", "capture meeting", "log meeting" | Structured meeting notes with append support |
| `/classify` | "classify", "review queue", "triage inbox" | Entry classification and review queue triage |
| `/watch` | "add feed", "remove source", "show my sources" | Manage feed sources with auto-poll scheduling |
| `/radar` | "what's new", "show my digest", "what have I missed" | Ambient intelligence digest from feed entries |
| `/tune` | "adjust thresholds", "tune my feed" | Display and adjust feed relevance thresholds |
| `/setup` | "setup", "configure distillery" | Onboarding wizard — connectivity, connector registration, auto-poll |

## MCP Unavailability

If the MCP server is not configured or not running, each skill displays:

```text
Warning: Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

To set up the server:
1. Ensure Distillery is installed: https://github.com/norrietaylor/distillery
2. Configure the server in your Claude Code settings: see docs/mcp-setup.md
3. Restart Claude Code or reload MCP servers
```

Follow [docs/mcp-setup.md](mcp-setup.md) to resolve the issue.

## Troubleshooting

See [docs/mcp-setup.md#troubleshooting](mcp-setup.md#troubleshooting) for common problems
and solutions.

## Further Reading

- [MCP Server Setup](mcp-setup.md) — full MCP configuration reference
- [Team Setup](team-setup.md) — connecting to a hosted Distillery instance
- [Deployment Guide](deployment.md) — running Distillery as a team HTTP service with GitHub OAuth
- [Skills README](./../.claude/skills/README.md) — skill authoring and conventions
- [CONVENTIONS.md](./../.claude/skills/CONVENTIONS.md) — shared patterns across all skills
