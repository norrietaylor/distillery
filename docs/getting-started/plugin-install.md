# Plugin Install

The Distillery plugin packages all ten knowledge-base skills for distribution and installation via the Claude Code plugin mechanism. Once installed, the skills are available in every project without copying files.

## Install via Plugin Marketplace (Recommended)

```bash
# Add the Distillery marketplace (one-time setup)
claude plugin marketplace add norrietaylor/distillery

# Install the plugin
claude plugin install distillery
```

This installs the skill definitions globally and configures the MCP server connection to the hosted Distillery instance.

After installation, restart Claude Code and run the onboarding wizard:

```text
/setup
```

This verifies MCP connectivity, detects your transport, and configures auto-poll for ambient intelligence.

!!! warning "Demo Server"
    The plugin defaults to the hosted instance at `distillery-mcp.fly.dev`, which is a **demo server** for evaluation only. Do not store sensitive or confidential data. For production use, [deploy your own instance](../team/fly.md) or use [local setup](local-setup.md).

!!! note "Claude Desktop"
    The Claude desktop app does not support Claude Code skills or the plugin install system. Desktop users can connect the MCP server directly (all 22 tools are available) but slash commands like `/distill` and `/recall` are CLI-only features.

## Manual Install (Copy Skills)

Copy the skills directory into any project that should have access:

```bash
mkdir -p ~/.claude/skills
cp -r /path/to/distillery/.claude-plugin/skills/* ~/.claude/skills/
```

Or clone and symlink:

```bash
git clone https://github.com/norrietaylor/distillery.git ~/.claude/distillery
ln -s ~/.claude/distillery/.claude-plugin/skills/distill   ~/.claude/skills/distill
ln -s ~/.claude/distillery/.claude-plugin/skills/recall    ~/.claude/skills/recall
ln -s ~/.claude/distillery/.claude-plugin/skills/pour      ~/.claude/skills/pour
ln -s ~/.claude/distillery/.claude-plugin/skills/bookmark  ~/.claude/skills/bookmark
ln -s ~/.claude/distillery/.claude-plugin/skills/minutes   ~/.claude/skills/minutes
ln -s ~/.claude/distillery/.claude-plugin/skills/classify  ~/.claude/skills/classify
ln -s ~/.claude/distillery/.claude-plugin/skills/watch     ~/.claude/skills/watch
ln -s ~/.claude/distillery/.claude-plugin/skills/radar     ~/.claude/skills/radar
ln -s ~/.claude/distillery/.claude-plugin/skills/tune      ~/.claude/skills/tune
ln -s ~/.claude/distillery/.claude-plugin/skills/setup     ~/.claude/skills/setup
```

## MCP Configuration

The skills require the Distillery MCP server. The plugin defaults to the hosted server at `https://distillery-mcp.fly.dev/mcp` with GitHub OAuth authentication — no local installation or API key required.

### Default — Hosted HTTP (GitHub OAuth)

The plugin manifest configures this automatically on install. On first use, Claude Code opens a browser for GitHub OAuth login. After authorization, all MCP tools are available.

To configure manually, add to `~/.claude/settings.json`:

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

For offline use or a private knowledge base, run the MCP server locally. Requires Python 3.11+ and a local Distillery installation.

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

See [Local Setup](local-setup.md) for full local configuration and [MCP Server Reference](mcp-setup.md) for all options.

### Alternative — Self-hosted HTTP

Deploy your own Distillery server with GitHub OAuth. See [Operator Deployment](../team/deployment.md) for setup and [Fly.io](../team/fly.md) or [Prefect Horizon](../team/prefect.md) for platform-specific guides.

## Remote Auto-Poll Setup

Enable remote auto-polling so feed sources are polled automatically even when Claude Code is not running. This uses Claude Code's scheduled remote agents (triggers).

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

The wizard detects your transport, finds the registered connector, and creates a scheduled trigger that polls all feed sources every hour.

### Step 3 — Verify

```text
/watch list
```

You should see your feed sources and a note about the active remote trigger.

## Verifying the Setup

After saving the settings file, restart Claude Code or reload MCP servers, then check connectivity by calling the `distillery_status` MCP tool:

```text
distillery_status
```

You should see a JSON response with `"status": "ok"`.

You can also run the CLI health check directly:

```bash
distillery health
```

## Available Skills

| Skill | Trigger Phrases | Description |
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

## Troubleshooting

See [MCP Server Reference — Troubleshooting](mcp-setup.md#troubleshooting) for common problems and solutions.
