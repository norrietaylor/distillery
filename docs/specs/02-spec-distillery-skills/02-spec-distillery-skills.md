# 02-spec-distillery-skills: Core Claude Code Skills

## Introduction/Overview

Five Claude Code skills form the user-facing interface to the Distillery knowledge base. Each skill is a SKILL.md file that instructs Claude to invoke the Distillery MCP server tools. This spec covers `/distill` (capture), `/recall` (search), `/pour` (synthesize), `/bookmark` (URL storage), and `/minutes` (updatable meeting notes).

## Goals

1. Ship 5 working Claude Code skills as SKILL.md files in `.claude/skills/` within the distillery repo
2. Each skill correctly invokes the Distillery MCP server tools and handles responses including errors
3. `/distill` performs duplicate detection before storing, presenting dedup warnings to the user
4. `/recall` and `/pour` display full content with provenance (entry ID, author, timestamp, similarity score)
5. `/minutes` supports creating new meeting notes and appending to existing ones via `meeting_id`

## User Stories

- As a team member, I want to run `/distill` at the end of a session so that decisions and insights are captured in the team knowledge base
- As a team member, I want to run `/recall distributed caching` so that I get relevant entries about that topic with sources
- As a team member, I want to run `/pour authentication architecture` so that I get a synthesized overview citing multiple knowledge entries
- As a team member, I want to run `/bookmark https://example.com/article` so that the URL and an auto-generated summary are stored
- As a team member, I want to run `/minutes --update standup-2026-03-22` so that new notes are appended to the existing meeting record

## Demoable Units of Work

### Unit 1: /distill — Session Knowledge Capture

**Purpose:** Capture decisions, insights, and learnings from the current Claude Code session into the Distillery knowledge base, with duplicate detection.

**Functional Requirements:**
- The skill shall be defined in `.claude/skills/distill/SKILL.md` with YAML frontmatter containing `name: distill` and a description that triggers on "distill", "capture this", "save knowledge", "log learnings"
- The skill shall gather from the current session context: project name, key decisions made, architectural insights, action items, open questions, and key files modified
- If any context is unclear, the skill shall ask the user before proceeding
- The skill shall construct a distilled summary (not raw session dump — focus on decisions, rationale, and insights)
- Before storing, the skill shall call `distillery_find_similar` with the distilled content and threshold 0.8
- If similar entries are found (score ≥ 0.8), the skill shall present them to the user and ask: store anyway, merge with existing, or skip
- If storing, the skill shall call `distillery_store` with: content (distilled summary), entry_type "session", author (from config or ask user), project (from repo context), tags (extracted from content), and metadata containing `session_id`
- The skill shall confirm the stored entry ID to the user
- The skill shall support an optional argument for explicit content: `/distill "specific insight to capture"`

**Proof Artifacts:**
- File: `.claude/skills/distill/SKILL.md` exists with correct frontmatter and complete instructions
- Test: Manual invocation of `/distill` in a Claude Code session with the Distillery MCP server connected stores an entry retrievable via `distillery_get`

### Unit 2: /recall — Semantic Knowledge Search

**Purpose:** Search the Distillery knowledge base semantically and display results with full content and provenance.

**Functional Requirements:**
- The skill shall be defined in `.claude/skills/recall/SKILL.md` with YAML frontmatter containing `name: recall` and a description that triggers on "recall", "search knowledge", "what do we know about", "find in knowledge base"
- The skill shall accept a natural language query as `$ARGUMENTS`: `/recall distributed caching strategies`
- The skill shall call `distillery_search` with the query text, limit 10, and no filters by default
- The skill shall support optional filter flags parsed from arguments:
  - `--type <entry_type>` — filter by entry type
  - `--author <name>` — filter by author
  - `--project <name>` — filter by project
  - `--limit <n>` — override result count (default 10)
- For each result, the skill shall display:
  - Similarity score (as percentage)
  - Entry type badge (e.g., `[session]`, `[bookmark]`)
  - Full content
  - Provenance line: `ID: <id> | Author: <author> | Project: <project> | <created_at>`
  - Tags (if any)
- If no results are found, the skill shall report that clearly and suggest broadening the query
- If no arguments are provided, the skill shall ask the user what they want to search for

**Proof Artifacts:**
- File: `.claude/skills/recall/SKILL.md` exists with correct frontmatter and complete instructions
- Test: Manual invocation of `/recall` with a query returns formatted results from entries previously stored via `/distill` or `distillery_store`

### Unit 3: /pour — Multi-Entry Knowledge Synthesis

**Purpose:** Synthesize knowledge from multiple entries on a topic into a structured, cited narrative through multi-pass retrieval and interactive refinement.

**Functional Requirements:**

*Invocation and Input:*
- The skill shall be defined in `.claude/skills/pour/SKILL.md` with YAML frontmatter containing `name: pour` and a description that triggers on "pour", "synthesize", "what's the full picture on", "deep dive into"
- The skill shall accept a topic or question as `$ARGUMENTS`: `/pour how does our auth system work?`
- The skill shall support `--project <name>` to scope synthesis to a specific project
- If no arguments are provided, the skill shall ask the user what topic to synthesize

*Multi-Pass Retrieval (Graph Traversal):*
- **Pass 1 (Broad):** Call `distillery_search` with the topic, limit 20, to get initial results
- **Pass 2 (Follow-up):** Analyze Pass 1 results to identify related concepts, people, and sub-topics mentioned in the entries. For each significant related concept not covered by Pass 1, call `distillery_search` again with the related concept as query (up to 3 follow-up searches)
- **Pass 3 (Gap-filling):** If Pass 1 and Pass 2 reveal references to specific projects, people, or decisions that weren't returned, call `distillery_search` with targeted queries for those gaps (up to 2 gap-filling searches)
- Deduplicate across all passes (same entry ID → count once)
- The skill shall report total entries found and passes completed

*Structured Output Format:*
- The skill shall produce a structured synthesis with these sections:
  1. **Summary** (2-3 paragraphs) — the cohesive narrative integrating all findings, with inline citations using `[Entry <short-id>]` notation
  2. **Timeline** — if entries span multiple dates, present a chronological view of how the topic evolved (decisions, changes, reversals)
  3. **Key Decisions** — bullet list of decisions found across entries, with who made them and when
  4. **Contradictions** — flag any entries that contradict each other, showing both sides with citations
  5. **Knowledge Gaps** — areas where entries are thin, missing, or outdated. Specific suggestions for what to `/distill` next
- Omit sections that have no content (e.g., skip Timeline if all entries are from the same day)

*Source Attribution:*
- After the synthesis, list all cited entries in a **Sources** section:
  - Short ID (first 8 chars of UUID)
  - Entry type badge
  - Author
  - Date
  - First line of content (as context)
  - Similarity score from the search pass that found it

*Interactive Refinement:*
- After presenting the synthesis, the skill shall ask the user: "Would you like to go deeper on any sub-topic, or is this sufficient?"
- If the user identifies a sub-topic, the skill shall run a focused retrieval pass on that sub-topic and produce an addendum synthesis (same structured format) appended below the original
- The refinement loop continues until the user indicates they are satisfied
- Each refinement pass is clearly labeled: `## Refinement: <sub-topic>`

*Edge Cases:*
- If fewer than 2 entries are found across all passes, the skill shall fall back to `/recall` behavior (display results directly instead of synthesizing)
- If all entries are from a single author, note this as a potential knowledge gap (single perspective)

**Proof Artifacts:**
- File: `.claude/skills/pour/SKILL.md` exists with correct frontmatter and complete instructions
- Test: Manual invocation of `/pour` on a topic with 3+ stored entries produces a multi-section synthesis with inline citations, a source list, and an interactive refinement prompt

### Unit 4: /bookmark — URL Knowledge Capture

**Purpose:** Store a URL with an auto-generated summary in the Distillery knowledge base.

**Functional Requirements:**
- The skill shall be defined in `.claude/skills/bookmark/SKILL.md` with YAML frontmatter containing `name: bookmark` and a description that triggers on "bookmark", "save this link", "store this URL", "remember this page"
- The skill shall accept a URL as the first argument: `/bookmark https://example.com/article`
- The skill shall accept optional tags after the URL: `/bookmark https://example.com/article #caching #architecture`
- The skill shall fetch the URL content using the `WebFetch` tool
- The skill shall generate a concise summary (2-4 sentences) of the fetched content
- If the URL is inaccessible, the skill shall ask the user to provide a manual summary
- Before storing, the skill shall call `distillery_find_similar` with the URL + summary text to check for duplicate bookmarks
- If a duplicate is found, the skill shall warn the user and ask whether to store anyway or skip
- The skill shall call `distillery_store` with: content (summary + key points), entry_type "bookmark", metadata containing `url` and `summary`, tags (from arguments + auto-extracted), and author
- The skill shall confirm with: entry ID, URL, summary preview, and tags
- If no URL argument is provided, the skill shall ask the user for a URL

**Proof Artifacts:**
- File: `.claude/skills/bookmark/SKILL.md` exists with correct frontmatter and complete instructions
- Test: Manual invocation of `/bookmark` with a valid URL fetches content, generates summary, stores entry, and the entry is retrievable via `/recall`

### Unit 5: /minutes — Meeting Notes with Append Updates

**Purpose:** Capture meeting notes and support appending updates to existing meetings via `meeting_id`.

**Functional Requirements:**
- The skill shall be defined in `.claude/skills/minutes/SKILL.md` with YAML frontmatter containing `name: minutes` and a description that triggers on "minutes", "meeting notes", "capture meeting", "log meeting"
- **New meeting mode** (default): The skill shall gather from the user:
  - Meeting title/topic
  - Attendees
  - Key discussion points
  - Decisions made
  - Action items (with owners if known)
  - Follow-ups needed
- The skill shall generate a `meeting_id` from the date and a slugified title: `standup-2026-03-22`, `arch-review-2026-03-22`
- The skill shall call `distillery_store` with: content (formatted meeting notes), entry_type "minutes", metadata containing `meeting_id` and `attendees`, tags (extracted from content), and author
- **Update mode** (`/minutes --update <meeting_id>`): The skill shall:
  1. Call `distillery_search` with the `meeting_id` as query to find the existing entry
  2. If found, gather new content from the user (additional notes, new action items, resolved items)
  3. Call `distillery_update` with the entry ID, appending new content below a `## Update — <timestamp>` heading, incrementing the version
  4. If not found, report that no meeting with that ID exists and offer to create a new one
- The skill shall confirm with: entry ID, meeting_id, version number, and a preview of the stored content
- The skill shall support listing recent meetings: `/minutes --list` calls `distillery_list` with `entry_type: "minutes"`, limit 10

**Proof Artifacts:**
- File: `.claude/skills/minutes/SKILL.md` exists with correct frontmatter and complete instructions
- Test: Manual invocation of `/minutes` creates a meeting entry, then `/minutes --update <meeting_id>` appends to it with incremented version

## Non-Goals (Out of Scope)

- **Classification pipeline** — auto-classification, confidence scoring, and `/classify` are covered in spec 03
- **Semantic deduplication logic** — skills call `find_similar` and present results, but the skip/merge/create threshold logic belongs in spec 03
- **Ambient feed intelligence** — `/radar`, `/watch`, `/tune` are Phase 3
- **Phase 2 skills** — `/whois`, `/investigate`, `/digest`, `/briefing`, `/process`, `/gh-sync`
- **Skill tests as Python code** — skills are SKILL.md files tested by manual invocation. Automated skill testing is out of scope.
- **MCP server changes** — the 7 existing tools are sufficient. No server modifications needed.

## Design Considerations

No GUI. All output is rendered as markdown in the Claude Code terminal. Skills should:
- Use markdown headers, tables, and code blocks for structure
- Keep provenance lines compact (one line per entry)
- Use emoji sparingly and only for entry type badges if at all
- Present duplicate warnings clearly with the similar entry's content visible

## Repository Standards

- Skills live in `.claude/skills/<skill-name>/SKILL.md` within the distillery repo
- SKILL.md format: YAML frontmatter (`name`, `description`) + markdown body
- Skill names are lowercase, hyphen-free for slash command compatibility
- Each skill directory contains only `SKILL.md` (no supporting scripts for MVP)
- Follow the session-log skill pattern for structure: When to Use → Process (Steps) → Output Format → Rules

## Technical Considerations

- **MCP server must be running** — all skills depend on the Distillery MCP server being configured in the user's Claude Code settings. Skills should detect if MCP tools are unavailable and display a helpful setup message referencing `docs/mcp-setup.md`.
- **Author identification** — skills should try to determine the author from: (1) git config `user.name`, (2) environment variable `DISTILLERY_AUTHOR`, (3) ask the user. Cache the result for the session.
- **Project identification** — skills should determine the project from: (1) current git repo name, (2) `$ARGUMENTS` containing `--project`, (3) ask the user.
- **Tag extraction** — skills should extract tags from content keywords. For `/bookmark`, also parse `#tag` syntax from arguments.
- **Error handling** — if an MCP tool returns an error response (`{"error": true, ...}`), the skill should display the error message clearly and suggest corrective action.
- **WebFetch for /bookmark** — the `/bookmark` skill uses Claude Code's built-in `WebFetch` tool to retrieve URL content. This is available in all Claude Code environments.

## Security Considerations

- Skills do not handle API keys directly — the MCP server manages embedding provider credentials
- URLs fetched by `/bookmark` may contain sensitive content — the skill stores only the summary, not raw page HTML
- No PII handling beyond author names which are team-visible by design

## Success Metrics

- All 5 SKILL.md files exist in `.claude/skills/` with valid frontmatter
- Each skill can be invoked via `/command` in Claude Code with the Distillery MCP server connected
- `/distill` stores entries retrievable by `/recall`
- `/recall` returns semantically relevant results with provenance
- `/pour` synthesizes 3+ entries into a cited narrative
- `/bookmark` fetches, summarizes, and stores a URL
- `/minutes` creates a meeting entry and `/minutes --update` appends to it

## Open Questions

1. **Skill auto-invocation** — Should any skills trigger automatically (e.g., `/distill` at end of session)? For MVP, all skills are manual-only. Auto-invocation can be added via Claude Code hooks in a future iteration.
2. **Tag taxonomy** — Should tags be free-form or validated against a list? For MVP, free-form. Spec 03's classification pipeline may introduce validated tags.
3. **Author persistence** — Should the author be stored in `distillery.yaml` config? Currently determined per-session from git config. Could add `team.default_author` to config in a future iteration.
