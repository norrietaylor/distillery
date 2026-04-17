# Plugin Install

The Distillery plugin packages all fourteen knowledge-base skills for distribution and installation via the Claude Code plugin mechanism. Once installed, the skills are available in every project without copying files.

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
    The plugin defaults to the hosted instance at `distillery-mcp.fly.dev`, which is a **demo server** for evaluation only. Do not store sensitive or confidential data. For production use, [deploy your own instance](../team/deployment.md) or use [local setup](local-setup.md).

!!! note "Claude Desktop"
    The Claude Desktop app does not support Claude Code skills or the plugin install system. Desktop users can connect the MCP server directly (all 20 tools are available) but slash commands like `/distill` and `/recall` are CLI-only features.

## Manual Install (Copy Skills)

Copy the skills directory into any project that should have access:

```bash
mkdir -p ~/.claude/skills
cp -r /path/to/distillery/skills/* ~/.claude/skills/
```

Or clone and symlink:

```bash
git clone https://github.com/norrietaylor/distillery.git ~/.claude/distillery
ln -s ~/.claude/distillery/skills/distill   ~/.claude/skills/distill
ln -s ~/.claude/distillery/skills/recall    ~/.claude/skills/recall
ln -s ~/.claude/distillery/skills/pour      ~/.claude/skills/pour
ln -s ~/.claude/distillery/skills/bookmark  ~/.claude/skills/bookmark
ln -s ~/.claude/distillery/skills/minutes   ~/.claude/skills/minutes
ln -s ~/.claude/distillery/skills/classify  ~/.claude/skills/classify
ln -s ~/.claude/distillery/skills/watch     ~/.claude/skills/watch
ln -s ~/.claude/distillery/skills/radar     ~/.claude/skills/radar
ln -s ~/.claude/distillery/skills/tune      ~/.claude/skills/tune
ln -s ~/.claude/distillery/skills/digest      ~/.claude/skills/digest
ln -s ~/.claude/distillery/skills/gh-sync     ~/.claude/skills/gh-sync
ln -s ~/.claude/distillery/skills/investigate  ~/.claude/skills/investigate
ln -s ~/.claude/distillery/skills/briefing    ~/.claude/skills/briefing
ln -s ~/.claude/distillery/skills/setup     ~/.claude/skills/setup
```

## MCP Configuration

The skills require the Distillery MCP server. The recommended approach is to run it locally via `uvx` for a private knowledge base. The plugin also bundles a demo server connection for quick evaluation.

### Recommended — Local stdio with uvx

Run the MCP server locally for a private, self-contained knowledge base. Requires Python 3.11+.

```bash
# No install needed
uvx distillery-mcp

# Or install persistently
pip install distillery-mcp
```

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "distillery": {
      "command": "uvx",
      "args": ["distillery-mcp"],
      "env": {
        "JINA_API_KEY": "${JINA_API_KEY}",
        "DISTILLERY_CONFIG": "${DISTILLERY_CONFIG}"
      }
    }
  }
}
```

This overrides the plugin's default demo server connection. See [Local Setup](local-setup.md) for full configuration (embedding providers, cloud storage, etc.).

### Alternative — Demo server (no setup)

The plugin manifest configures a connection to the hosted demo at `https://distillery-mcp.fly.dev/mcp` with GitHub OAuth authentication. On first use, Claude Code opens a browser for GitHub OAuth login.

!!! warning "Demo Server"
    The demo server is for **evaluation only**. Do not store sensitive or confidential data. For production use, run locally with `uvx` (above) or deploy your own instance.

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

### Alternative — Self-hosted HTTP

Deploy your own Distillery server with GitHub OAuth. See [Operator Deployment](../team/deployment.md) for setup and the [distill_ops](https://github.com/norrietaylor/distill_ops) repo for platform-specific guides (Fly.io, Prefect Horizon).

To point the plugin at your own instance, set the `distillery_mcp_url` plugin config field at enable time. Claude Code prompts for userConfig values when you enable the plugin, and the value is substituted into the plugin's MCP server registration automatically. Leave it at the default to use the hosted demo.

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

After saving the settings file, restart Claude Code or reload MCP servers, then check connectivity by calling the `distillery_metrics` MCP tool:

```text
distillery_metrics(scope="summary")
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
| `/digest` | "team digest", "weekly summary" | Team activity summary from internal entries |
| `/gh-sync` | "sync GitHub", "import issues" | Sync GitHub issues/PRs into the knowledge base |
| `/investigate` | "investigate", "deep context" | Deep context builder with relationship traversal |
| `/briefing` | "team briefing", "dashboard" | Team knowledge dashboard with metrics and activity |
| `/setup` | "setup", "configure distillery" | Onboarding wizard — connectivity, connector registration, auto-poll |

## Troubleshooting

See [MCP Server Reference — Troubleshooting](mcp-setup.md#troubleshooting) for common problems and solutions.
