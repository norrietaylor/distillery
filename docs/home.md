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

Distillery provides 10 Claude Code slash commands:

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

## Quick Start

The fastest way to get started:

```bash
# Install the plugin (all 10 skills + MCP connection)
claude plugin marketplace add norrietaylor/distillery
claude plugin install distillery
```

Then run the onboarding wizard in Claude Code:

```text
/setup
```

This verifies MCP connectivity, detects your transport, and configures auto-poll for ambient intelligence.

For other installation options, see [Plugin Install](getting-started/plugin-install.md) or [Local Setup](getting-started/local-setup.md).

## License

Apache 2.0 — see [LICENSE](https://github.com/norrietaylor/distillery/blob/main/LICENSE) for details.
