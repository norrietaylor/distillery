---
title: "Building a Second Brain for Claude Code"
published: false
description: "How I built Distillery — a knowledge base that lives inside your coding assistant, capturing decisions and context before they disappear into chat history."
tags: [claudecode, devtools, knowledgemanagement, python]
canonical_url: https://norrietaylor.github.io/distillery/blog/building-a-second-brain-for-claude-code/
---

# Building a Second Brain for Claude Code

Every team I've worked on has the same problem. Someone makes a decision — a good one, usually — with a lot of context behind it. Why we chose DuckDB over Postgres. Why we inverted that dependency. Why the authentication flow goes through a middleware layer instead of a decorator. And then, six months later, someone asks "why does this work this way?" and the answer is... gone. Buried in Slack. Lost in a PR description nobody remembers. Living only in the head of the person who wrote it, if they're still on the team.

I started building Distillery to solve this problem for my own work with Claude Code. It turned into something more interesting than I expected.

## The Problem: Knowledge Lives in Chat

When you work with Claude Code all day, you're having real conversations. You're debugging, designing, deciding. Some of those conversations contain genuinely valuable knowledge — not just the code produced, but the *reasoning* behind it. The context that makes the code make sense.

But that context lives in your chat history. It's ephemeral by design. Next session, fresh context. Next week, you can't find it. Next month, a new team member joins and has no idea why things work the way they do.

The standard answers — wikis, Confluence, Notion — all share the same failure mode: they require friction to populate. A wiki doesn't help if writing to it is slower than the pace of actual work. Documentation that requires a separate workflow doesn't get written. Or it does, once, and then it rots.

The irony is that the knowledge gets *generated* constantly. Every time you and Claude Code figure out an approach, that's value. Every time you decide not to do something and explain why, that's value. It just doesn't get captured.

## The Insight: Capture Where Work Happens

The fix isn't a better wiki. The fix is making capture so frictionless that it happens at the moment of insight, without switching context.

If you're already talking to Claude Code, the capture tool should be Claude Code. Not a sidebar. Not a separate app. A slash command.

```
/distill "Decided to use DuckDB for local storage because it supports vector similarity search natively via the VSS extension. Postgres would require pgvector and a separate service. For local dev and small-team deployments, DuckDB's file-based model is significantly simpler. Revisit if we need multi-writer concurrency."
```

That's it. The decision, the reasoning, the trade-offs, captured in the moment, from inside the tool you're already using. And because it's semantic search, you can find it later in natural language:

```
/recall why did we choose DuckDB
```

This is the core insight Distillery is built on: capture-at-source, inside the assistant.

## What Distillery Does

Distillery is a knowledge base system for Claude Code. It stores, searches, and classifies knowledge entries using DuckDB with vector similarity search. It includes ambient intelligence that monitors GitHub repos and RSS feeds for relevant developments. It exposes everything through 10 Claude Code slash commands.

Here are the commands:

| Skill | What it does |
|-------|-------------|
| `/distill` | Capture knowledge from the current session |
| `/recall` | Semantic search across all knowledge |
| `/pour` | Multi-pass synthesis — summarize across many entries |
| `/bookmark` | Store URLs with auto-generated summaries |
| `/minutes` | Capture meeting notes with append support |
| `/classify` | Review and triage the review queue |
| `/watch` | Manage monitored GitHub repos and RSS feeds |
| `/radar` | Ambient digest of what's changed in your feeds |
| `/tune` | Adjust relevance scoring thresholds |
| `/setup` | Onboarding wizard for MCP connectivity |

The deduplication system is one of the things I'm most happy with. When you try to store something, Distillery checks semantic similarity against existing entries. Above 95% similarity, it skips — you already have this. Between 80-95%, it offers to merge — same concept, maybe new detail. Between 60-80%, it links — related, worth knowing about. This keeps the knowledge base from getting cluttered with near-duplicates, which is the main reason most personal knowledge systems eventually become unusable.

The `/pour` command is the one that feels most like magic. You ask a synthesis question:

```
/pour how does our authentication system work?
```

And it does a multi-pass synthesis: first pass retrieves the most relevant entries via semantic search, second pass extracts the key points, third pass synthesizes a coherent answer with citations showing which entries contributed what. For complex topics where knowledge is distributed across many entries, this is significantly better than any single search result.

The ambient intelligence layer — `/watch` and `/radar` — monitors external sources. You tell it to watch a GitHub repo or an RSS feed, and it polls periodically, scores relevance against your knowledge base using embeddings, and surfaces the most relevant updates in a digest. When a dependency you care about releases a breaking change, `/radar` tells you before you stumble into it.

## Architecture: Four Layers, Clean Separation

The architecture is four layers:

```
Skills (.claude-plugin/skills/)    ← slash commands users invoke
    ↓
MCP Server (src/distillery/mcp/)   ← 22 tools, stdio or HTTP transport
    ↓
Core Protocols (store/, embedding/) ← typed Protocol interfaces
    ↓
Backends (DuckDB, Jina, OpenAI)    ← actual storage and embedding APIs
```

The skills are Markdown files with YAML frontmatter — they're instructions for Claude Code, not code. The MCP server is where the actual logic lives. The core protocols are Python `Protocol` classes (structural subtyping, not ABCs) that define the contract between layers. The backends implement those protocols.

I chose MCP for the transport layer for a specific reason: it means Distillery tools are available to any MCP-compatible client, not just Claude Code. And because FastMCP handles the wire protocol, I can focus on the tool logic.

The transport choice — stdio or HTTP — matters for deployment. Stdio is simpler: the MCP server runs as a subprocess of Claude Code, single user, no authentication needed. HTTP transport enables multi-user deployment: multiple Claude Code instances connect to a shared server, authentication is handled via GitHub OAuth, and the knowledge base is genuinely shared.

```python
# Stdio: local single-user
distillery-mcp

# HTTP: team deployment with GitHub OAuth
distillery-mcp --transport http --port 8000
```

For storage, DuckDB with the VSS extension handles both structured queries and vector similarity search in a single file. No separate vector database. No Postgres. For local dev and small-team deployment, this is the right trade-off — simple operations (backup is `cp distillery.db distillery.db.bak`), good enough performance, no infrastructure overhead.

The embedding layer is pluggable. Default is Jina AI's embedding API (good quality, generous free tier). OpenAI's embeddings work too. The `EmbeddingProvider` protocol makes it straightforward to add others.

## Team Access: GitHub OAuth on Fly.io

Running Distillery locally is a one-person knowledge base. The interesting case is team access: shared knowledge that everyone on the team can read and write.

The HTTP transport with GitHub OAuth handles this. You deploy to Fly.io (or any host), configure GitHub OAuth credentials, and every team member connects their Claude Code to the same server. Knowledge captured by one person is searchable by everyone. `/pour` synthesizes across the whole team's collective knowledge.

The Fly.io deployment is designed to be minimal: a single Fly machine with a persistent volume for DuckDB, a GitHub OAuth app for authentication, and the MCP server running in HTTP mode. The whole thing fits in Fly's free tier for small teams.

```bash
# Deploy to Fly.io
cd deploy/fly
fly launch
fly secrets set GITHUB_CLIENT_ID=... GITHUB_CLIENT_SECRET=...
fly deploy
```

After that, team members add the server URL to their Claude Code MCP configuration:

```json
{
  "mcpServers": {
    "distillery": {
      "type": "http",
      "url": "https://your-app.fly.dev/mcp"
    }
  }
}
```

## Demo Flow: Distill, Recall, Pour

Here's the pattern I use most during a working session.

We're building a new feature — say, adding webhook support to the MCP server. The conversation with Claude Code involves several decisions: how to handle request validation, what to do about payload size limits, why we're using a specific ASGI pattern for routing. As I make those decisions, I capture them:

```
/distill "Webhook endpoint validates signatures using HMAC-SHA256. Raw request body must be read before parsing to preserve the signature. Store raw bytes in request state for the validator middleware."

/distill "Using Starlette's ASGI dispatcher instead of Mount for webhook routing because Mount doesn't correctly forward request scope. Bug filed upstream."

/distill "Payload size limit set to 1MB to match GitHub's webhook payload cap. Larger payloads are rejected with 413. This is a deliberate constraint, not a limitation."
```

Three entries. Takes about 30 seconds total.

A month later, someone asks why the webhook validation is structured the way it is:

```
/recall webhook signature validation
```

Returns the first entry immediately — the reasoning is right there. If they want the full picture:

```
/pour how does webhook handling work in the MCP server?
```

Returns a synthesized answer pulling from all three entries, with citations. New team members can understand the design in minutes instead of spending an afternoon reading code.

## What's Next

The current roadmap has a few areas I'm actively working on:

**Prefect deployment** — Fly.io is good for simple deployments, but for teams that want scheduled feed polling as managed Prefect flows rather than a cron job, there's a Prefect deployment path in progress.

**MCP directory listings** — Distillery will be submitted to the major MCP directories (Glama, mcp.so, Smithery) once the package is on PyPI. This is mostly a submission process rather than development work.

**PyPI release** — The package is currently installed from source. Getting it onto PyPI makes the installation path significantly simpler and enables the version badge in the README to mean something.

**Classification improvements** — The LLM-based classification engine uses a confidence threshold (default 60%) to decide what goes to the review queue. I want to experiment with few-shot examples in the classification prompt to improve precision on domain-specific knowledge.

The full roadmap is at [norrietaylor.github.io/distillery/roadmap/](https://norrietaylor.github.io/distillery/roadmap/).

## Try It

The quickest way to try Distillery is through the Claude Code plugin marketplace:

```bash
claude plugin marketplace add norrietaylor/distillery
claude plugin install distillery
```

Then run the onboarding wizard from a Claude Code session:

```
/setup
```

The wizard checks MCP connectivity, detects whether you're on stdio or HTTP, and walks you through configuration. If you want to connect to the demo server to try it without any setup, `/setup` handles that too. (The demo server at `distillery-mcp.fly.dev` is for evaluation only — don't store anything sensitive there.)

For local setup from source:

```bash
git clone https://github.com/norrietaylor/distillery.git
cd distillery
pip install -e .
```

You'll need a Jina AI API key for embeddings (free tier is generous) and then to configure the MCP server in Claude Code's settings. The [Local Setup Guide](https://norrietaylor.github.io/distillery/getting-started/local-setup/) walks through the full process.

For team deployment on Fly.io, see the [Fly.io deployment guide](https://norrietaylor.github.io/distillery/team/fly/). It's a 15-minute setup if you have Fly CLI installed and a GitHub OAuth app ready.

---

The thing I keep coming back to is that the knowledge problem is fundamentally a friction problem. Every system that requires you to leave your current context to capture knowledge will fail. The capture has to be where the work is.

For teams using Claude Code, that's already solved: the capture tool is Claude Code. Distillery just gives that capture tool a place to store things, and a way to get them back.

I'd love to hear what use cases you're running into — find me on GitHub at [norrietaylor/distillery](https://github.com/norrietaylor/distillery) or drop a comment below.
