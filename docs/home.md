<div style="text-align: center; margin: 2rem 0 1rem;">
  <img src="../assets/distillery-logo-dark-512.png" alt="Distillery" width="256" style="max-width: 100%;">
</div>

# Distillery

**Team Knowledge, Distilled**

Distillery is a team knowledge base accessed through [Claude Code](https://claude.ai/code) skills. It refines raw information from working sessions, meetings, bookmarks, and conversations into concentrated, searchable knowledge — stored as vector embeddings in [DuckDB](https://duckdb.org/) and retrieved through natural language.

Runs locally over stdio or as a hosted HTTP service with GitHub OAuth for team access.

## Who is Distillery for?

- **Developers and teams** who use Claude Code and want to capture, organize, and retrieve knowledge without leaving their workflow.
- **Team leads and operators** who want a shared knowledge base their team can access through a hosted MCP server with GitHub authentication.
- **Anyone who wants to stop losing context** — capture decisions, insights, and references as they happen, and retrieve them through natural language when you need them.

## Skills

Distillery provides 14 Claude Code slash commands:

| Skill | Purpose | Example |
|-------|---------|---------|
| [`/distill`](skills/distill.md) | Capture session knowledge with dedup detection | `/distill "We decided to use DuckDB for local storage"` |
| [`/recall`](skills/recall.md) | Semantic search with provenance | `/recall distributed caching strategies` |
| [`/pour`](skills/pour.md) | Multi-entry synthesis with citations | `/pour how does our auth system work?` |
| [`/bookmark`](skills/bookmark.md) | Store URLs with auto-generated summaries | `/bookmark https://example.com/article #caching` |
| [`/minutes`](skills/minutes.md) | Meeting notes with append updates | `/minutes --update standup-2026-03-22` |
| [`/classify`](skills/classify.md) | Classify entries and triage review queue | `/classify --inbox` |
| [`/watch`](skills/watch.md) | Manage monitored feed sources | `/watch add github:duckdb/duckdb` |
| [`/radar`](skills/radar.md) | Ambient feed digest with source suggestions | `/radar --days 7` |
| [`/tune`](skills/tune.md) | Adjust feed relevance thresholds | `/tune --digest 0.40` |
| [`/setup`](skills/setup.md) | Onboarding wizard for MCP connectivity and config | `/setup` |
| [`/digest`](skills/digest.md) | Team activity summary from internal entries | `/digest --days 7` |
| [`/gh-sync`](skills/gh-sync.md) | Sync GitHub issues/PRs into the knowledge base | `/gh-sync owner/repo` |
| [`/investigate`](skills/investigate.md) | Deep context builder with relationship traversal | `/investigate authentication flow` |
| [`/briefing`](skills/briefing.md) | Knowledge dashboard (solo and team mode) | `/briefing --project distillery` |

## Quick Start

### Step 1: Install the Plugin

```bash
claude plugin marketplace add norrietaylor/distillery
claude plugin install distillery
```

This installs all 14 skills and configures the MCP server to run **locally** via `uvx distillery-mcp` — a private, self-contained knowledge base on your machine. Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

!!! tip "Install uv"
    `curl -LsSf https://astral.sh/uv/install.sh | sh`

### Step 2: Set Your Embedding API Key (Optional but Recommended)

```bash
export JINA_API_KEY=jina_...   # free at jina.ai
```

`uvx` inherits this from your shell environment. Without a key, Distillery falls back to a stub embedding provider (search quality degraded).

Restart Claude Code and run `/setup` to complete onboarding.

### Try the Hosted Demo (Opt-In)

Want to evaluate without installing locally? Override the plugin default with the hosted demo at `distillery-mcp.fly.dev`:

```bash
claude mcp add distillery --scope user --transport http --url https://distillery-mcp.fly.dev/mcp
```

!!! warning "Demo Server"
    `distillery-mcp.fly.dev` is a **demo server** for evaluation only. Do not store sensitive or confidential data.

See [Local Setup](getting-started/local-setup.md) for full configuration (embedding providers, cloud storage, etc.) or [deploy your own instance](team/deployment.md) for team use.

## License

Apache 2.0 — see [LICENSE](https://github.com/norrietaylor/distillery/blob/main/LICENSE) for details.
