---
title: "Full-Proof: Distillery 0.4.0 and the Agent Memory Problem"
published: false
description: "Why the agent-memory crisis makes API stability load-bearing, and what Distillery 0.4.0 ships to meet it."
tags: [claudecode, mcp, devtools, release, memory]
canonical_url: https://norrietaylor.github.io/distillery/blog/distillery-0-4-0-full-proof/
---

# Full-Proof: Distillery 0.4.0 and the Agent Memory Problem

!!! note "Release summary"
    Distillery 0.4.0 shipped April 19, 2026. It's the release where the
    MCP tool surface becomes a public contract: stable tool names,
    consistent error codes, predictable response shapes. The release
    body lives on the [GitHub release page](https://github.com/norrietaylor/distillery/releases/tag/v0.4.0).

A few weeks ago I wrote [the first post in this series](building-a-second-brain-for-claude-code.md) about why I built Distillery. The short version: the knowledge your team generates while working with Claude Code is mostly evaporating, and the fix is to capture it where the work happens, not in a separate tool.

That was the capture story. This post is about the memory story, and why I spent a release hardening the surface instead of shipping features.

## What Karpathy's LLM Wiki actually argues

The shape of the agent-memory conversation changed in April. Karpathy posted his "LLM Wiki" idea to Hacker News, and within a week the pattern had been cloned into at least five projects: Knowledge Raven, Memoriki, OpenTrace KG-MCP, OptiVault, and a handful of Obsidian harness variants. The shape of the argument, simplified:

- Raw sources are not useful on their own. Chat logs, PRs, tickets, and docs are too lossy to reason over directly.
- The intermediate layer is an LLM-maintained wiki that compounds synthesis over time. You don't re-derive context per query. You maintain a living artifact.
- A query layer sits on top of that, CLAUDE.md-style and schema-first, trimmed for whatever context budget the model in use gives you.

Distillery was already built around this pattern. `/distill` writes, `/recall` queries, `/pour` synthesizes. What Karpathy's post did was make the pattern legible to a much broader audience, and put a name on what everyone was converging toward.

The operational side of the wiki pattern is where the interesting work actually lives, though, and it's where contributor feedback shaped what 0.x shipped. Every entry carries provenance (author, session ID, source). Every entry can be corrected without losing its history. Entries can be marked expired or unreliable without being deleted (issue #177). Those aren't decorative. They're the primitives that let a shared knowledge base admit it was wrong, which is what separates a living memory layer from a static dump.

My own investigation of the memory research last week kept landing on the same conclusion. Three-tier layered memory (fast index on top, episodes in the middle, raw transcripts on demand) is now the default pattern. LongMemEval-S at 73% is a reasonable community-stack baseline (BGE-M3 plus Flash-2.5-lite), and MemPalace's ChromaDB-backed stack has since posted 96.6% on LongMemEval R@5 in raw mode, which is the kind of jump worth watching. Distillery is tracking a LongMemEval retrieval benchmark and transcript-mining integration in issue #233 so we can measure against the same yardstick. The leaked Claude Code memory internals, three subsystems plus a "Dream" consolidation pass, is almost exactly this architecture. The failures in agent memory aren't mostly retrieval: they sit in the reasoning layer between retrieval and action, and in the moment a session ends and all the volatile context evaporates.

## The memory layer is load-bearing

If you're building agents, the memory layer sits under everything else. Planners read from it. Tools write to it. Evals depend on it being deterministic across runs. When Claude Managed Agents launched in April with memory labeled "research preview," the entire community ecosystem (memsearch, Honcho, Hippo, Memoriki, thebrain, Knowledge Raven, Octopoda, MemPalace) rushed to fill the gap, because nobody ships serious agent work on top of a preview.

The same argument applies one layer down. If the memory layer you build on has drifting tool names, inconsistent error codes, response envelopes that change shape between minor versions, and defaults that flood your context window without warning, every downstream agent inherits that instability. Planners inherit it. Evals inherit it. Shared team knowledge bases inherit it.

That's what this release is about.

## The stability pledge

From 0.4.0 onward, the MCP tool surface is a public contract. That covers:

- Tool names
- Parameter shapes and defaults
- Error codes
- Response envelopes

Breaking changes require a major version bump. Evolution happens additively: new optional parameters, new tools, new output modes behind an explicit opt-in. Skills and plugins can declare `min_server_version` with confidence that the surface they compiled against will still be there.

This is a commitment, not a feature flag. If something has to break, it breaks on a major, with a deprecation window and loud warnings on the deprecated path first.

## What shipped in 0.4.0

Sixty-plus PRs landed under the `staging/api-hardening` line. The narrative categories:

**API surface hardening.** `distillery_store`'s `dedup_action` now means what it says (#332). `"stored"` means a new row was written. `"merged"` and `"linked"` are reserved for true folds, not informational similarity hints; the similarity signal lives on `existing_entry_id` and `similarity` where it belongs. `distillery_list` defaults to `output_mode="summary"` (#311), which shrinks a typical `limit=50` gh-sync response from roughly 300 KB of content to a few kilobytes of titles, tags, and previews. Error codes consolidated on a single `ToolErrorCode` enum across every tool. `resolve_review` is idempotent for no-op transitions (#333). Canonical `entry_type` values are suggested on `INVALID_PARAMS`.

**Storage quality.** Aborted transactions roll back and surface query failures in `distillery_status` instead of swallowing them (#363). WAL is flushed after writes and preserved on recovery, with signature matching (#346). FTS WAL replay no longer fails on cold start (#349). The "ghost entry ID" class of bug is gone. `storage_bytes` scopes to the filtered set when filters are active, so usage numbers stop lying about what you actually searched.

**Feeds.** `gh-sync` now runs async via server-side background jobs (#348), so long syncs don't block the caller. Poll `distillery_sync_status` for progress. Liveness fields are populated across poll and sync paths (#334), so `/watch` reports accurate freshness. Crucially for anyone using ambient intelligence: feed entries are now excluded from the interest profile, which means `/radar` no longer drifts toward whatever feed happens to be loudest that week.

**Scheduling.** `/setup` and `/watch` now configure Claude Code routines (#272) instead of CronCreate jobs or GitHub Actions webhook scheduling. Three routines ship: hourly feed poll, daily stale check, weekly maintenance. The webhook endpoints (`/hooks/poll`, `/hooks/rescore`, `/hooks/classify-batch`) are deprecated and log warnings when hit. `/api/maintenance` is retained for orchestrated ops.

## What this unlocks

Stability is boring on its own. What makes it worth writing about is everything it lets other people do.

**Dashboards.** There's a SvelteKit dashboard in progress (the `dashboard/` directory in the repo is the seed). With the MCP surface contracted, the dashboard can ship pinned against `min_server_version=0.4.0`, and nothing downstream will break when internal implementations move.

**Community plugins.** If you want to build on top of the Distillery MCP tools, you can pin against the 0.4.0 contract with the same confidence you'd pin against any public SDK.

**Memory-layer integrations.** LangChain orchestrators, Letta-style stateful-agent frameworks, and any MCP-native runtime can now treat Distillery as a durable backend instead of a moving target.

*_Stability is the prerequisite for anyone else building on top._*

## Try it

```bash
uvx distillery-mcp@0.4.0
# or
pip install distillery-mcp==0.4.0
```

The hosted demo server at `https://distillery-mcp.fly.dev/mcp` has been redeployed to match. If you're coming from an older version, nothing you wrote against the 0.3.x surface should break. If it does, that's now a bug against the pledge, not a design decision, and I want to hear about it.

The full release notes are on the [GitHub release](https://github.com/norrietaylor/distillery/releases/tag/v0.4.0). The discussion thread lives in [GitHub Discussions](https://github.com/norrietaylor/distillery/discussions).

---

Karpathy's point about the LLM Wiki is that knowledge compounds when the layer under your agent is treated as infrastructure, not as something you rebuild every sprint. That's the model 0.4.0 commits to. Pour a full-proof one.
