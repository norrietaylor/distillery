"""Elasticsearch storage backend for Distillery.

Implements the ``DistilleryStore`` protocol using Elasticsearch 9.x with
the ``AsyncElasticsearch`` client. Uses BBQ HNSW vector indexing for
dense_vector fields with cosine similarity.

This module provides:
  - Connection management via ``AsyncElasticsearch``
  - Versioned index creation with aliases
  - BBQ HNSW mappings for embedding fields
  - Async CRUD operations (store, get, update, delete)

Search, find_similar, list_entries, and logging operations are added by T02/T03.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from distillery.models import Entry, EntryStatus, validate_metadata

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch

    from distillery.embedding.protocol import EmbeddingProvider
    from distillery.store.protocol import SearchResult

logger = logging.getLogger(__name__)

# Immutable fields that callers may never overwrite via update().
_IMMUTABLE_FIELDS = frozenset({"id", "created_at", "source"})


def _entry_to_doc(entry: Entry, embedding: list[float]) -> dict[str, Any]:
    """Convert an Entry and its embedding into an Elasticsearch document.

    Args:
        entry: The entry to serialise.
        embedding: The pre-computed embedding vector.

    Returns:
        A dict suitable for indexing into Elasticsearch.
    """
    return {
        "content": entry.content,
        "entry_type": entry.entry_type.value,
        "source": entry.source.value,
        "author": entry.author,
        "project": entry.project,
        "tags": list(entry.tags),
        "status": entry.status.value,
        "metadata": json.dumps(entry.metadata),
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
        "version": entry.version,
        "embedding": embedding,
        "accessed_at": entry.accessed_at.isoformat() if entry.accessed_at else None,
    }


def _doc_to_entry(doc_id: str, source: dict[str, Any]) -> Entry:
    """Reconstruct an Entry from an Elasticsearch document.

    Args:
        doc_id: The document ``_id``.
        source: The ``_source`` dict from the ES response.

    Returns:
        A fully populated ``Entry`` instance.
    """
    metadata_raw = source.get("metadata", "{}")
    if isinstance(metadata_raw, str):
        metadata: dict[str, Any] = json.loads(metadata_raw)
    else:
        metadata = dict(metadata_raw) if metadata_raw else {}

    accessed_at_raw = source.get("accessed_at")
    accessed_at: datetime | None = None
    if accessed_at_raw is not None:
        accessed_at = datetime.fromisoformat(accessed_at_raw)
        if accessed_at.tzinfo is None:
            accessed_at = accessed_at.replace(tzinfo=UTC)

    created_at = datetime.fromisoformat(source["created_at"])
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    updated_at = datetime.fromisoformat(source["updated_at"])
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)

    return Entry(
        id=doc_id,
        content=source["content"],
        entry_type=source["entry_type"],
        source=source["source"],
        author=source["author"],
        project=source.get("project"),
        tags=list(source.get("tags", [])),
        status=source.get("status", "active"),
        metadata=metadata,
        created_at=created_at,
        updated_at=updated_at,
        version=int(source.get("version", 1)),
        accessed_at=accessed_at,
    )


class ElasticsearchStore:
    """Elasticsearch-backed implementation of the ``DistilleryStore`` protocol.

    Manages versioned indices with aliases and BBQ HNSW vector mappings.
    All public methods are ``async``.

    Parameters
    ----------
    client:
        An ``AsyncElasticsearch`` instance for communicating with the cluster.
    embedding_provider:
        An object satisfying the ``EmbeddingProvider`` protocol.  Its
        ``dimensions`` property determines the vector field width.
    index_prefix:
        Prefix for all Elasticsearch index names.  Defaults to ``"distillery"``.
    embedding_mode:
        One of ``"client"``, ``"server"``, or ``"auto"``.  Defaults to
        ``"client"``.
    """

    # Index name suffixes and their versioned counterparts.
    _INDEX_DEFS: list[tuple[str, str]] = [
        ("entries", "entries_v1"),
        ("search_log", "search_log_v1"),
        ("feedback_log", "feedback_log_v1"),
    ]

    def __init__(
        self,
        client: AsyncElasticsearch,
        embedding_provider: EmbeddingProvider,
        index_prefix: str = "distillery",
        embedding_mode: str = "client",
    ) -> None:
        self._client = client
        self._embedding_provider = embedding_provider
        self._index_prefix = index_prefix
        self._embedding_mode = embedding_mode
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Index name helpers
    # ------------------------------------------------------------------

    def _alias_name(self, suffix: str) -> str:
        """Return the alias name for an index suffix (e.g. ``distillery_entries``)."""
        return f"{self._index_prefix}_{suffix}"

    def _versioned_name(self, versioned_suffix: str) -> str:
        """Return the versioned index name (e.g. ``distillery_entries_v1``)."""
        return f"{self._index_prefix}_{versioned_suffix}"

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    def _entries_mappings(self) -> dict[str, Any]:
        """Return the index mappings for the entries index."""
        return {
            "properties": {
                "content": {"type": "text"},
                "entry_type": {"type": "keyword"},
                "source": {"type": "keyword"},
                "author": {"type": "keyword"},
                "project": {"type": "keyword"},
                "tags": {"type": "keyword"},
                "status": {"type": "keyword"},
                "metadata": {"type": "text", "index": False},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "version": {"type": "integer"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": self._embedding_provider.dimensions,
                    "index": True,
                    "similarity": "cosine",
                    "index_options": {
                        "type": "bbq_hnsw",
                        "m": 16,
                        "ef_construction": 100,
                    },
                },
                "accessed_at": {"type": "date"},
            }
        }

    def _search_log_mappings(self) -> dict[str, Any]:
        """Return the index mappings for the search_log index."""
        return {
            "properties": {
                "query": {"type": "text"},
                "result_entry_ids": {"type": "keyword"},
                "result_scores": {"type": "float"},
                "timestamp": {"type": "date"},
                "session_id": {"type": "keyword"},
            }
        }

    def _feedback_log_mappings(self) -> dict[str, Any]:
        """Return the index mappings for the feedback_log index."""
        return {
            "properties": {
                "search_id": {"type": "keyword"},
                "entry_id": {"type": "keyword"},
                "signal": {"type": "keyword"},
                "timestamp": {"type": "date"},
            }
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create versioned indices with aliases if they do not already exist.

        This must be called once before any other method.  Subsequent calls
        are no-ops.
        """
        if self._initialized:
            return

        mappings_map: dict[str, dict[str, Any]] = {
            "entries_v1": self._entries_mappings(),
            "search_log_v1": self._search_log_mappings(),
            "feedback_log_v1": self._feedback_log_mappings(),
        }

        for alias_suffix, versioned_suffix in self._INDEX_DEFS:
            index_name = self._versioned_name(versioned_suffix)
            alias_name = self._alias_name(alias_suffix)

            exists = await self._client.indices.exists(index=index_name)
            if not exists:
                body: dict[str, Any] = {
                    "aliases": {alias_name: {}},
                }
                mappings = mappings_map.get(versioned_suffix)
                if mappings:
                    body["mappings"] = mappings

                await self._client.indices.create(index=index_name, body=body)
                logger.info(
                    "Created index %s with alias %s",
                    index_name,
                    alias_name,
                )
            else:
                logger.debug("Index %s already exists, skipping creation", index_name)

        self._initialized = True
        logger.info(
            "ElasticsearchStore initialized (prefix=%s, embedding_mode=%s)",
            self._index_prefix,
            self._embedding_mode,
        )

    async def close(self) -> None:
        """Close the underlying async ES client."""
        await self._client.close()
        self._initialized = False
        logger.info("ElasticsearchStore connection closed")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def client(self) -> AsyncElasticsearch:
        """Return the underlying ``AsyncElasticsearch`` client."""
        return self._client

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        """Return the configured embedding provider."""
        return self._embedding_provider

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    async def store(self, entry: Entry) -> str:
        """Persist a new entry and return its ID.

        Embeds the entry content via the configured embedding provider,
        then indexes the document into Elasticsearch.

        Returns:
            The UUID string of the stored entry.
        """
        validate_metadata(entry.entry_type.value, entry.metadata)
        embedding = self._embedding_provider.embed(entry.content)
        doc = _entry_to_doc(entry, embedding)

        await self._client.index(
            index=self._alias_name("entries"),
            id=entry.id,
            document=doc,
            refresh="wait_for",
        )
        logger.debug("Stored entry id=%s", entry.id)
        return entry.id

    async def get(self, entry_id: str) -> Entry | None:
        """Retrieve an entry by its ID.

        Returns ``None`` for missing entries or entries with status ``archived``.
        """
        try:
            resp = await self._client.get(
                index=self._alias_name("entries"),
                id=entry_id,
            )
        except Exception:
            # NotFoundError or other transport errors.
            return None

        source: dict[str, Any] = resp["_source"]
        if source.get("status") == EntryStatus.ARCHIVED.value:
            return None

        entry = _doc_to_entry(entry_id, source)

        # Fire-and-forget: update accessed_at.
        try:
            await self._client.update(
                index=self._alias_name("entries"),
                id=entry_id,
                doc={"accessed_at": datetime.now(tz=UTC).isoformat()},
            )
        except Exception:
            logger.debug("accessed_at update failed for id=%s (ignored)", entry_id)

        return entry

    async def update(self, entry_id: str, updates: dict[str, Any]) -> Entry:
        """Apply a partial update to an existing entry.

        Increments ``version`` by 1 and refreshes ``updated_at``.  Rejects
        changes to immutable fields (``id``, ``created_at``, ``source``).
        Re-embeds when ``content`` changes.

        Raises:
            ValueError: If ``updates`` contains any immutable field.
            KeyError: If no entry with ``entry_id`` exists.

        Returns:
            The updated ``Entry``.
        """
        bad_keys = _IMMUTABLE_FIELDS & updates.keys()
        if bad_keys:
            raise ValueError(
                f"Cannot update immutable field(s): {', '.join(sorted(bad_keys))}"
            )

        # Fetch existing document.
        try:
            resp = await self._client.get(
                index=self._alias_name("entries"),
                id=entry_id,
            )
        except Exception as exc:
            raise KeyError(f"No entry found with id={entry_id!r}") from exc

        existing_source: dict[str, Any] = resp["_source"]

        # Validate metadata if metadata or entry_type is changing.
        if "metadata" in updates or "entry_type" in updates:
            existing_metadata_raw = existing_source.get("metadata", "{}")
            if isinstance(existing_metadata_raw, str):
                existing_metadata: dict[str, Any] = json.loads(existing_metadata_raw)
            else:
                existing_metadata = dict(existing_metadata_raw) if existing_metadata_raw else {}

            raw_type: Any = updates.get("entry_type", existing_source.get("entry_type", ""))
            effective_type: str = (
                raw_type.value if hasattr(raw_type, "value") else str(raw_type)
            )
            effective_metadata = updates.get("metadata", existing_metadata)
            validate_metadata(effective_type, effective_metadata)

        now = datetime.now(tz=UTC)

        # Build the partial document for the ES update.
        doc: dict[str, Any] = {}
        for key, value in updates.items():
            if hasattr(value, "value"):
                doc[key] = value.value
            elif key == "metadata" and isinstance(value, dict):
                doc[key] = json.dumps(value)
            elif key == "tags" and isinstance(value, list):
                doc[key] = list(value)
            else:
                doc[key] = value

        # Re-embed when content changes.
        if "content" in updates:
            new_embedding = self._embedding_provider.embed(updates["content"])
            doc["embedding"] = new_embedding

        # Always increment version and refresh timestamps.
        current_version = int(existing_source.get("version", 1))
        doc["version"] = current_version + 1
        doc["updated_at"] = now.isoformat()
        doc["accessed_at"] = now.isoformat()

        await self._client.update(
            index=self._alias_name("entries"),
            id=entry_id,
            doc=doc,
            refresh="wait_for",
        )
        logger.debug("Updated entry id=%s", entry_id)

        # Re-fetch to return the updated state.
        fetch_resp = await self._client.get(
            index=self._alias_name("entries"),
            id=entry_id,
        )
        return _doc_to_entry(entry_id, fetch_resp["_source"])

    async def delete(self, entry_id: str) -> bool:
        """Soft-delete an entry by setting its status to ``archived``.

        Returns:
            ``True`` if the entry was found and archived, ``False`` otherwise.
        """
        try:
            await self._client.update(
                index=self._alias_name("entries"),
                id=entry_id,
                doc={
                    "status": EntryStatus.ARCHIVED.value,
                    "updated_at": datetime.now(tz=UTC).isoformat(),
                },
                refresh="wait_for",
            )
            logger.debug("Soft-deleted (archived) entry id=%s", entry_id)
            return True
        except Exception:
            logger.debug("delete() called for non-existent entry id=%s", entry_id)
            return False

    # ------------------------------------------------------------------
    # Stub methods for protocol compliance (implemented in T02/T03)
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[SearchResult]:
        """Perform semantic search (implemented in T02)."""
        raise NotImplementedError("search() will be implemented in T02")

    async def find_similar(
        self,
        content: str,
        threshold: float,
        limit: int,
    ) -> list[SearchResult]:
        """Find similar entries (implemented in T02)."""
        raise NotImplementedError("find_similar() will be implemented in T02")

    async def list_entries(
        self,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
    ) -> list[Entry]:
        """List entries with filters (implemented in T02)."""
        raise NotImplementedError("list_entries() will be implemented in T02")

    async def log_search(
        self,
        query: str,
        result_entry_ids: list[str],
        result_scores: list[float],
        session_id: str | None = None,
    ) -> str:
        """Log a search event (implemented in T03)."""
        raise NotImplementedError("log_search() will be implemented in T03")

    async def log_feedback(
        self,
        search_id: str,
        entry_id: str,
        signal: str,
    ) -> str:
        """Log feedback (implemented in T03)."""
        raise NotImplementedError("log_feedback() will be implemented in T03")
