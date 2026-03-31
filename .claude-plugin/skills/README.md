# Distillery Skills

This directory contains Claude Code skills that integrate with the Distillery knowledge base MCP server.

## Available Skills

Each skill is located in its own subdirectory:

- **`distill/`** — `/distill` — Capture session knowledge with duplicate detection
- **`recall/`** — `/recall` — Semantic search for knowledge entries
- **`pour/`** — `/pour` — Multi-entry synthesis and deep dives
- **`bookmark/`** — `/bookmark` — Store and summarize URLs
- **`minutes/`** — `/minutes` — Create and update meeting notes

## Getting Started

### 1. Set Up the Distillery MCP Server

Each skill requires the Distillery MCP server to be configured in your Claude Code settings.

See `/docs/mcp-setup.md` for setup instructions.

### 2. Using a Skill

Once the MCP server is configured, invoke a skill using the `/` slash command:

```
/distill
/recall distributed caching
/pour authentication system
/bookmark https://example.com/article
/minutes --update standup-2026-03-22
```

### 3. Skill Structure

Each skill is defined in a `SKILL.md` file with YAML frontmatter and markdown instructions:

```yaml
---
name: distill
description: "Capture session knowledge..."
---

# Distill — Session Knowledge Capture

[Instructions follow...]
```

When you invoke a skill, Claude Code loads the `SKILL.md` file and executes the instructions.

## Conventions

All skills follow shared conventions for consistency. See `CONVENTIONS.md` for:

- SKILL.md structure and format
- Author and project identification patterns
- MCP unavailability detection and error handling
- Tag extraction and metadata storage
- Provenance and versioning rules

## Developing New Skills

To create a new skill:

1. Create a subdirectory: `mkdir .claude/skills/<skill-name>/`
2. Create `SKILL.md` with frontmatter and instructions (follow the session-log pattern)
3. Reference `CONVENTIONS.md` for shared patterns
4. Test manually with the MCP server running
5. Ensure you include error handling for MCP unavailability

## MCP Tools Available

The Distillery MCP server provides these tools:

- `distillery_status` — Check server health and database stats
- `distillery_store` — Store a new knowledge entry
- `distillery_search` — Semantic search for entries
- `distillery_find_similar` — Find duplicate entries
- `distillery_get` — Retrieve an entry by ID
- `distillery_update` — Partially update an entry
- `distillery_list` — List entries with filtering

See `/docs/mcp-setup.md` for full tool documentation.

## Debugging

If a skill doesn't work:

1. **Verify MCP server is configured:** Check your Claude Code settings file (`.claude/settings.json`)
2. **Verify MCP server is running:** Try calling `distillery_status` directly
3. **Check skill format:** Ensure the SKILL.md has valid YAML frontmatter and proper structure
4. **Check error messages:** MCP errors appear in the skill output

For more details, see `/docs/mcp-setup.md#troubleshooting`.
