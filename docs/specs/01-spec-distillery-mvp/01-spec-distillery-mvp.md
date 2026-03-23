# 01-spec-distillery-mvp: Storage Layer & Data Model

## Introduction/Overview

Distillery's storage layer is the foundation for a team-accessible knowledge base accessed through Claude Code skills. This spec defines the data model, storage abstraction protocol, DuckDB backend implementation, configurable embedding provider, and MCP server that exposes storage operations as tools. All upstream skills (`/distill`, `/recall`, `/pour`, etc.) depend on this layer.

## Goals

1. Define a stable `Entry` data model with structured metadata that supports all planned entry types (session, bookmark, minutes, reference, idea, inbox)
2. Implement a `DistilleryStore` protocol that abstracts storage operations, enabling future migration from DuckDB to Elasticsearch without rewriting skills
3. Build a working DuckDB backend with vector similarity search (HNSW), metadata filtering, and basic aggregation
4. Ship a configurable embedding provider interface with a Jina v3 default adapter
5. Expose all storage operations through an MCP server that Claude Code skills can connect to

## User Stories

- As a Claude Code skill developer, I want a stable storage API so that I can build `/distill` and `/recall` without coupling to a specific database
- As a team member, I want my knowledge entries to have consistent metadata (author, project, tags, timestamps) so that retrieval is precise
- As an operator, I want to swap embedding models without changing storage code so that I can optimize cost/quality over time
- As a Claude Code user, I want the storage layer available as an MCP server so that skills can call `store`, `search`, and `get` as standard tools

## Demoable Units of Work

### Unit 1: Project Scaffolding & Entry Data Model

**Purpose:** Establish the Python project structure, configuration system, and the canonical `Entry` dataclass that all components share.

**Functional Requirements:**
- The system shall use a Python project with `pyproject.toml` (PEP 621), supporting Python 3.11+
- The system shall define an `Entry` dataclass with these required fields:
  - `id` (UUID, auto-generated)
  - `content` (str, the knowledge text)
  - `entry_type` (enum: `session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`)
  - `source` (str: `claude-code`, `manual`, `import`)
  - `author` (str)
  - `project` (str, optional)
  - `tags` (list[str], default empty)
  - `status` (enum: `active`, `pending_review`, `archived`)
  - `created_at` (datetime, auto-generated)
  - `updated_at` (datetime, auto-generated)
  - `version` (int, default 1, incremented on update)
- The system shall define type-specific optional fields as a `metadata` dict:
  - Session entries: `session_id`, `session_type` (work/cowork)
  - Bookmark entries: `url`, `summary`
  - Minutes entries: `meeting_id`
- The system shall load configuration from a YAML file (`distillery.yaml`) with settings for:
  - `storage.backend` (str: `duckdb`)
  - `storage.database_path` (str, default `~/.distillery/distillery.db`)
  - `embedding.provider` (str: `jina`, `openai`, or custom)
  - `embedding.model` (str, default `jina-embeddings-v3`)
  - `embedding.dimensions` (int, default `1024`)
  - `embedding.api_key_env` (str, name of environment variable holding the API key)
  - `team.name` (str)
  - `classification.confidence_threshold` (float, default `0.6`)
- The system shall validate configuration on load and raise clear errors for missing required fields

**Proof Artifacts:**
- Test: `tests/test_entry.py` passes — demonstrates Entry creation, serialization, validation, and type-specific metadata
- Test: `tests/test_config.py` passes — demonstrates YAML config loading, defaults, and validation errors
- File: `pyproject.toml` contains project metadata, dependencies, and entry points

### Unit 2: DistilleryStore Protocol & DuckDB Backend

**Purpose:** Define the storage abstraction protocol and implement the DuckDB backend with table schema, CRUD operations, and vector storage.

**Functional Requirements:**
- The system shall define a `DistilleryStore` protocol (Python `Protocol` class) with these async methods:
  - `store(entry: Entry) -> str` — store entry, return ID
  - `get(entry_id: str) -> Entry | None` — retrieve by ID
  - `update(entry_id: str, updates: dict) -> Entry` — partial update, increment version, update `updated_at`
  - `delete(entry_id: str) -> bool` — soft delete (set status to `archived`)
  - `search(query: str, filters: dict | None, limit: int) -> list[SearchResult]` — semantic search with optional metadata filters
  - `find_similar(content: str, threshold: float, limit: int) -> list[SearchResult]` — find entries above similarity threshold (for deduplication)
  - `list_entries(filters: dict | None, limit: int, offset: int) -> list[Entry]` — list with metadata filtering and pagination
- The system shall define `SearchResult` as a dataclass containing `entry: Entry` and `score: float`
- The system shall implement `DuckDBStore` satisfying the `DistilleryStore` protocol
- The `DuckDBStore` shall create a DuckDB database file at the configured path on first use
- The `DuckDBStore` shall create an `entries` table with columns matching all `Entry` fields, plus an `embedding` column of type `FLOAT[{dimensions}]`
- The `DuckDBStore` shall install and load the `vss` extension and create an HNSW index on the `embedding` column with `metric = 'cosine'`
- The `DuckDBStore` shall enable experimental HNSW persistence (`SET hnsw_enable_experimental_persistence = true`)
- The `search` method shall accept filters on: `entry_type`, `author`, `project`, `tags` (contains any), `status`, and date ranges on `created_at`
- The `search` method shall combine vector similarity with metadata filters in a single query
- The `find_similar` method shall return entries whose cosine similarity to the provided content exceeds the threshold, sorted by descending similarity
- The `update` method shall reject updates to `id`, `created_at`, and `source` fields
- The `list_entries` method shall support the same filters as `search` but without semantic ranking

**Proof Artifacts:**
- Test: `tests/test_store_protocol.py` passes — demonstrates protocol compliance via duck typing
- Test: `tests/test_duckdb_store.py` passes — demonstrates store, get, update, delete, search, find_similar, and list_entries against a real DuckDB instance (in-memory for tests)
- CLI: `python -m distillery.store --check` returns connection status and entry count

### Unit 3: Configurable Embedding Provider

**Purpose:** Abstract embedding generation behind a provider interface, ship Jina v3 and OpenAI adapters, and integrate with the storage layer.

**Functional Requirements:**
- The system shall define an `EmbeddingProvider` protocol with:
  - `embed(text: str) -> list[float]` — embed a single text
  - `embed_batch(texts: list[str]) -> list[list[float]]` — embed multiple texts efficiently
  - `dimensions` property returning the vector dimensionality
  - `model_name` property returning the model identifier
- The system shall implement `JinaEmbeddingProvider` using the Jina AI API:
  - Model: `jina-embeddings-v3` (default)
  - Dimensions: 1024 (default, configurable via Matryoshka truncation)
  - API key sourced from environment variable specified in config
  - Task type: `retrieval.passage` for storage, `retrieval.query` for search
- The system shall implement `OpenAIEmbeddingProvider` using the OpenAI API:
  - Model: `text-embedding-3-small` (default)
  - Dimensions: 512 (default)
  - API key sourced from environment variable specified in config
- The system shall select the provider based on `embedding.provider` in config
- The `DuckDBStore` shall use the configured `EmbeddingProvider` to generate embeddings on `store()` and on `search()`/`find_similar()`
- The system shall store the embedding model name and dimensions in a `_meta` table in DuckDB, and raise an error on startup if the configured model differs from what was used to populate the database (preventing mixed-model embeddings)
- The `embed_batch` method shall handle rate limiting with exponential backoff (max 3 retries)

**Proof Artifacts:**
- Test: `tests/test_embedding.py` passes — demonstrates provider interface compliance, model name/dimensions properties, and error handling (uses mocked HTTP responses)
- Test: `tests/test_store_integration.py` passes — demonstrates end-to-end store → search flow with a mock embedding provider returning deterministic vectors
- File: `distillery.yaml.example` contains documented configuration for both Jina and OpenAI providers

### Unit 4: MCP Server

**Purpose:** Expose storage operations as an MCP server so Claude Code skills can connect and call `store`, `search`, `get`, `update`, and `find_similar` as tools.

**Functional Requirements:**
- The system shall implement an MCP server using the `mcp` Python SDK (stdio transport)
- The server shall expose these tools:
  - `distillery_store` — accepts entry fields (content, entry_type, author, project, tags, metadata), stores in DB, returns entry ID and any dedup warnings
  - `distillery_search` — accepts query string, optional filters (entry_type, author, project, tags, status, date_from, date_to), optional limit (default 10), returns list of entries with similarity scores
  - `distillery_get` — accepts entry_id, returns full entry or error
  - `distillery_update` — accepts entry_id and fields to update, returns updated entry
  - `distillery_find_similar` — accepts content string and threshold (default 0.8), returns similar entries with scores (used by skills for deduplication checks)
  - `distillery_list` — accepts optional filters, limit, offset, returns entries without semantic ranking
  - `distillery_status` — returns DB stats: total entries, entries by type, entries by status, database size, embedding model in use
- Each tool shall validate inputs and return structured error messages for invalid requests
- The server shall initialize `DuckDBStore` and `EmbeddingProvider` from `distillery.yaml` on startup
- The server shall be launchable via `python -m distillery.mcp` or `distillery-mcp` entry point
- The system shall include a Claude Code MCP configuration snippet for `settings.json`:
  ```json
  {
    "mcpServers": {
      "distillery": {
        "command": "python",
        "args": ["-m", "distillery.mcp"],
        "env": { "JINA_API_KEY": "..." }
      }
    }
  }
  ```

**Proof Artifacts:**
- Test: `tests/test_mcp_server.py` passes — demonstrates all 7 tools via MCP client test harness (store → search → get → update → find_similar → list → status)
- CLI: `python -m distillery.mcp` starts server, `distillery_status` tool returns valid stats
- File: `docs/mcp-setup.md` contains setup instructions for connecting Claude Code to the Distillery MCP server

## Non-Goals (Out of Scope)

- **Skills implementation** — `/distill`, `/recall`, `/pour`, etc. are covered in spec 02
- **Classification pipeline** — confidence scoring, type inference, and review queue are covered in spec 03
- **Semantic deduplication logic** — the `find_similar` method provides the primitive; dedup decision logic (skip/merge/create thresholds) belongs in the classification spec
- **Elasticsearch backend** — Phase 2; the `DistilleryStore` protocol is designed to support it but implementation is deferred
- **Private entries / access control** — MVP is team-only; access control is deferred
- **Ambient feed intelligence** — Phase 3
- **Web UI or REST API** — all access is via MCP server + Claude Code skills
- **Authentication** — the MCP server runs locally; no auth needed for MVP

## Design Considerations

No GUI. All interaction through Claude Code skills connecting to the MCP server. The MCP server is the sole runtime interface to the storage layer.

## Repository Standards

- **Language:** Python 3.11+
- **Package manager:** `uv` (if available) or `pip`
- **Project config:** `pyproject.toml` (PEP 621)
- **Type checking:** `mypy` strict mode
- **Linting:** `ruff`
- **Testing:** `pytest` with `pytest-asyncio`
- **Code style:** Type hints on all public functions, docstrings on all public classes and methods
- **Directory structure:**
  ```
  distillery/
  ├── pyproject.toml
  ├── distillery.yaml.example
  ├── src/
  │   └── distillery/
  │       ├── __init__.py
  │       ├── config.py          # YAML config loading
  │       ├── models.py          # Entry, SearchResult, enums
  │       ├── store/
  │       │   ├── __init__.py
  │       │   ├── protocol.py    # DistilleryStore protocol
  │       │   └── duckdb.py      # DuckDB implementation
  │       ├── embedding/
  │       │   ├── __init__.py
  │       │   ├── protocol.py    # EmbeddingProvider protocol
  │       │   ├── jina.py        # Jina adapter
  │       │   └── openai.py      # OpenAI adapter
  │       └── mcp/
  │           ├── __init__.py
  │           └── server.py      # MCP server
  ├── tests/
  │   ├── test_entry.py
  │   ├── test_config.py
  │   ├── test_store_protocol.py
  │   ├── test_duckdb_store.py
  │   ├── test_embedding.py
  │   ├── test_store_integration.py
  │   └── test_mcp_server.py
  └── docs/
      ├── mcp-setup.md
      └── specs/
          └── 01-spec-distillery-mvp/
  ```

## Technical Considerations

- **DuckDB VSS is experimental.** HNSW persistence requires `hnsw_enable_experimental_persistence = true`. WAL recovery is not reliable. Acceptable for prototype; data should be backed up regularly. The abstraction layer ensures migration to ES is a backend swap.
- **Embedding model lock.** The `_meta` table prevents mixing embeddings from different models in the same database. To change models, re-embed the entire corpus (a migration script should be provided but is out of scope for this spec).
- **Async design.** The `DistilleryStore` protocol is async. DuckDB is synchronous; the `DuckDBStore` wraps calls in `asyncio.to_thread()` to avoid blocking the MCP server event loop.
- **Vector dimensions.** Jina v3 supports Matryoshka dimension reduction. Default 1024; can be reduced to 512 or 256 at config time for faster search at slight accuracy cost.
- **MCP transport.** Stdio transport for local use. If team access is needed before ES migration, the MCP server could be wrapped in SSE transport, but that is out of scope.
- **Filters on search.** DuckDB does not support native hybrid search (BM25 + vector). For MVP, `search()` performs vector similarity then applies metadata filters as post-processing. This is acceptable at small scale (<10K entries). The ES backend will use native hybrid search.
- **Tags filtering.** Tags are stored as a JSON array in DuckDB. Filter "contains any" uses `list_has_any()` or equivalent DuckDB function.
- **Entry versioning.** The `version` field increments on every `update()` call. Full version history (storing previous versions) is deferred — only the current version is stored.

## Security Considerations

- **API keys** for embedding providers are sourced from environment variables, never stored in config files or the database
- **distillery.yaml.example** must not contain real API keys
- **The MCP server runs locally** (stdio transport) with no network exposure. No authentication required for MVP.
- **Database file permissions** should be set to user-only (`0600`) on creation
- **No PII handling** — Distillery stores team knowledge, not personal data. No special PII protections for MVP.

## Success Metrics

- All 7 test files pass with `pytest`
- `mypy --strict` passes on all source files
- `ruff check` passes with zero errors
- MCP server starts and all 7 tools respond correctly
- Store → search round-trip returns the stored entry with score > 0.9 (using identical query text)
- `find_similar` correctly identifies duplicate content (score > 0.95) and distinguishes unrelated content (score < 0.3)
- DuckDB database file is created at configured path and persists across server restarts

## Open Questions

1. **DuckDB concurrency** — If multiple Claude Code sessions connect to the same MCP server simultaneously, DuckDB's single-writer limitation may cause contention. For MVP with a single user this is not a problem, but should be monitored. The ES migration in Phase 2 resolves this.
2. **Embedding cost** — At 1024 dimensions and typical session summaries (~500 tokens), Jina v3 costs are negligible for MVP scale. Monitor if batch operations (future `/process` skill) create cost spikes.
3. **HNSW index rebuild** — After significant deletes (soft-delete marks), the HNSW index may degrade. A periodic `PRAGMA hnsw_compact_index` or index rebuild may be needed. Monitor search quality over time.
