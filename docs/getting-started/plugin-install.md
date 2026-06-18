# Plugin Install

The Distillery plugin packages all fourteen knowledge-base skills for distribution and installation via the Claude Code plugin mechanism. Once installed, the skills are available in every project without copying files.

## Install via Plugin Marketplace (Recommended)

```bash
# Add the Distillery marketplace (one-time setup)
claude plugin marketplace add norrietaylor/distillery

# Install the plugin
claude plugin install distillery
```

This installs the skill definitions globally. The plugin **does not configure an MCP server automatically** — run `/setup` (next step) to add one. The recommended setup is a private, self-contained local knowledge base via `uvx --from 'distillery-mcp[fastembed]>=0.6.0' distillery-mcp`, with on-device `fastembed` embeddings (no API key required). Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) on your `PATH`.

!!! tip "Install uv"
    `curl -LsSf https://astral.sh/uv/install.sh | sh` — or use `pip install 'distillery-mcp[fastembed]'` and set the server `command` to `distillery-mcp` (see [Troubleshooting](mcp-setup.md#troubleshooting)).

After installation, restart Claude Code and run the onboarding wizard:

```text
/setup
```

This verifies MCP connectivity, prompts you to configure an MCP server if none is connected, detects your transport, and configures auto-poll for ambient intelligence.

!!! note "Hosted demo (opt-in)"
    Want a zero-install evaluation? You can opt into the hosted demo at `distillery-mcp.fly.dev` instead — see [MCP Configuration](#mcp-configuration) below. The demo server is for **evaluation only**; do not store sensitive or confidential data.

!!! note "Claude Desktop"
    The Claude Desktop app does not support Claude Code skills or the plugin install system. Desktop users can connect the MCP server directly (all 16 tools are available) but slash commands like `/distill` and `/recall` are CLI-only features.

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

The skills require the Distillery MCP server, which you configure yourself — the plugin ships skills only. The **recommended** setup is local stdio via `uvx distillery-mcp`. Hosted demo and self-hosted HTTP are opt-in alternatives.

### Recommended — Local stdio with uvx (fastembed)

`/setup` prompts to add this when no server is connected, or add it manually to `~/.claude.json` (user scope) or `.mcp.json` (this project):

```json
{
  "mcpServers": {
    "distillery": {
      "command": "uvx",
      "args": ["--from", "distillery-mcp[fastembed]>=0.6.0", "distillery-mcp"],
      "env": {
        "DISTILLERY_EMBEDDING_PROVIDER": "fastembed"
      }
    }
  }
}
```

Out of the box, no API keys are required — `fastembed` runs ONNX inference on-device. Optional Distillery config vars (like `DISTILLERY_CONFIG`) are inherited from the Claude Code process environment:

```bash
# Optional:
export DISTILLERY_CONFIG=/path/to/distillery.yaml
```

To use a hosted embedding provider instead (Jina or OpenAI), override the default in your shell before launching Claude Code:

```bash
# Jina (free tier at jina.ai)
export DISTILLERY_EMBEDDING_PROVIDER=jina
export JINA_API_KEY=jina_...

# Or OpenAI
export DISTILLERY_EMBEDDING_PROVIDER=openai
export OPENAI_API_KEY=sk-...
```

See [Local Setup](local-setup.md) for full configuration (embedding providers, cloud storage, etc.).

If you prefer to manage the configuration yourself in `~/.claude.json`, you can shadow the plugin registration with the same stdio block (env vars like `DISTILLERY_EMBEDDING_PROVIDER` and any provider API key should be set in your shell rather than via `${VAR}` interpolation):

```json
{
  "mcpServers": {
    "distillery": {
      "command": "uvx",
      "args": ["--from", "distillery-mcp[fastembed]>=0.6.0", "distillery-mcp"],
      "env": {
        "DISTILLERY_EMBEDDING_PROVIDER": "fastembed"
      }
    }
  }
}
```

### Opt-in — Hosted demo

Distillery operates a hosted demo at `https://distillery-mcp.fly.dev/mcp` for zero-install evaluation. Authentication is via GitHub OAuth (Claude Code opens a browser on first use).

!!! warning "Demo Server"
    The demo server is for **evaluation only**. Do not store sensitive or confidential data. For production use, stick with the default local stdio setup or deploy your own instance.

Register the demo at user scope (shadows the plugin's local default):

```bash
claude mcp add distillery --scope user --transport http --url https://distillery-mcp.fly.dev/mcp
```

Or add the equivalent block to `~/.claude.json`:

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

### Opt-in — Self-hosted HTTP

Deploy your own Distillery server with GitHub OAuth. See [Operator Deployment](../team/deployment.md) for setup and the [distill_ops](https://github.com/norrietaylor/distill_ops) repo for platform-specific guides (Fly.io, Prefect Horizon).

To shadow the plugin default with your own instance, register at user scope:

```bash
claude mcp add distillery --scope user --transport http --url https://your-instance.example.com/mcp
```

## Remote Auto-Poll Setup

Enable remote auto-polling so feed sources are polled automatically even when Claude Code is not running. This uses Claude Code's scheduled remote agents (triggers).

!!! note "HTTP transport required"
    Remote auto-poll requires an HTTP-reachable MCP endpoint (Hosted Demo or Self-hosted HTTP). The default local stdio transport (`uvx distillery-mcp`) only runs on your machine and is not reachable by remote triggers.

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
distillery_status()
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
