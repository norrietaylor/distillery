---
title: "Building a Second Brain for Claude Code"
published: false
description: "How I built Distillery — The problem isn't generating knowledge. It's retaining it..."
tags: [claudecode, mcp, devtools, knowledgemanagement, python]
canonical_url: https://norrietaylor.github.io/distillery/blog/building-a-second-brain-for-claude-code/
---

# Building a Second Brain for Claude Code

!!! note "Updated for Distillery 0.4.0"
    The tool counts, skill list, and examples in this post were refreshed
    for the Distillery 0.4.0 release (April 2026) — the MCP surface
    consolidation that landed in `staging/api-hardening` folded eight
    tools into broader handlers, moved feed polling/rescoring to webhook
    endpoints, and lifted the skill total to fourteen. Earlier drafts
    reflecting the pre-0.4 surface have been overwritten.

Every team I've worked on has the same problem. Someone makes a decision — a good one, usually — with a lot of context behind it. Why we chose DuckDB over Postgres. Why we inverted that dependency. Why the authentication flow goes through a middleware layer instead of a decorator. And then, six months later, someone asks "why does this work this way?" and the answer is... gone. Buried in Slack. Lost in a PR description nobody remembers. Living only in the head of the person who wrote it, if they're still on the team.

In the age of agentic development this fundamental problem has only been exacerbated. The time it takes to code up an epic is no longer the long pole in the SDLC tent. Knowledge is being generated at exponential rates and no one seems to be able to keep up.

*_The problem isn't generating knowledge. It's retaining it._*

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

Distillery is a knowledge base system for Claude Code. It stores, searches, and classifies knowledge entries using DuckDB with vector similarity search. It includes ambient intelligence that monitors GitHub repos and RSS feeds for relevant developments. It exposes 16 MCP tools and 14 Claude Code slash commands. Install it with `pip install distillery-mcp`.

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

The deduplication system is one of the things I'm most happy with. When you try to store something, Distillery checks semantic similarity against existing entries. Above 95% similarity, it skips — you already have this. Between 80-95%, it offers to merge — same concept, maybe new detail. Between 60-80%, it links — related, worth knowing about. This keeps the knowledge base from getting cluttered with near-duplicates, which is the main reason most personal knowledge systems eventually become unusable. (Details in the [dedup docs](https://norrietaylor.github.io/distillery/architecture/deduplication/).)

The `/pour` command is the one that feels most like magic. You ask a synthesis question:

```
/pour how does our authentication system work?
```

And it does a multi-pass synthesis: first pass retrieves the most relevant entries via semantic search, second pass extracts the key points, third pass synthesizes a coherent answer with citations showing which entries contributed what. For complex topics where knowledge is distributed across many entries, this is significantly better than any single search result. See the [pour docs](https://norrietaylor.github.io/distillery/skills/pour/) for examples.

## Ambient Intelligence: The Game Changer

The feature that changed how I work isn't capture or search — it's ambient intelligence. The `/watch` and `/radar` commands turn Distillery from a passive knowledge store into something that actively works for you.

Here's the idea: you tell Distillery to watch sources — GitHub repos, RSS feeds, subreddits — and it polls them on a schedule. But it doesn't just dump everything into a feed. It *scores every item for relevance against your existing knowledge base* using embedding similarity. If an item is semantically close to things you've already captured, it surfaces. If it's noise, it's filtered out.

```
/watch add https://github.com/anthropics/claude-code
/watch add https://simonwillison.net/atom/everything
```

The scoring pipeline has layers that make it genuinely smart:

**Interest-boosted relevance.** Distillery mines your knowledge base to build an interest profile — your most-used tags (recency-weighted, so recent work matters more than old entries), your bookmarked domains, your tracked repos, your expertise areas. When a feed item matches entries tagged with your top interests, the relevance score gets boosted by up to 15%. This creates a positive feedback loop: the more you capture about a topic, the better Distillery gets at finding related content.

**Trust-weighted sources.** Not all sources are equal. You can set a `trust_weight` per source — your team's own repos at 1.0, a secondary blog at 0.7. The poller multiplies all scores by trust weight, giving you a tunable signal-to-noise ratio.

**Two-tier thresholds.** Items scoring above 0.85 trigger alerts. Items between 0.60 and 0.85 are quietly stored for the next digest. Below 0.60, they're dropped. This prevents alert fatigue while still capturing everything worth knowing. Both thresholds are adjustable via `/tune`.

**Smart deduplication.** When the same story appears in three different feeds, Distillery catches it. A fast external ID check filters exact duplicates, then semantic dedup at 0.95 similarity catches rephrased duplicates. Batch-aware dedup prevents items from the same poll run from blocking each other.

When you're ready for your briefing:

```
/radar
```

You get a synthesized digest grouped by source, with cross-cutting themes highlighted and links to the original items. Add `--suggest` and Distillery will recommend new sources based on your interest profile — repos you reference but don't track, domains you bookmark but don't follow.

The whole system runs on a schedule — hourly polls, daily rescoring, weekly maintenance — without any manual intervention. Your knowledge base gets smarter over time because the interest profile evolves as you capture more. I've caught breaking changes in dependencies, relevant new tools, and team-relevant discussions days before I would have otherwise. See the [feed system docs](https://norrietaylor.github.io/distillery/skills/watch/) and [radar docs](https://norrietaylor.github.io/distillery/skills/radar/) for the full details.

## Architecture: Four Layers, Clean Separation

The architecture is four layers:

```
Skills (skills/)                   ← slash commands users invoke
    ↓
MCP Server (src/distillery/mcp/)   ← 16 tools, stdio or HTTP transport
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

## Team Access: GitHub OAuth

Running Distillery locally is a one-person knowledge base. The interesting case is team access: shared knowledge that everyone on the team can read and write.

The HTTP transport with GitHub OAuth handles this. You deploy, configure GitHub OAuth credentials, and every team member connects their Claude Code to the same server. Knowledge captured by one person is searchable by everyone. `/pour` synthesizes across the whole team's collective knowledge.

## What's Next

Distillery v0.1.0 is [now on PyPI](https://pypi.org/project/distillery-mcp/) — `pip install distillery-mcp`. With the package published, the next priorities are:

**MCP directory listings** — Submitting to the major MCP directories (Glama, mcp.so, Smithery, modelcontextprotocol.io) so teams can discover Distillery where they're already looking for MCP servers.

**Team skills** — The next wave of skills is built around shared knowledge bases. `/whois` builds an evidence-backed expertise map from contributions — who on the team knows what, backed by the entries they've captured. `/digest` generates team activity summaries so everyone stays aware of what others are learning. `/briefing` provides a dashboard view of the team's collective knowledge state. `/investigate` compiles deep context on a domain by synthesizing across the whole team's entries. `/gh-sync` connects GitHub issues and PRs as knowledge sources. These are designed for teams running a shared Distillery instance with GitHub OAuth, where the real value compounds — every team member's captures make everyone else's searches and syntheses better. See the [roadmap](https://norrietaylor.github.io/distillery/roadmap/) for the full list.

**Classification improvements** — The LLM-based classification engine uses a confidence threshold (default 60%) to decide what goes to the review queue. I want to experiment with few-shot examples in the classification prompt to improve precision on domain-specific knowledge.

The full roadmap is at [norrietaylor.github.io/distillery/roadmap/](https://norrietaylor.github.io/distillery/roadmap/).

## Try It

From the Claude Code plugin marketplace:

```bash
claude plugin marketplace add norrietaylor/distillery
claude plugin install distillery
```

Then run the onboarding wizard from a Claude Code session:

```
/setup
```

The wizard checks MCP connectivity, detects whether you're on stdio or HTTP, and walks you through configuration. If you want to connect to the demo server to try it without any setup, `/setup` handles that too. (The demo server at `distillery-mcp.fly.dev` is for evaluation only — don't store anything sensitive there.)

You'll need a Jina AI API key for embeddings (free tier is generous) and then to configure the MCP server in Claude Code's settings. The [Local Setup Guide](https://norrietaylor.github.io/distillery/getting-started/local-setup/) walks through the full process.

---

The thing I keep coming back to is that the knowledge problem is fundamentally a friction problem. Every system that requires you to leave your current context to capture knowledge will fail. The capture has to be where the work is.

For teams using Claude Code, that's already solved: the capture tool is Claude Code. Distillery just gives that capture tool a place to store things, and a way to get them back.

I'd love to hear what use cases you're running into — find me on GitHub at [norrietaylor/distillery](https://github.com/norrietaylor/distillery), check out the [full documentation](https://norrietaylor.github.io/distillery/), or drop a comment below.
