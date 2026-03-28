# 08-spec-infrastructure-improvements

## Introduction/Overview

This spec extends the Distillery data model with two foundational infrastructure features for Phase 2 team expansion: a hierarchical namespace taxonomy for tags and new entry type schemas with validated metadata. Together these provide the structured organization and richer entity types needed before scaling from single-user to team use.

## Goals

1. Add hierarchical slash-separated tag namespaces with validation and prefix-based querying
2. Introduce four new entry types (`person`, `project`, `digest`, `github`) with type-specific metadata schemas
3. Enforce strict metadata validation on new entry types at the store layer
4. Maintain full backward compatibility with existing flat tags and current entry types
5. Expose namespace and type schema features through MCP tools

## User Stories

- As a **user**, I want to organize tags hierarchically (e.g. `project/billing-v2/decisions`) so that I can filter knowledge by project, domain, and category without flat-tag clutter.
- As a **user**, I want to search entries by tag prefix (e.g. all tags under `project/billing-v2/`) so that I can retrieve all knowledge related to a specific project subtree.
- As a **user**, I want to store person entries with required expertise metadata so that `/whois` queries can find domain experts.
- As a **user**, I want to store github entries with required repo and issue/PR metadata so that `/gh-sync` can track external references.
- As a **contributor**, I want type-specific metadata validation so that malformed entries are rejected at store time rather than causing downstream failures.

## Demoable Units of Work

### Unit 1: Hierarchical Tag Namespace

**Purpose:** Add slash-separated hierarchical tag validation, prefix-based tag querying, and a new MCP tool for tag tree exploration — while keeping existing flat tags fully functional.

**Functional Requirements:**

- The system shall accept tags in the format `segment/segment/.../segment` where each segment matches `[a-z0-9]([a-z0-9-]*[a-z0-9])?` (lowercase alphanumeric with internal hyphens)
- The system shall continue to accept flat tags (no slashes) using the same segment format — existing entries are unaffected
- The system shall provide a `validate_tag(tag: str) -> bool` function in `src/distillery/models.py` that returns `True` for valid flat or hierarchical tags
- The `Entry` dataclass `__post_init__` (or a factory validator) shall validate all tags on construction and raise `ValueError` for invalid tags
- The `DuckDBStore.search()` and `DuckDBStore.list_entries()` methods shall support a new `tag_prefix` filter key that matches any tag starting with the given prefix followed by `/` (e.g. `tag_prefix="project/billing"` matches `project/billing/decisions` and `project/billing/api` but not `project/billing-v2`)
- The `distillery_search` and `distillery_list` MCP tools shall accept an optional `tag_prefix` parameter
- The system shall provide a `distillery_tag_tree` MCP tool that returns a nested tree structure of all tags currently in use, with entry counts at each node
- The `distillery_tag_tree` tool shall accept an optional `prefix` parameter to return only a subtree
- The tag validation shall pass `mypy --strict` and `ruff check`

**Proof Artifacts:**

- Test: `tests/test_tags.py` passes — covers valid/invalid tag formats, hierarchical tags, flat tag backward compatibility, tag prefix filtering in search and list, and tag tree generation
- CLI: `distillery_tag_tree` returns `{"tree": {"project": {"billing-v2": {"decisions": {"count": N}}}}}` after storing entries with hierarchical tags
- Test: `distillery_search` with `tag_prefix="project/billing-v2"` returns only entries tagged under that namespace
- Test: Existing entries with flat tags remain queryable and pass validation

### Unit 2: Entry Type Schemas with Metadata Validation

**Purpose:** Add four new entry types (`person`, `project`, `digest`, `github`) with strict type-specific metadata schemas, validated at store time.

**Functional Requirements:**

- The `EntryType` enum shall add four new members: `PERSON = "person"`, `PROJECT = "project"`, `DIGEST = "digest"`, `GITHUB = "github"`
- The system shall define a `TYPE_METADATA_SCHEMAS` registry in `src/distillery/models.py` mapping each new `EntryType` to its required and optional metadata keys with types:
  - `person`: required `expertise` (list[str]), optional `github_username` (str), `team` (str), `role` (str)
  - `project`: required `repo` (str), optional `status` (str), `team` (str), `description` (str)
  - `digest`: required `period_start` (str, ISO date), `period_end` (str, ISO date), optional `project` (str), `entry_count` (int)
  - `github`: required `repo` (str), `ref_type` (str, one of `issue`, `pr`, `discussion`, `release`), `ref_number` (int), optional `title` (str), `state` (str), `url` (str)
- The existing seven entry types (`session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`) shall have NO required metadata — fully backward compatible
- The system shall provide a `validate_metadata(entry_type: EntryType, metadata: dict) -> list[str]` function that returns a list of validation error messages (empty list = valid)
- The `DuckDBStore.store()` method shall call `validate_metadata()` and raise `ValueError` if validation fails for the entry's type
- The `DuckDBStore.update()` method shall re-validate metadata after applying updates when the entry uses a type with a schema
- The `distillery_store` MCP tool shall return validation errors in the response (not silently drop them) when metadata is invalid
- The system shall provide a `distillery_type_schemas` MCP tool that returns the full schema registry as JSON, so callers can discover required/optional fields per type
- All new code shall pass `mypy --strict` and `ruff check`

**Proof Artifacts:**

- Test: `tests/test_type_schemas.py` passes — covers all four new types with valid metadata, missing required fields, wrong field types, update re-validation, and backward compatibility for existing types
- CLI: `distillery_store` with `entry_type="person"` and missing `expertise` returns a validation error
- CLI: `distillery_store` with `entry_type="github"` and valid metadata succeeds and returns the entry ID
- CLI: `distillery_type_schemas` returns JSON with all type schemas including required/optional field definitions
- Test: Existing entry types (`session`, `bookmark`, etc.) continue to accept any metadata without validation errors

### Unit 3: Config & Skill Integration

**Purpose:** Wire the new tag namespace and type schema features into configuration and update existing skills to use hierarchical tags.

**Functional Requirements:**

- The `distillery.yaml` config shall support a new `tags` section with:
  - `enforce_namespaces` (bool, default `false`): when `true`, all new tags must contain at least one `/` separator (flat tags rejected on new entries, existing entries unaffected)
  - `reserved_prefixes` (list[str], default `[]`): top-level namespace prefixes that only specific sources can use (e.g. `["system"]` reserves `system/*` tags)
- The `DistilleryConfig` dataclass shall add a `TagsConfig` with the above fields
- The `_validate()` function shall validate `reserved_prefixes` entries are valid tag segments
- The `/distill` skill (`SKILL.md`) shall be updated to suggest hierarchical tags based on project context (e.g. `project/{repo-name}/sessions`)
- The `/bookmark` skill (`SKILL.md`) shall be updated to suggest hierarchical tags (e.g. `source/bookmark/{domain}`)
- The `distillery_store` MCP tool shall enforce `reserved_prefixes` — reject tags using a reserved prefix unless the entry source matches an allowed list
- All config parsing and validation shall pass `mypy --strict` and `ruff check`

**Proof Artifacts:**

- Test: `tests/test_config.py` updated — covers `tags` config parsing, `enforce_namespaces` flag, `reserved_prefixes` validation
- Test: With `enforce_namespaces=true`, flat tags are rejected on new entries but accepted on existing entry reads
- Test: Reserved prefix enforcement blocks unauthorized tag usage
- File: `.claude/skills/distill/SKILL.md` contains hierarchical tag suggestion step
- File: `.claude/skills/bookmark/SKILL.md` contains hierarchical tag suggestion step
- File: `distillery.yaml.example` contains `tags` section with comments

## Non-Goals (Out of Scope)

- Auto-migration of existing flat tags to hierarchical format
- Tag rename/refactor tooling
- Elasticsearch migration or any storage backend changes
- Access control or visibility flags
- Session capture hooks
- Provenance tracking
- UI for tag tree browsing (MCP tool only)
- Metadata schema evolution or versioning

## Design Considerations

- Tag tree output from `distillery_tag_tree` uses nested JSON matching the slash hierarchy, with `count` leaf nodes
- Type schema registry is a plain Python dict, not a separate config file — keeps it co-located with the enum
- Validation errors are returned as structured lists, not exceptions, at the MCP layer — the store layer uses exceptions

## Repository Standards

- Conventional Commits: `feat(models):`, `feat(store):`, `feat(mcp):`, `feat(config):`, `docs(skills):`
- Scopes: `models`, `store`, `mcp`, `config`, `skills`
- mypy strict for `src/`, relaxed for `tests/`
- ruff with existing rule set (line length 100, E501 ignored)
- Shared `conftest.py` fixtures for new test modules
- All async tests use `asyncio_mode = "auto"`

## Technical Considerations

- Tag validation regex: `^[a-z0-9]([a-z0-9-]*[a-z0-9])?(/[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$`
- `tag_prefix` filter in DuckDB uses `list_filter(tags, t -> starts_with(t, ? || '/'))` or equivalent DuckDB list function
- `distillery_tag_tree` aggregates by scanning all entries' tags — acceptable at current scale (<10K entries). At scale, consider a materialized tag index.
- `TYPE_METADATA_SCHEMAS` uses a simple dict structure: `{EntryType: {"required": {"field": type}, "optional": {"field": type}}}` — type checking is isinstance-based at runtime
- The `validate_metadata` function is pure (no I/O) and can be called from both store and MCP layers
- Adding `__post_init__` tag validation to `Entry` may break existing test factories — `make_entry()` in conftest.py must be updated to produce valid tags

## Security Considerations

- `reserved_prefixes` prevents tag namespace squatting (e.g. a `system/*` namespace reserved for internal use)
- No new API keys or external services required
- Type metadata schemas may contain PII in `person` entries (name, role, team) — acceptable for local single-user deployment, should be reviewed before multi-user deployment

## Success Metrics

- All existing tests continue to pass with zero regressions
- New test coverage for tag validation, prefix querying, type schemas, and metadata validation achieves 80%+ coverage on new code
- `distillery_tag_tree` returns a correct tree for a test dataset with 10+ hierarchical tags
- `distillery_type_schemas` returns all four new type schemas with correct required/optional fields

## Open Questions

No open questions at this time.
