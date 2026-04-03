"""In-process MCP bridge for eval: routes Claude tool_use calls to real handlers.

Creates a fresh in-memory DuckDB store, seeds it with scenario entries, then
exposes:

- ``get_tool_schemas()`` -- Anthropic-compatible tool definition list.
- ``call_tool(name, arguments)`` -- calls the actual ``_handle_*`` function and
  returns the parsed JSON response dict.
- ``count_stored_entries()`` -- returns the number of entries currently in the
  store (for effectiveness scoring).
- ``seed_file_store()`` -- seeds a file-backed DuckDB with entries for CLI eval.

This allows the eval runner to test the real tool implementations end-to-end
without starting a subprocess or stdio transport.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp import types as mcp_types

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
    TeamConfig,
)
from distillery.eval.models import SeedEntry
from distillery.mcp._stub_embedding import HashEmbeddingProvider
from distillery.mcp.server import (
    _handle_aggregate,
    _handle_classify,
    _handle_find_similar,
    _handle_get,
    _handle_interests,
    _handle_list,
    _handle_metrics,
    _handle_resolve_review,
    _handle_search,
    _handle_stale,
    _handle_store,
    _handle_tag_tree,
    _handle_type_schemas,
    _handle_update,
    _handle_watch,
    _handle_poll,
    _handle_rescore,
)
from distillery.store.duckdb import DuckDBStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Anthropic-compatible tool schemas for all 17 distillery MCP tools
# ---------------------------------------------------------------------------

DISTILLERY_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "distillery_store",
        "description": (
            "Store a new knowledge entry. Returns the created entry ID plus any "
            "deduplication warnings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Full text of the entry."},
                "entry_type": {
                    "type": "string",
                    "description": (
                        "One of: session, bookmark, minutes, meeting, "
                        "reference, idea, inbox, person, project, digest, github."
                    ),
                },
                "author": {"type": "string", "description": "Author identifier."},
                "project": {"type": "string", "description": "Optional project name."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of lowercase hyphenated tags.",
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional type-specific metadata.",
                },
                "dedup_threshold": {
                    "type": "number",
                    "description": "Similarity threshold for dedup warnings (default 0.8).",
                },
            },
            "required": ["content", "entry_type", "author"],
        },
    },
    {
        "name": "distillery_get",
        "description": "Retrieve a knowledge entry by its UUID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string", "description": "UUID of the entry."},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "distillery_update",
        "description": "Update an existing knowledge entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "content": {"type": "string"},
                "entry_type": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "description": "active, pending_review, or archived."},
                "metadata": {"type": "object"},
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "distillery_list",
        "description": "List entries without semantic ranking (newest first).",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_type": {"type": "string"},
                "author": {"type": "string"},
                "project": {"type": "string"},
                "status": {"type": "string"},
                "limit": {"type": "integer", "description": "Max results (default 10)."},
                "offset": {"type": "integer"},
                "output_mode": {
                    "type": "string",
                    "description": "Output mode: 'full' (default), 'summary' (no content), 'ids'.",
                },
                "content_max_length": {
                    "type": "integer",
                    "description": "Truncate content to this many characters (full mode only).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "distillery_aggregate",
        "description": "Count entries grouped by a field (e.g. entry_type, source, author).",
        "input_schema": {
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "description": (
                        "Field to group by. One of: entry_type, status, author, "
                        "project, source, metadata.source_url, metadata.source_type."
                    ),
                },
                "entry_type": {"type": "string"},
                "author": {"type": "string"},
                "project": {"type": "string"},
                "status": {"type": "string"},
                "date_from": {
                    "type": "string",
                    "description": "ISO 8601 start date (inclusive).",
                },
                "date_to": {
                    "type": "string",
                    "description": "ISO 8601 end date (inclusive).",
                },
                "tag_prefix": {
                    "type": "string",
                    "description": "Filter to entries under this tag namespace prefix.",
                },
                "limit": {"type": "integer", "description": "Max groups (default 50)."},
            },
            "required": ["group_by"],
        },
    },
    {
        "name": "distillery_search",
        "description": (
            "Semantic search over the knowledge base using natural language. "
            "Returns entries ranked by cosine similarity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query."},
                "limit": {"type": "integer", "description": "Max results (default 10)."},
                "entry_type": {"type": "string"},
                "author": {"type": "string"},
                "project": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "distillery_find_similar",
        "description": (
            "Find entries similar to the given content. Supports dedup_action=true "
            "for deduplication recommendations and conflict_check=true for conflict detection."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "threshold": {"type": "number", "description": "Similarity threshold (default 0.8)."},
                "dedup_action": {
                    "type": "boolean",
                    "description": "If true, add dedup action recommendation (create/skip/merge/link).",
                },
                "conflict_check": {
                    "type": "boolean",
                    "description": "If true, run conflict detection pass.",
                },
                "llm_responses": {
                    "type": "array",
                    "description": "LLM evaluations for conflict candidates (second pass).",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "distillery_classify",
        "description": "Persist a classification result onto an entry and update its status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "entry_type": {"type": "string"},
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"},
                "source_document": {"type": "string"},
            },
            "required": ["entry_id", "entry_type", "confidence", "reasoning"],
        },
    },
    {
        "name": "distillery_resolve_review",
        "description": "Approve, reclassify, or archive a pending-review entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string"},
                "action": {"type": "string", "description": "approve, reclassify, or archive."},
                "new_entry_type": {"type": "string"},
                "reviewer": {"type": "string"},
            },
            "required": ["entry_id", "action"],
        },
    },
    {
        "name": "distillery_metrics",
        "description": (
            "Retrieve aggregate metrics. scope='summary' gives entry counts and server info "
            "(replaces distillery_status). scope='search_quality' gives search quality metrics. "
            "scope='full' (default) gives complete metrics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "One of: 'summary', 'full', 'search_quality' (default: 'full').",
                },
                "period_days": {"type": "integer", "description": "Lookback window in days."},
            },
            "required": [],
        },
    },
    {
        "name": "distillery_stale",
        "description": "List entries that have not been accessed recently.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer"},
                "limit": {"type": "integer"},
                "entry_type": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "distillery_tag_tree",
        "description": "Return the hierarchical tag tree.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prefix": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "distillery_type_schemas",
        "description": "Return metadata schemas for all structured entry types.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "distillery_interests",
        "description": (
            "Build an interest profile from active entries. "
            "Set suggest_sources=true to also get feed source recommendations "
            "(replaces the former distillery_suggest_sources tool)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recency_days": {"type": "integer", "description": "Lookback window (default 90)."},
                "top_n": {"type": "integer", "description": "Max topics returned (default 20)."},
                "suggest_sources": {
                    "type": "boolean",
                    "description": "If true, include feed source suggestions.",
                },
                "max_suggestions": {
                    "type": "integer",
                    "description": "Max source suggestions (default 5).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "distillery_watch",
        "description": "Manage feed sources (add, remove, list).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "One of: list, add, remove."},
                "url": {"type": "string"},
                "source_type": {"type": "string"},
                "label": {"type": "string"},
                "poll_interval_minutes": {"type": "integer"},
            },
            "required": [],
        },
    },
    {
        "name": "distillery_poll",
        "description": "Trigger a feed poll for one or all registered sources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_url": {"type": "string", "description": "URL of source to poll; omit for all."},
            },
            "required": [],
        },
    },
    {
        "name": "distillery_rescore",
        "description": "Rescore feed entries using the current interest profile.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max entries to rescore (default 100)."},
            },
            "required": [],
        },
    },
]


def _make_test_config() -> DistilleryConfig:
    """Return a minimal DistilleryConfig suitable for in-memory eval testing."""
    return DistilleryConfig(
        storage=StorageConfig(backend="duckdb", database_path=":memory:"),
        embedding=EmbeddingConfig(provider="mock", model="mock-hash", dimensions=4),
        team=TeamConfig(),
        classification=ClassificationConfig(),
    )


class MCPBridge:
    """Routes Claude tool_use calls to real in-process _handle_* functions.

    Args:
        store: An initialised DuckDBStore (in-memory).
        config: DistilleryConfig for handlers that need it.
        embedding_provider: The embedding provider used by the store.
    """

    def __init__(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: Any,
    ) -> None:
        self._store = store
        self._config = config
        self._embedding_provider = embedding_provider

    @classmethod
    async def create(cls, seed_entries: list[SeedEntry] | None = None) -> MCPBridge:
        """Create and initialise a bridge with an optional set of seed entries.

        Args:
            seed_entries: Entries to store before eval scenarios run.

        Returns:
            Initialised :class:`MCPBridge` instance.
        """
        provider = HashEmbeddingProvider(dimensions=4)
        config = _make_test_config()
        store = DuckDBStore(db_path=":memory:", embedding_provider=provider)
        await store.initialize()

        bridge = cls(store=store, config=config, embedding_provider=provider)

        for seed in seed_entries or []:
            await bridge._seed_entry(seed)

        return bridge

    async def _seed_entry(self, seed: SeedEntry) -> None:
        """Insert a single seed entry into the store."""
        from distillery.models import Entry, EntrySource, EntryType

        entry = Entry(
            content=seed.content,
            entry_type=EntryType(seed.entry_type),
            source=EntrySource.MANUAL,
            author=seed.author,
            tags=seed.tags,
            project=seed.project,
            metadata=seed.metadata,
        )
        await self._store.store(entry)

    async def close(self) -> None:
        """Close the underlying DuckDB store."""
        await self._store.close()

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return the Anthropic-compatible tool schema list."""
        return DISTILLERY_TOOL_SCHEMAS

    async def count_stored_entries(self) -> int:
        """Return the current number of entries in the store."""
        results = await self._store.list_entries(filters=None, limit=2147483647, offset=0)
        return len(results)

    async def count_entries_since_seed(self, seed_count: int) -> int:
        """Return entries added after seeding (total minus seed_count)."""
        total = await self.count_stored_entries()
        return max(0, total - seed_count)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Route a tool call to the appropriate handler and return parsed JSON.

        Args:
            name: MCP tool name (e.g. ``"distillery_search"``).
            arguments: Arguments from Claude's tool_use block.

        Returns:
            Parsed JSON response dict from the handler.
        """
        content = await self._dispatch(name, arguments)
        if content and hasattr(content[0], "text"):
            try:
                result: dict[str, Any] = json.loads(content[0].text)
                return result
            except json.JSONDecodeError:
                return {"text": str(content[0].text)}
        return {"error": True, "message": f"Unknown tool: {name}"}

    async def _dispatch(self, name: str, args: dict[str, Any]) -> Any:
        """Route to the correct _handle_* function."""
        store = self._store
        config = self._config
        ep = self._embedding_provider

        if name == "distillery_store":
            return await _handle_store(store=store, arguments=args, cfg=config)
        if name == "distillery_get":
            return await _handle_get(store=store, arguments=args)
        if name == "distillery_update":
            return await _handle_update(store=store, arguments=args)
        if name == "distillery_list":
            return await _handle_list(store=store, arguments=args)
        if name == "distillery_aggregate":
            return await _handle_aggregate(store=store, arguments=args)
        if name == "distillery_search":
            return await _handle_search(store=store, arguments=args)
        if name == "distillery_find_similar":
            return await _handle_find_similar(store=store, arguments=args, cfg=config)
        if name == "distillery_classify":
            return await _handle_classify(store=store, config=config, arguments=args)
        if name == "distillery_resolve_review":
            return await _handle_resolve_review(store=store, arguments=args)
        if name == "distillery_metrics":
            return await _handle_metrics(
                store=store, config=config, embedding_provider=ep, arguments=args
            )
        if name == "distillery_stale":
            return await _handle_stale(store=store, config=config, arguments=args)
        if name == "distillery_tag_tree":
            return await _handle_tag_tree(store=store, arguments=args)
        if name == "distillery_type_schemas":
            return await _handle_type_schemas()
        if name == "distillery_interests":
            return await _handle_interests(store=store, config=config, arguments=args)
        if name == "distillery_watch":
            return await _handle_watch(store=store, arguments=args)
        if name == "distillery_poll":
            return await _handle_poll(store=store, config=config, arguments=args)
        if name == "distillery_rescore":
            return await _handle_rescore(store=store, config=config, arguments=args)

        logger.warning("Unknown tool requested: %s", name)
        return [
            mcp_types.TextContent(
                type="text",
                text=json.dumps({"error": True, "code": "UNKNOWN_TOOL", "message": f"No handler for {name}"}),
            )
        ]


async def seed_file_store(
    db_path: str,
    seed_entries: list[SeedEntry],
    dimensions: int = 4,
) -> int:
    """Create (or open) a file-backed DuckDB and seed it with entries.

    Used by :class:`ClaudeEvalRunner` to prepare a temporary DuckDB file that
    the MCP server subprocess will open.  Returns the number of entries
    successfully stored so the caller can compute ``entries_stored`` later.

    Args:
        db_path: Path to the DuckDB database file.
        seed_entries: Entries to pre-load.
        dimensions: Embedding vector dimensionality (default 4).

    Returns:
        Number of entries seeded.
    """
    from distillery.models import Entry, EntrySource, EntryType

    provider = HashEmbeddingProvider(dimensions=dimensions)
    store = DuckDBStore(db_path=db_path, embedding_provider=provider)
    await store.initialize()

    count = 0
    for seed in seed_entries:
        entry = Entry(
            content=seed.content,
            entry_type=EntryType(seed.entry_type),
            source=EntrySource.MANUAL,
            author=seed.author,
            tags=seed.tags,
            project=seed.project,
            metadata=seed.metadata,
        )
        await store.store(entry)
        count += 1

    await store.close()
    return count
