# 04-spec-plugin-audit

## Introduction/Overview

Harden the Distillery Claude Code plugin's skill definitions and plugin metadata against best-practice recommendations. This spec covers skill frontmatter improvements (allowed-tools, disable-model-invocation, descriptions, effort/model hints), plugin.json enhancements (userConfig for sensitive keys), and CONVENTIONS.md updates. No server-side or test changes — those are covered separately in spec 05.

## Goals

1. Every skill declares its minimum required `allowed-tools` set, preventing unintended tool access
2. Side-effect skills (`/distill`, `/bookmark`, `/minutes`, `/watch`) are protected from auto-invocation via `disable-model-invocation: true`
3. Skill descriptions communicate purpose concisely instead of listing trigger phrases
4. Heavy skills (`/pour`, `/radar`) declare `context: fork` for isolated execution
5. `plugin.json` declares `userConfig` with `sensitive: true` for API keys

## User Stories

- As a **Claude Code user**, I want skills restricted to only the MCP tools they need so that unrelated tools aren't exposed during skill execution.
- As a **team member**, I want side-effect skills to require explicit invocation so that Claude doesn't auto-store or auto-watch without my intent.
- As a **plugin installer**, I want API keys configured via `userConfig` with keychain storage so that secrets aren't managed manually via environment variables.

## Demoable Units of Work

### Unit 1: Skill Frontmatter Hardening

**Purpose:** Add `allowed-tools`, `disable-model-invocation`, `context`, `effort`, and `model` fields to all 10 skill YAML frontmatter blocks, following the principle of least privilege.

**Functional Requirements:**
- Each skill's SKILL.md frontmatter shall include an `allowed-tools` field listing only the MCP tools that skill requires:

  | Skill | `allowed-tools` |
  |-------|-----------------|
  | `/recall` | `mcp__*__distillery_search`, `mcp__*__distillery_get`, `mcp__*__distillery_status` |
  | `/distill` | `mcp__*__distillery_store`, `mcp__*__distillery_check_dedup`, `mcp__*__distillery_find_similar`, `mcp__*__distillery_update`, `mcp__*__distillery_status`, `Bash(git config *)` |
  | `/pour` | `mcp__*__distillery_search`, `mcp__*__distillery_get`, `mcp__*__distillery_store`, `mcp__*__distillery_status` |
  | `/bookmark` | `mcp__*__distillery_store`, `mcp__*__distillery_check_dedup`, `mcp__*__distillery_status`, `WebFetch` |
  | `/minutes` | `mcp__*__distillery_store`, `mcp__*__distillery_search`, `mcp__*__distillery_get`, `mcp__*__distillery_update`, `mcp__*__distillery_list`, `mcp__*__distillery_status` |
  | `/classify` | `mcp__*__distillery_classify`, `mcp__*__distillery_review_queue`, `mcp__*__distillery_resolve_review`, `mcp__*__distillery_get`, `mcp__*__distillery_list`, `mcp__*__distillery_status` |
  | `/watch` | `mcp__*__distillery_watch`, `mcp__*__distillery_status`, `CronCreate`, `CronList`, `CronDelete`, `RemoteTrigger` |
  | `/radar` | `mcp__*__distillery_search`, `mcp__*__distillery_list`, `mcp__*__distillery_store`, `mcp__*__distillery_interests`, `mcp__*__distillery_suggest_sources`, `mcp__*__distillery_status` |
  | `/tune` | `mcp__*__distillery_status`, `mcp__*__distillery_update` |
  | `/setup` | `mcp__*__distillery_status`, `CronCreate`, `RemoteTrigger` |

- Skills that write data shall include `disable-model-invocation: true` in their frontmatter: `/distill`, `/bookmark`, `/minutes`, `/watch`.
- Long-running skills shall include `context: fork` in their frontmatter: `/pour`, `/radar`.
- Lightweight read-only skills shall include `effort: low`: `/recall`, `/tune`, `/setup`.
- Heavy synthesis skills shall include `effort: high`: `/pour`, `/radar`.
- All other skills shall include `effort: medium`: `/distill`, `/bookmark`, `/minutes`, `/classify`, `/watch`.

**Proof Artifacts:**
- File: Each of the 10 `SKILL.md` files contains `allowed-tools` in YAML frontmatter
- File: `/distill`, `/bookmark`, `/minutes`, `/watch` SKILL.md files contain `disable-model-invocation: true`
- File: `/pour` and `/radar` SKILL.md files contain `context: fork`

### Unit 2: Skill Description Rewrite

**Purpose:** Replace trigger-phrase-list descriptions with concise purpose statements that communicate what each skill does, reducing context token waste.

**Functional Requirements:**
- Each skill's `description` field shall be rewritten to a single sentence describing the skill's purpose, not its trigger phrases. Trigger phrases are handled by Claude Code's skill matching — descriptions should help the model understand *what the skill does*.
- Proposed descriptions:

  | Skill | New Description |
  |-------|----------------|
  | `/distill` | Capture decisions, insights, and action items from the current session into the knowledge base |
  | `/recall` | Search the knowledge base using natural language and return matching entries with provenance |
  | `/pour` | Synthesize multiple knowledge entries into a cohesive narrative with citations |
  | `/bookmark` | Save a URL with an auto-generated summary to the knowledge base |
  | `/minutes` | Capture meeting notes or append updates to an existing meeting record |
  | `/classify` | Classify knowledge entries by type and manage the manual review queue |
  | `/watch` | Add, remove, or list monitored feed sources (RSS and GitHub) |
  | `/radar` | Generate an ambient intelligence digest from recent feed activity with source suggestions |
  | `/tune` | Display and adjust feed relevance thresholds for alerts and digests |
  | `/setup` | Onboarding wizard — verify MCP connectivity, detect transport, and configure scheduled tasks |

- The trigger phrases currently in descriptions shall be preserved as a comment or documentation note within the SKILL.md body (not in the YAML frontmatter), so they remain discoverable but don't consume model context.

**Proof Artifacts:**
- File: Each SKILL.md `description` field is ≤120 characters and contains no "Triggered by:" text
- File: No SKILL.md frontmatter `description` contains single quotes or trigger-phrase lists

### Unit 3: Plugin Metadata Enhancement

**Purpose:** Add `userConfig` declarations to `plugin.json` for sensitive API keys, enabling keychain-backed secret storage instead of manual environment variable management.

**Functional Requirements:**
- `plugin.json` shall include a `userConfig` section declaring configuration fields for API keys required by the plugin:
  - `jina_api_key`: Jina embedding API key, `sensitive: true`
  - `github_client_id`: GitHub OAuth client ID (not sensitive — public value)
  - `github_client_secret`: GitHub OAuth client secret, `sensitive: true`
- Sensitive fields shall use `sensitive: true` to enable keychain storage via Claude Code's secure config system.
- Each config field shall include a `description` explaining its purpose and where to obtain the value.
- CONVENTIONS.md shall be updated to reference `userConfig` as the preferred method for API key configuration, with environment variables as fallback.

**Proof Artifacts:**
- File: `plugin.json` contains `userConfig` with `jina_api_key` and `github_client_secret` marked `sensitive: true`
- File: CONVENTIONS.md references `userConfig` for API key management

## Non-Goals (Out of Scope)

- MCP server refactoring (server.py split, error standardization) — covered in spec 05
- Test coverage improvements — covered in spec 05
- Hook definitions (`SessionStart`, `Stop`, `PostToolUse`) — deferred to future spec
- Custom agent definition (`distillery-researcher`) — deferred
- Moving skills directory from `.claude-plugin/skills/` to plugin root — keeping current location to prevent auto-loading during development
- Tool count consolidation (#99) — separate issue
- `X-Request-ID` correlation support — deferred

## Design Considerations

No specific design requirements identified. All changes are to YAML frontmatter and JSON configuration files.

## Repository Standards

- **Conventional Commits**: `chore(skills):`, `chore(plugin):`
- **YAML frontmatter**: Follow existing SKILL.md format with added fields
- **plugin.json**: Follow Claude Code plugin schema

## Technical Considerations

- The `allowed-tools` wildcard pattern `mcp__*__distillery_*` matches any MCP connector name, which is necessary because the connector name varies depending on how the plugin is installed (marketplace vs local).
- `disable-model-invocation: true` prevents Claude from auto-invoking the skill based on conversation context — it must be explicitly triggered by the user via `/skill-name`.
- `context: fork` runs the skill in an isolated subagent, preventing long-running skills from blocking the main conversation.
- `userConfig` with `sensitive: true` stores values in the OS keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service) rather than plaintext config files.

## Security Considerations

- `allowed-tools` restrictions are a defense-in-depth measure — they don't replace server-side authorization but limit the blast radius of skill execution.
- `sensitive: true` on `userConfig` fields ensures API keys are stored in the OS keychain, not in plaintext JSON files on disk.
- `disable-model-invocation` on write skills prevents unintended data mutations from Claude's autonomous behavior.

## Success Metrics

| Metric | Target |
|--------|--------|
| Skills with `allowed-tools` | 10/10 |
| Side-effect skills with `disable-model-invocation` | 4/4 |
| Skill descriptions ≤120 chars | 10/10 |
| `userConfig` sensitive fields | 2 (jina_api_key, github_client_secret) |

## Open Questions

No open questions at this time.
