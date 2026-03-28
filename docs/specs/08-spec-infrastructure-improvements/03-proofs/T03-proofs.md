# T03 Proof Summary: Config & Skill Integration

## Task

Add `TagsConfig` to `distillery.yaml` config (enforce_namespaces, reserved_prefixes), wire
reserved prefix enforcement into the `distillery_store` MCP tool, update `/distill` and
`/bookmark` skill SKILL.md files to suggest hierarchical tags, update `distillery.yaml.example`.

## Proof Artifacts

| File | Type | Status | Description |
|------|------|--------|-------------|
| T03-01-test.txt | test | PASS | All 48 tests in `tests/test_config.py` pass, including 9 new `TestTagsConfig` tests |
| T03-02-cli.txt | cli | PASS | Reserved prefix enforcement in `_handle_store` verified: rejects unauthorized sources, allows `distillery-core` |

## Summary of Changes

### `src/distillery/config.py`
- Added `TagsConfig` dataclass with `enforce_namespaces: bool` (default `False`) and `reserved_prefixes: list[str]` (default `[]`)
- Added `_parse_tags(raw)` function for YAML section parsing
- Added `tags: TagsConfig` field to `DistilleryConfig`
- Added `reserved_prefixes` validation in `_validate()`: each prefix must match `[a-z0-9][a-z0-9-]*`
- Updated `load_config()` to parse `tags` section from YAML

### `src/distillery/mcp/server.py`
- Added reserved prefix enforcement block in `_handle_store()`: tags using a reserved prefix are rejected with `RESERVED_PREFIX` error code unless the entry source is `distillery-core`
- Added `entry_source_str` resolution from `arguments.get("source", EntrySource.CLAUDE_CODE)`

### `.claude/skills/distill/SKILL.md`
- Updated Step 7 (Extract Tags) to suggest hierarchical tags: `project/{repo-name}/sessions`, `project/{repo-name}/decisions`, `project/{repo-name}/architecture`, `domain/{topic}`

### `.claude/skills/bookmark/SKILL.md`
- Updated Step 8 (Extract Tags) to suggest hierarchical tags: `source/bookmark/{domain}` (domain derived from URL with dots replaced by hyphens), `domain/{topic}`, `project/{repo-name}/references`

### `distillery.yaml.example`
- Added `tags` section documenting `enforce_namespaces` and `reserved_prefixes` with explanatory comments

### `tests/test_config.py`
- Added `TagsConfig` import
- Added `TestExampleConfigFile::test_example_config_tags_section` verifying example file has `tags` section
- Added `TestTagsConfig` class (9 tests) covering: defaults, parsing, enforcement, validation errors

## Verification

Full test suite: 613 passed
Config tests: 48 passed (includes 9 new tags tests)
Ruff: 0 errors
