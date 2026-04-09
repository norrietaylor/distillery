# /briefing — Knowledge Dashboard

Produces a single-command knowledge dashboard: recent entries, pending corrections, soon-to-expire items, stale knowledge, and unresolved work — all scoped to your project. When multiple authors are detected (or `--team` is passed), team sections are added automatically.

## Usage

```text
/briefing
/briefing --project distillery
/briefing --team
```

**Trigger phrases:** "briefing", "knowledge dashboard", "project overview", "my briefing", "team briefing"

## When to Use

- Starting a work session to orient yourself
- Checking the state of your knowledge base at a glance
- Getting a project-scoped overview of what needs attention
- Viewing team activity and cross-author context

## What It Does

### Solo Mode (default)

Displays 5 sections scoped to your project:

| Section | What it shows |
|---------|--------------|
| **Recent entries** | Latest knowledge captured (configurable limit) |
| **Corrections** | Entries with pending corrections via `entry_relations` |
| **Expiring soon** | Entries with `expires_at` approaching |
| **Stale knowledge** | Entries not updated in 30+ days |
| **Unresolved** | Items in `pending_review` status |

### Team Mode (`--team`)

Adds 3 additional sections:

| Section | What it shows |
|---------|--------------|
| **Team activity** | Recent entries from all authors |
| **Related entries** | Entries from teammates on overlapping topics |
| **Review queue** | Items awaiting classification review |

## Options

| Flag | Description |
|------|-------------|
| `--project NAME` | Scope to a specific project |
| `--team` | Enable team sections (auto-detected when multiple authors exist) |

## Session Start Hook

The `/setup` wizard can configure a `SessionStart` hook that automatically injects a condensed briefing at the start of every Claude Code session. This gives Claude awareness of recent knowledge and stale items without requiring a manual `/briefing` invocation.

See the [/setup docs](setup.md) for configuration details.

## Tips

- Run at the start of each work session to catch up on what needs attention
- Combine with `/digest` for full context — `/briefing` shows current state, `/digest` shows recent activity
- The `expires_at` section helps you stay on top of time-sensitive knowledge
- Corrections section surfaces entries that may need updating based on newer information
