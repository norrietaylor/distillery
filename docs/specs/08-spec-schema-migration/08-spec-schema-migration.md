# 08-spec-schema-migration

## Introduction/Overview

Add DuckDB version pinning, a forward-only schema migration system, and `distillery export` / `distillery import` CLI commands to the Distillery store layer. This replaces the current ad-hoc `CREATE IF NOT EXISTS` / `ALTER IF NOT EXISTS` initialization with versioned, numbered migrations tracked in `_meta`, and provides first-class backup/restore for breaking schema changes.

## Goals

1. Pin DuckDB to `~=1.5.0` in `pyproject.toml` to prevent on-disk format breakage from minor version upgrades
2. Track `schema_version`, `duckdb_version`, and `vss_version` in the `_meta` table
3. Implement a forward-only migration system (`store/migrations.py`) with numbered, idempotent migration functions
4. Add `distillery export` and `distillery import` CLI commands for full knowledge base backup and restore
5. Document Fly.io deployment migration strategy in `deploy/fly/README.md`

## User Stories

- As an **operator**, I want DuckDB pinned to a compatible release so that pip upgrades don't silently corrupt my database.
- As a **developer**, I want numbered migrations so that schema changes are tracked, ordered, and testable.
- As a **user**, I want `distillery export` so that I can back up my knowledge base to a portable JSON file before risky operations.
- As a **Fly.io deployer**, I want documented migration steps so that I know how to safely upgrade the persistent volume database.

## Demoable Units of Work

### Unit 1: Version Pinning and `_meta` Version Tracking

**Purpose:** Pin DuckDB to a compatible release range and extend `_meta` to track schema version, DuckDB version, and VSS extension version at startup.

**Functional Requirements:**
- `pyproject.toml` shall change the DuckDB dependency from `>=0.8.0` to `~=1.5.0` (allows 1.5.x patches, blocks 1.6.0+).
- The `_meta` table shall store the following additional keys alongside existing `embedding_model` and `embedding_dimensions`:
  - `schema_version` — integer as string (e.g., `"3"`), representing the highest migration that has been applied
  - `duckdb_version` — the DuckDB library version at time of last startup (e.g., `"1.5.1"`)
  - `vss_version` — the VSS extension version loaded at startup (if available from the extension metadata)
- On startup, `_sync_initialize()` shall:
  1. Open the database and load the VSS extension (existing behavior)
  2. Read `schema_version` from `_meta` (default `0` if key doesn't exist or `_meta` table doesn't exist)
  3. Read the current DuckDB library version via `duckdb.__version__`
  4. Compare stored `duckdb_version` with current version; log a warning if major or minor version differs
  5. Update `duckdb_version` and `vss_version` in `_meta` to current values
- The startup log shall include: `Schema at version {N}, DuckDB {version}`.

**Proof Artifacts:**
- File: `pyproject.toml` contains `"duckdb~=1.5.0"`
- Test: `pytest tests/test_store_migration.py::test_meta_version_tracking` passes — verifies `schema_version`, `duckdb_version` are written to `_meta`
- CLI: `distillery status` displays schema version and DuckDB version

### Unit 2: Forward-Only Schema Migration System

**Purpose:** Replace the ad-hoc `CREATE IF NOT EXISTS` / `ALTER IF NOT EXISTS` initialization with a numbered migration system that runs pending migrations in order on startup.

**Functional Requirements:**
- The system shall include `src/distillery/store/migrations.py` with a `MIGRATIONS` dictionary mapping integer version numbers to migration functions:
  ```python
  MIGRATIONS: dict[int, Callable[[duckdb.DuckDBPyConnection], None]] = {
      1: _initial_schema,        # entries table, _meta table
      2: _add_accessed_at,       # ALTER TABLE entries ADD COLUMN accessed_at
      3: _add_ownership_columns, # created_by, last_modified_by columns
      4: _create_log_tables,     # search_log, feedback_log, audit_log
      5: _create_feed_sources,   # feed_sources table
      6: _create_hnsw_index,     # HNSW cosine similarity index
  }
  ```
- Migration functions 1–6 shall be extracted from the existing `_sync_initialize()` helper methods (`_create_schema`, `_add_accessed_at_column`, `_add_ownership_columns`, `_create_log_tables`, `_create_feed_sources_table`, `_create_index`). Each function shall be idempotent (safe to re-run using `IF NOT EXISTS` / `IF NOT EXISTS` guards).
- The startup flow in `_sync_initialize()` shall be refactored to:
  1. Ensure `_meta` table exists (bootstrap — this is migration 0)
  2. Read `schema_version` from `_meta` (default `0`)
  3. For each migration version > current, execute the migration function in order
  4. After all pending migrations complete, update `schema_version` in `_meta` to the highest applied version
  5. Validate embedding model/dimensions (existing logic, unchanged)
- Each migration shall run within a transaction. If a migration fails, the transaction is rolled back and startup raises a `RuntimeError` with the failing migration number and error message.
- The existing ad-hoc calls in `_sync_initialize()` shall be removed and replaced with a single call to `run_pending_migrations(conn)`.
- A `get_current_schema_version(conn)` function shall be exported for use by the CLI and tests.

**Proof Artifacts:**
- File: `src/distillery/store/migrations.py` exists with `MIGRATIONS` dict containing 6 entries
- Test: `pytest tests/test_store_migration.py::test_migration_from_zero` — fresh database reaches schema version 6
- Test: `pytest tests/test_store_migration.py::test_migration_idempotent` — running migrations twice produces same result
- Test: `pytest tests/test_store_migration.py::test_migration_partial` — database at version 3 runs only migrations 4, 5, 6
- CLI: `distillery status` shows `Schema version: 6`

### Unit 3: Export/Import CLI Commands

**Purpose:** Add `distillery export` and `distillery import` CLI commands for full knowledge base backup and restore, supporting both operational backup and breaking migration workflows.

**Functional Requirements:**
- `distillery export` shall:
  - Accept a required `--output` flag specifying the output file path (JSON format)
  - Export all entries from the `entries` table as a JSON array, with each entry serialized as: `{id, content, entry_type, source, status, tags, metadata, version, project, author, created_at, updated_at}`
  - Embeddings shall NOT be exported (they are re-computed on import from the content)
  - Export the `feed_sources` table as a separate JSON array in the output
  - Export `_meta` key-value pairs for provenance
  - The output JSON structure shall be: `{"version": 1, "exported_at": "<ISO timestamp>", "meta": {...}, "entries": [...], "feed_sources": [...]}`
  - Report: `Exported {N} entries and {M} feed sources to {path}`
- `distillery import` shall:
  - Accept a required `--input` flag specifying the input file path
  - Accept an optional `--mode` flag with values `"merge"` (default) or `"replace"`
    - `"merge"`: insert entries that don't exist (by ID), skip entries that already exist
    - `"replace"`: drop all existing entries, import all entries from the file, re-embed content
  - Re-compute embeddings for all imported entries using the configured embedding provider
  - Import feed sources (merge by URL, skip duplicates)
  - Report: `Imported {N} entries ({S} skipped, {E} re-embedded) and {M} feed sources`
- Both commands shall validate the JSON structure and report clear errors for malformed input.
- Both commands shall be registered as subcommands of the `distillery` CLI.

**Proof Artifacts:**
- CLI: `distillery export --output backup.json` creates a valid JSON file with entries and feed sources
- CLI: `distillery import --input backup.json --mode merge` imports entries, skipping duplicates
- CLI: `distillery export --output backup.json && distillery import --input backup.json --mode replace` round-trips successfully
- Test: `pytest tests/test_cli_export_import.py` passes with merge and replace mode tests

### Unit 4: Fly.io Migration Documentation

**Purpose:** Document the migration strategy for the Fly.io deployment where DuckDB runs on a persistent volume.

**Functional Requirements:**
- `deploy/fly/README.md` shall include a `## Database Migrations` section covering:
  - **Automatic migrations**: Additive migrations (new columns, new tables) run automatically on app startup — no operator action needed.
  - **Pre-deploy backup**: Before deploying a version with breaking schema changes, run `fly ssh console -C "distillery export --output /data/backup-$(date +%Y%m%d).json"` to back up.
  - **Volume snapshots**: Alternative backup via `fly volumes snapshots create <vol-id>` before risky deploys.
  - **Breaking migration procedure**: Export → deploy new version with `--mode replace` → verify → remove backup.
  - **Rollback**: Restore from volume snapshot or JSON backup using `distillery import --input backup.json --mode replace`.
- The documentation shall include example commands for each step.

**Proof Artifacts:**
- File: `deploy/fly/README.md` contains `## Database Migrations` section
- File: Section includes `distillery export` and `distillery import` example commands

## Non-Goals (Out of Scope)

- Down-migrations / rollback functions — backup-before-upgrade is the rollback strategy
- Automated blue-green deployment for Fly.io — operational, not code
- Embedding re-computation optimization (batch embedding on import uses existing `embed_batch`)
- Schema changes beyond documenting existing schema as migration 1–6 — no new schema changes in this spec
- MotherDuck / Prefect Horizon migration strategy — separate deployment, different constraints

## Design Considerations

No specific design requirements identified. CLI output follows existing patterns (`distillery status`, `distillery eval`).

## Repository Standards

- **Conventional Commits**: `feat(store):` for migrations, `feat(cli):` for export/import, `docs(deploy):` for Fly docs
- **mypy --strict** on `src/distillery/store/migrations.py`
- **pytest** markers: `@pytest.mark.unit` for migration logic, `@pytest.mark.integration` for CLI round-trips

## Technical Considerations

- **Migration extraction**: The 6 migration functions are already implemented as methods on `DuckDBStore`. Extracting them to module-level functions in `migrations.py` requires passing the `conn` object and removing `self` references. The embedding dimensions parameter for index creation comes from the config — pass it as an argument.
- **Idempotency**: All migrations use `IF NOT EXISTS` guards. Re-running a migration on an already-migrated database is a no-op.
- **Transaction safety**: DuckDB supports transactions. Each migration should `BEGIN` / `COMMIT` with `ROLLBACK` on exception. Note: DDL in DuckDB is transactional (unlike some databases).
- **Export size**: A knowledge base with 10,000 entries at ~1KB each is ~10MB JSON. Streaming JSON is unnecessary at this scale.
- **Import re-embedding**: `embed_batch` processes entries in batches. For large imports, this may take minutes depending on the embedding provider rate limits. Log progress per batch.
- **Concurrent startup**: The existing 3-attempt retry loop in `_sync_initialize()` handles write-write conflicts. Migrations should respect this — only one process runs migrations; others wait and verify.

## Security Considerations

- `distillery export` outputs all knowledge base content to a file. The file may contain sensitive information. Document that export files should be treated as sensitive data.
- `distillery import --mode replace` is destructive — it drops all existing entries. Add a confirmation prompt (or `--yes` flag to skip) before executing.
- Exported JSON files should not contain API keys or OAuth tokens — only entry content and metadata.

## Success Metrics

| Metric | Target |
|--------|--------|
| DuckDB version pin | `~=1.5.0` in pyproject.toml |
| `_meta` version keys | `schema_version`, `duckdb_version`, `vss_version` |
| Migration count | 6 (extracted from existing init code) |
| Export/import round-trip | 100% data fidelity (entries + feed sources) |
| Fly.io docs | Migration section in deploy/fly/README.md |

## Open Questions

No open questions at this time.
