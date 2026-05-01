<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/norrietaylor/distillery/main/docs/assets/distillery-logo-dark-512.png" width="180">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/norrietaylor/distillery/main/docs/assets/distillery-logo-512.png" width="180">
    <img alt="Distillery" src="https://raw.githubusercontent.com/norrietaylor/distillery/main/docs/assets/distillery-logo-512.png" width="180">
  </picture>
</p>

<h1 align="center">Distillery</h1>

<!-- mcp-name: io.github.norrietaylor/distillery-mcp -->

<p align="center">
  <strong>Team Knowledge, Distilled</strong>
  <br>
  Capture, classify, connect, and surface team knowledge through conversational commands.
</p>

<p align="center">
  <a href="https://norrietaylor.github.io/distillery/">Documentation</a> &middot;
  <a href="#skills">Skills</a> &middot;
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="https://norrietaylor.github.io/distillery/roadmap/">Roadmap</a> &middot;
  <a href="https://norrietaylor.github.io/distillery/presentation.html">Slides</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/distillery-mcp/"><img src="https://img.shields.io/pypi/v/distillery-mcp" alt="PyPI version"></a>
  <a href="https://pypi.org/project/distillery-mcp/"><img src="https://img.shields.io/pypi/dm/distillery-mcp" alt="PyPI downloads"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python version"></a>
</p>

---
## What is Distillery?

Distillery is a team knowledge base accessed through Claude Code skills. It refines raw information from working sessions, meetings, bookmarks, and conversations into concentrated, searchable knowledge — stored as vector embeddings in DuckDB and retrieved through natural language. Runs locally over stdio or as a hosted HTTP service with GitHub OAuth for team access.

Distillery captures the highest-value transformation — from noise to signal — and makes it a tool the whole team can use.

> **Full documentation:** [norrietaylor.github.io/distillery](https://norrietaylor.github.io/distillery/)

<p align="center">
  <img src="https://raw.githubusercontent.com/norrietaylor/distillery/main/docs/assets/distillery-demo.gif" alt="Distillery demo — /distill captures a decision, /pour synthesizes it" width="600">
</p>

## Skills

Distillery provides 14 Claude Code slash commands:

| Skill | Purpose | Example |
|-------|---------|---------|
| `/distill` | Capture session knowledge with dedup detection | `/distill "We decided to use DuckDB for local storage"` |
| `/recall` | Semantic search with provenance | `/recall distributed caching strategies` |
| `/pour` | Multi-entry synthesis with citations | `/pour how does our auth system work?` |
| `/bookmark` | Store URLs with auto-generated summaries | `/bookmark https://example.com/article #caching` |
| `/minutes` | Meeting notes with append updates | `/minutes --update standup-2026-03-22` |
| `/classify` | Classify entries and triage review queue | `/classify --inbox` |
| `/watch` | Manage monitored feed sources | `/watch add github:duckdb/duckdb` |
| `/radar` | Ambient feed digest with source suggestions | `/radar --days 7` |
| `/tune` | Adjust feed relevance thresholds | `/tune relevance 0.4` |
| `/digest` | Team activity summary from internal entries | `/digest --days 7 --project myapp` |
| `/gh-sync` | Sync GitHub issues/PRs into the knowledge base | `/gh-sync owner/repo --issues` |
| `/investigate` | Deep context builder with relationship traversal | `/investigate distributed caching` |
| `/briefing` | Team knowledge dashboard with metrics | `/briefing --days 7` |
| `/setup` | Onboarding wizard for MCP connectivity and config | `/setup` |

## Quick Start

### Step 1: Install the Plugin

```bash
claude plugin marketplace add norrietaylor/distillery
claude plugin install distillery
```

This installs all 14 skills and configures the MCP server to run **locally** via `uvx distillery-mcp` — a private, self-contained knowledge base on your machine. Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) (install: `curl -LsSf https://astral.sh/uv/install.sh | sh`).

### Step 2: Set Your Embedding API Key (Optional but Recommended)

```bash
# Get a free API key from jina.ai
export JINA_API_KEY=jina_...
```

`uvx` inherits this from your shell environment. Without a key, Distillery falls back to a stub embedding provider (search quality degraded).

Restart Claude Code and run the onboarding wizard:

```
/setup
```

### Try the Hosted Demo (Opt-In)

Want to evaluate without installing anything locally? Override the plugin default with the hosted demo at `distillery-mcp.fly.dev`:

```bash
claude mcp add distillery --scope user --transport http --url https://distillery-mcp.fly.dev/mcp
```

> **Demo Server:** `distillery-mcp.fly.dev` is for evaluation only. Do not store sensitive or confidential data.

See the [Local Setup Guide](https://norrietaylor.github.io/distillery/getting-started/local-setup/) for full configuration options, or [deploy your own instance](https://norrietaylor.github.io/distillery/team/deployment/) for team use.

## Development

```bash
uv pip install -e ".[dev]"
# or
pip install -e ".[dev]"
pytest                              # run tests
mypy --strict src/distillery/       # type check
ruff check src/ tests/              # lint
```

See [Contributing](https://norrietaylor.github.io/distillery/contributing/) for the full guide.

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
