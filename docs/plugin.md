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

- **Skills directory** — loaded from `.claude-plugin/skills/` (only when installed as a plugin)
- **MCP server dependency** — HTTP transport to the hosted Distillery server (GitHub OAuth)

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
cp -r /path/to/distillery/.claude-plugin/skills/* ~/.claude/skills/
```

Or clone this repo and symlink:

```bash
git clone https://github.com/norrietaylor/distillery.git ~/.claude/distillery
ln -s ~/.claude/distillery/.claude-plugin/skills/distill   ~/.claude/skills/distill
ln -s ~/.claude/distillery/.claude-plugin/skills/recall    ~/.claude/skills/recall
ln -s ~/.claude/distillery/.claude-plugin/skills/pour      ~/.claude/skills/pour
ln -s ~/.claude/distillery/.claude-plugin/skills/bookmark  ~/.claude/skills/bookmark
ln -s ~/.claude/distillery/.claude-plugin/skills/minutes   ~/.claude/skills/minutes
ln -s ~/.claude/distillery/.claude-plugin/skills/classify  ~/.claude/skills/classify
```

## MCP Configuration

The skills require the Distillery MCP server.  The plugin defaults to the hosted
Distillery server at `https://distillery-mcp.fly.dev/mcp` with GitHub OAuth
authentication.  No local installation or API key required.

### Default — Hosted HTTP (GitHub OAuth)

The plugin manifest configures this automatically on install.  On first use, Claude Code
opens a browser for GitHub OAuth login.  After authorization, all MCP tools are available.

If you need to configure it manually, add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "distillery": {
      "url": "https://distillery-mcp.fly.dev/mcp",
      "transport": "http"
    }
  }
}
```

### Alternative — Local stdio

For offline use or a private knowledge base, run the MCP server locally.  Requires
Python 3.11+ and a local Distillery installation.

```bash
pip install distillery
```

Add to `~/.claude/settings.json`:

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

See [`distillery.yaml.example`](../distillery.yaml.example) for configuration options and
[mcp-setup.md](mcp-setup.md) for the full local setup guide.

### Alternative — Self-hosted HTTP

Deploy your own Distillery server with GitHub OAuth.  See [deployment.md](deployment.md) for
operator setup and [deploy/fly/README.md](../deploy/fly/README.md) or
[deploy/prefect/README.md](../deploy/prefect/README.md) for platform-specific guides.

---

## Remote Auto-Poll Setup

You can enable **remote auto-polling** so feed sources are polled automatically even when
Claude Code is not running.  This uses Claude Code's scheduled remote agents (triggers).

### Step 1 — Register the MCP Connector

1. Open **https://claude.ai/settings/connectors**
2. Click **"Add connector"**
3. Enter the Distillery MCP server URL: `https://distillery-mcp.fly.dev/mcp`
4. Name it: `distillery`
5. Click **Save**

### Step 2 — Run `/setup`

```text
/setup
```

The wizard detects your transport, finds the registered connector, and creates a scheduled
trigger that polls all feed sources every hour.  You can manage triggers at
https://claude.ai/code/scheduled.

### Step 3 — Verify

```text
/watch list
```

You should see your feed sources and a note about the active remote trigger.

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
- [Skills README](../.claude-plugin/skills/README.md) — skill authoring and conventions
- [CONVENTIONS.md](../.claude-plugin/skills/CONVENTIONS.md) — shared patterns across all skills
