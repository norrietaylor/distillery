"""Elasticsearch storage backend for Distillery.

Implements the ``DistilleryStore`` protocol using Elasticsearch 9.x with
the ``AsyncElasticsearch`` client. Uses BBQ HNSW vector indexing for
dense_vector fields with cosine similarity.

This module provides:
  - Connection management via ``AsyncElasticsearch``
  - Versioned index creation with aliases
  - BBQ HNSW mappings for embedding fields
  - Async CRUD operations (store, get, update, delete)
  - Semantic search via kNN with metadata filters
  - Similarity search with threshold enforcement
  - Paginated list_entries with bool query filters
  - Dual embedding: client-side (EmbeddingProvider), server-side (ES Inference),
    and auto-detection mode
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
        self._effective_mode: str = embedding_mode
        self._initialized: bool = False
        self._inference_endpoint_id: str | None = None

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
        """Return the index mappings for the entries index.

        When the effective embedding mode is ``"server"``, a ``semantic_text``
        field backed by an ES Inference endpoint is added alongside the
        ``dense_vector`` field for backward compatibility.
        """
        properties: dict[str, Any] = {
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

        # Add semantic_text field when server-side embedding is active.
        if self._effective_mode == "server" and self._inference_endpoint_id:
            properties["content_semantic"] = {
                "type": "semantic_text",
                "inference_id": self._inference_endpoint_id,
            }

        return {"properties": properties}

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

    async def _detect_inference_endpoint(self) -> str | None:
        """Detect whether an ES inference endpoint is available.

        Returns the first inference endpoint ID if one exists, ``None``
        otherwise.
        """
        try:
            resp = await self._client.inference.get(inference_id="_all")
            endpoints: list[Any] = resp.get("endpoints", resp.get("models", []))
            if endpoints and len(endpoints) > 0:
                first: dict[str, Any] = endpoints[0]
                endpoint_id: str = str(
                    first.get("inference_id", first.get("model_id", ""))
                )
                return endpoint_id if endpoint_id else None
        except Exception:
            logger.debug("Inference endpoint detection failed (falling back to client mode)")
        return None

    async def initialize(self) -> None:
        """Create versioned indices with aliases if they do not already exist.

        When ``embedding_mode`` is ``"auto"``, detects whether an ES inference
        endpoint is available and selects server or client mode accordingly.

        This must be called once before any other method.  Subsequent calls
        are no-ops.
        """
        if self._initialized:
            return

        # Resolve auto mode before creating indices.
        if self._embedding_mode == "auto":
            endpoint_id = await self._detect_inference_endpoint()
            if endpoint_id:
                self._effective_mode = "server"
                self._inference_endpoint_id = endpoint_id
                logger.info(
                    "Auto mode: detected inference endpoint %r, using server mode",
                    endpoint_id,
                )
            else:
                self._effective_mode = "client"
                logger.info("Auto mode: no inference endpoint found, using client mode")
        elif self._embedding_mode == "server":
            self._effective_mode = "server"
            # Try to detect the endpoint for semantic_text mapping.
            endpoint_id = await self._detect_inference_endpoint()
            if endpoint_id:
                self._inference_endpoint_id = endpoint_id

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

    @property
    def effective_embedding_mode(self) -> str:
        """Return the resolved embedding mode (after auto-detection)."""
        return self._effective_mode

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    async def store(self, entry: Entry) -> str:
        """Persist a new entry and return its ID.

        In client mode, embeds the entry content via the configured embedding
        provider and passes the vector to Elasticsearch.  In server mode,
        skips client-side embedding and relies on ES Inference to generate
        embeddings from the ``content_semantic`` field.

        Returns:
            The UUID string of the stored entry.
        """
        validate_metadata(entry.entry_type.value, entry.metadata)

        if self._effective_mode == "server":
            # Server mode: no client-side embedding; ES infers from content.
            embedding: list[float] = []
        else:
            embedding = self._embedding_provider.embed(entry.content)

        doc = _entry_to_doc(entry, embedding)

        # For server mode, populate the semantic_text source field.
        if self._effective_mode == "server":
            doc["content_semantic"] = entry.content

        await self._client.index(
            index=self._alias_name("entries"),
            id=entry.id,
            document=doc,
            refresh="wait_for",
        )
        logger.debug("Stored entry id=%s (mode=%s)", entry.id, self._effective_mode)
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
    # Filter helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filter_clauses(filters: dict[str, Any] | None) -> list[dict[str, Any]]:
        """Build a list of Elasticsearch filter clauses from metadata filters.

        Supports: ``entry_type``, ``author``, ``project``, ``tags`` (any-match),
        ``status``, ``date_from``, ``date_to``.

        Args:
            filters: Optional dict of filter keys to values.

        Returns:
            A list of ES query DSL filter clause dicts suitable for use in a
            ``bool.filter`` or kNN ``filter`` array.
        """
        if not filters:
            return []

        clauses: list[dict[str, Any]] = []

        for key in ("entry_type", "author", "project", "status"):
            value = filters.get(key)
            if value is not None:
                clauses.append({"term": {key: value}})

        tags = filters.get("tags")
        if tags is not None:
            clauses.append({"terms": {"tags": tags}})

        date_from = filters.get("date_from")
        date_to = filters.get("date_to")
        if date_from is not None or date_to is not None:
            range_clause: dict[str, Any] = {}
            if date_from is not None:
                range_clause["gte"] = str(date_from)
            if date_to is not None:
                range_clause["lte"] = str(date_to)
            clauses.append({"range": {"created_at": range_clause}})

        return clauses

    @staticmethod
    def _convert_es_score(es_score: float) -> float:
        """Convert an Elasticsearch cosine similarity score to [0.0, 1.0].

        ES stores cosine similarity as ``(1 + cosine) / 2``, mapping the
        ``[-1, 1]`` cosine range to ``[0, 1]``.  We invert this to recover
        the raw cosine value: ``cosine = 2 * es_score - 1``.

        The returned value is clamped to ``[0.0, 1.0]``.

        Args:
            es_score: The ``_score`` from an ES kNN search using cosine
                similarity.

        Returns:
            The cosine similarity in ``[0.0, 1.0]``.
        """
        cosine = 2.0 * es_score - 1.0
        return max(0.0, min(1.0, cosine))

    # ------------------------------------------------------------------
    # Search operations
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[SearchResult]:
        """Perform semantic search with optional metadata filters.

        In client mode, embeds the query via the ``EmbeddingProvider`` and
        issues a kNN search with ``query_vector``.  In server mode, uses
        the ES ``semantic`` query on the ``content_semantic`` field.

        Args:
            query: Natural-language query string.
            filters: Optional metadata constraints.
            limit: Maximum number of results.

        Returns:
            List of ``SearchResult`` objects sorted by descending score.
        """
        from distillery.store.protocol import SearchResult

        filter_clauses = self._build_filter_clauses(filters)

        if self._effective_mode == "server":
            # Server mode: use semantic query instead of kNN.
            search_body: dict[str, Any] = {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "semantic": {
                                    "field": "content_semantic",
                                    "query": query,
                                }
                            }
                        ],
                        "filter": filter_clauses,
                    }
                },
                "size": limit,
            }
            resp = await self._client.search(
                index=self._alias_name("entries"),
                body=search_body,
            )
        else:
            # Client mode: embed query and use kNN search.
            query_vector = self._embedding_provider.embed(query)

            knn: dict[str, Any] = {
                "field": "embedding",
                "query_vector": query_vector,
                "k": limit,
                "num_candidates": limit * 10,
            }
            if filter_clauses:
                knn["filter"] = {"bool": {"filter": filter_clauses}}

            resp = await self._client.search(
                index=self._alias_name("entries"),
                knn=knn,
                size=limit,
            )

        hits: list[dict[str, Any]] = resp["hits"]["hits"]
        results: list[SearchResult] = []
        for hit in hits:
            score = self._convert_es_score(float(hit["_score"]))
            entry = _doc_to_entry(hit["_id"], hit["_source"])
            results.append(SearchResult(entry=entry, score=score))

        return results

    async def find_similar(
        self,
        content: str,
        threshold: float,
        limit: int,
    ) -> list[SearchResult]:
        """Find entries whose cosine similarity to *content* exceeds *threshold*.

        Embeds the content, issues a kNN search, converts scores, and filters
        results below *threshold*.

        Args:
            content: Raw text to compare against the stored corpus.
            threshold: Minimum cosine similarity (inclusive) in ``[0.0, 1.0]``.
            limit: Maximum number of results to return.

        Returns:
            List of ``SearchResult`` with ``score >= threshold``, sorted by
            descending score.
        """
        from distillery.store.protocol import SearchResult

        query_vector = self._embedding_provider.embed(content)

        # Convert the [0, 1] threshold to the ES [0, 1] score space.
        # ES cosine score = (1 + cosine) / 2, so min_score = (1 + threshold) / 2
        min_es_score = (1.0 + threshold) / 2.0

        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": query_vector,
            "k": limit,
            "num_candidates": limit * 10,
            "similarity": min_es_score,
        }

        resp = await self._client.search(
            index=self._alias_name("entries"),
            knn=knn,
            size=limit,
        )

        hits: list[dict[str, Any]] = resp["hits"]["hits"]
        results: list[SearchResult] = []
        for hit in hits:
            score = self._convert_es_score(float(hit["_score"]))
            if score >= threshold:
                entry = _doc_to_entry(hit["_id"], hit["_source"])
                results.append(SearchResult(entry=entry, score=score))

        return results

    async def list_entries(
        self,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
    ) -> list[Entry]:
        """List entries with optional filters, sorted by ``created_at`` descending.

        Uses a ``bool`` query with filter clauses and ``from``/``size``
        pagination.

        Args:
            filters: Optional metadata constraints.
            limit: Maximum number of entries to return (ES ``size``).
            offset: Number of entries to skip (ES ``from``).

        Returns:
            List of ``Entry`` objects matching the filters.
        """
        filter_clauses = self._build_filter_clauses(filters)

        body: dict[str, Any] = {
            "query": {"bool": {"filter": filter_clauses}} if filter_clauses else {
                "match_all": {}
            },
            "sort": [{"created_at": {"order": "desc"}}],
            "from": offset,
            "size": limit,
        }

        resp = await self._client.search(
            index=self._alias_name("entries"),
            body=body,
        )

        hits: list[dict[str, Any]] = resp["hits"]["hits"]
        return [_doc_to_entry(hit["_id"], hit["_source"]) for hit in hits]

    async def log_search(
        self,
        query: str,
        result_entry_ids: list[str],
        result_scores: list[float],
        session_id: str | None = None,
    ) -> str:
        """Log a search event in the search_log index.

        Indexes a document in ``{prefix}_search_log`` capturing the query,
        the ordered list of returned entry IDs with their scores, an optional
        session identifier, and a UTC timestamp.

        Args:
            query: The natural-language query string that was searched.
            result_entry_ids: Ordered list of entry IDs returned by the search.
            result_scores: Ordered list of similarity scores corresponding to
                ``result_entry_ids``.
            session_id: Optional opaque string grouping related searches from
                the same user session.

        Returns:
            The document ID of the newly created search_log document.
        """
        import uuid

        search_id = str(uuid.uuid4())
        doc: dict[str, Any] = {
            "query": query,
            "result_entry_ids": result_entry_ids,
            "result_scores": result_scores,
            "session_id": session_id,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }

        await self._client.index(
            index=self._alias_name("search_log"),
            id=search_id,
            document=doc,
            refresh="wait_for",
        )
        logger.debug(
            "Logged search id=%s query=%r results=%d",
            search_id,
            query,
            len(result_entry_ids),
        )
        return search_id

    async def log_feedback(
        self,
        search_id: str,
        entry_id: str,
        signal: str,
    ) -> str:
        """Log feedback in the feedback_log index.

        Indexes a document in ``{prefix}_feedback_log`` linking a specific
        search event to the entry the user interacted with.

        Args:
            search_id: The ID of the search_log document this feedback relates
                to.
            entry_id: The ID of the entry the user interacted with.
            signal: The type of interaction signal (e.g. ``"relevant"``,
                ``"not_relevant"``, ``"partial"``).

        Returns:
            The document ID of the newly created feedback_log document.
        """
        import uuid

        feedback_id = str(uuid.uuid4())
        doc: dict[str, Any] = {
            "search_id": search_id,
            "entry_id": entry_id,
            "signal": signal,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }

        await self._client.index(
            index=self._alias_name("feedback_log"),
            id=feedback_id,
            document=doc,
            refresh="wait_for",
        )
        logger.debug(
            "Logged feedback id=%s search_id=%s entry_id=%s signal=%r",
            feedback_id,
            search_id,
            entry_id,
            signal,
        )
        return feedback_id
