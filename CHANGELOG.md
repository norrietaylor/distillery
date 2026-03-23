# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [v0.1.0] - 2026-03-22

Initial public release of the Distillery MVP, covering three specification areas.

### Spec 01 — Storage Layer & Data Model

- `Entry` data model with UUID, content, embedding, tags, source, topic, category, timestamps,
  and review-queue fields
- `DistilleryStore` protocol defining the full CRUD + search + classification interface
- `DuckDBStore` backend implementing `DistilleryStore` with VSS extension for vector similarity
  search (cosine similarity)
- `EmbeddingProvider` protocol with `OpenAIEmbeddingProvider` and `JinaEmbeddingProvider`
  implementations (rate limiting, retry, task-type support)
- MCP server (`distillery-mcp`) exposing 7 tools over stdio: `distillery_store`,
  `distillery_recall`, `distillery_search_by_tag`, `distillery_get`, `distillery_update`,
  `distillery_delete`, `distillery_health`
- `DistilleryConfig` with YAML-based configuration, environment variable overrides, and
  embedding provider selection

### Spec 02 — Core Skills

- `/distill` skill — capture session knowledge with duplicate detection and tag suggestions
- `/recall` skill — semantic search with provenance and relevance filtering
- `/pour` skill — multi-pass retrieval and structured synthesis with citations
- `/bookmark` skill — store URLs with auto-generated summaries and tag inference
- `/minutes` skill — meeting notes capture with append-update and list modes
- Shared slash-command conventions: output format, error handling, dry-run support

### Spec 03 — Classification Pipeline

- `ClassificationEngine` for automatic topic and category assignment using configurable
  taxonomy
- `DeduplicationChecker` for semantic similarity detection with configurable thresholds
- 4 additional MCP tools (11 total): `distillery_classify`, `distillery_review_queue`,
  `distillery_resolve_review`, `distillery_check_dedup`
- `/classify` skill — classify entries by ID, process full inbox, and manage review queue
- Config extensions: deduplication thresholds, classification taxonomy, review-queue settings

[Unreleased]: https://github.com/norrietaylor/distillery/compare/v0.1.0...HEAD
[v0.1.0]: https://github.com/norrietaylor/distillery/releases/tag/v0.1.0
