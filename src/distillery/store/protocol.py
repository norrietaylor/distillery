"""DistilleryStore protocol and SearchResult dataclass.

This module defines the abstract storage interface that all storage backends
must satisfy. Using Python's Protocol class enables structural subtyping,
so any class implementing the required async methods is a valid backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, overload, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from distillery.models import Entry


@dataclass
class SearchResult:
    """A single result from a semantic search or similarity query.

    Attributes:
        entry: The matched knowledge entry.
        score: Cosine similarity score in the range [0.0, 1.0].  Higher is
            more similar.  For ``find_similar`` results this value exceeds
            the caller-supplied threshold.
    """

    entry: Entry
    score: float


@runtime_checkable
class DistilleryStore(Protocol):
    """Abstract storage protocol for the Distillery knowledge base.

    All concrete storage backends (DuckDB, Elasticsearch, ...) must satisfy
    this interface.  Methods are async so that blocking I/O can be wrapped
    in ``asyncio.to_thread()`` without leaking into callers.

    Example usage::

        store: DistilleryStore = DuckDBStore(config)
        entry_id = await store.store(entry)
        result = await store.get(entry_id)
    """

    async def store(self, entry: Entry) -> str:
        """Persist a new entry and return its ID.

        Args:
            entry: The ``Entry`` instance to persist.  The ``id`` field is
                used as the primary key; callers should allow ``Entry`` to
                auto-generate one via ``uuid.uuid4()``.

        Returns:
            The string representation of the stored entry's UUID.
        """
        ...

    async def get(self, entry_id: str) -> Entry | None:
        """Retrieve an entry by its ID.

        Args:
            entry_id: The UUID string of the entry to fetch.

        Returns:
            The matching ``Entry``, or ``None`` if no entry with that ID
            exists or if the entry has been soft-deleted (status ``archived``).
        """
        ...

    async def update(self, entry_id: str, updates: dict[str, Any]) -> Entry:
        """Apply a partial update to an existing entry.

        Increments ``version`` by 1 and refreshes ``updated_at`` to the
        current UTC time.  Attempts to update ``id``, ``created_at``, or
        ``source`` are rejected with a ``ValueError``.

        Args:
            entry_id: The UUID string of the entry to update.
            updates: A dict of field names to new values.  Only writable
                fields are accepted.

        Returns:
            The updated ``Entry`` reflecting all applied changes.

        Raises:
            ValueError: If ``updates`` contains any of the immutable fields
                (``id``, ``created_at``, ``source``).
            KeyError: If no entry with ``entry_id`` exists.
        """
        ...

    async def delete(self, entry_id: str) -> bool:
        """Soft-delete an entry by setting its status to ``archived``.

        Args:
            entry_id: The UUID string of the entry to delete.

        Returns:
            ``True`` if the entry was found and archived, ``False`` if no
            entry with that ID exists.
        """
        ...

    async def search(
        self,
        query: str,
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[SearchResult]:
        """Perform semantic search with optional metadata filters.

        Embeds ``query`` using the configured ``EmbeddingProvider``, finds
        the nearest neighbours by cosine similarity, and applies any
        ``filters`` as post-processing.

        Supported filter keys:
            - ``entry_type`` (str | list[str])
            - ``author`` (str)
            - ``project`` (str)
            - ``tags`` (list[str]) -- matches entries containing *any* tag
            - ``status`` (str)
            - ``verification`` (str) -- one of ``"unverified"``, ``"testing"``, ``"verified"``
            - ``date_from`` (datetime | str) -- inclusive lower bound on ``created_at``
            - ``date_to`` (datetime | str) -- inclusive upper bound on ``created_at``

        Args:
            query: Natural-language query string to embed and search.
            filters: Optional dict of metadata constraints.  ``None`` means
                no filtering.
            limit: Maximum number of results to return.

        Returns:
            List of ``SearchResult`` objects sorted by descending similarity
            score.
        """
        ...

    async def find_similar(
        self,
        content: str,
        threshold: float,
        limit: int,
    ) -> list[SearchResult]:
        """Find entries whose cosine similarity to *content* exceeds *threshold*.

        Intended for deduplication checks before storing new content.

        Args:
            content: Raw text to compare against the stored corpus.
            threshold: Minimum cosine similarity (inclusive) for a result to
                be returned.  Typical values: ``0.8`` (near-duplicate),
                ``0.95`` (very high confidence duplicate).
            limit: Maximum number of results to return.

        Returns:
            List of ``SearchResult`` objects with ``score >= threshold``,
            sorted by descending score.
        """
        ...

    @overload
    async def list_entries(
        self,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
        *,
        stale_days: int | None = ...,
        group_by: None = ...,
        output: None = ...,
    ) -> list[Entry]: ...

    @overload
    async def list_entries(
        self,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
        *,
        stale_days: int | None = ...,
        group_by: str | None = ...,
        output: str | None = ...,
    ) -> list[Entry] | dict[str, Any]: ...

    async def list_entries(
        self,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
        *,
        stale_days: int | None = None,
        group_by: str | None = None,
        output: str | None = None,
    ) -> list[Entry] | dict[str, Any]:
        """
        List entries filtered by metadata with pagination.

        Returns entries in insertion order (sorted by descending ``created_at``)
        and does not perform semantic ranking.  When *group_by* or
        *output="stats"* is specified the return type changes to a dict.

        Parameters:
            filters: Optional metadata constraints. Supported keys:
                ``entry_type``, ``author``, ``project``, ``tags`` (matches any
                tag), ``status``, ``verification``, ``date_from``, ``date_to``.
            limit: Maximum number of entries (or groups) to return.
            offset: Number of entries to skip for pagination (ignored in
                group_by / stats modes).
            stale_days: When set, restricts results to entries whose last
                access (``COALESCE(accessed_at, updated_at)``) is older than
                *stale_days* days.  Composes with all other filters.
            group_by: When set, returns ``{"groups": [...], "total_groups": N,
                "total_entries": N}`` instead of a list of entries.  Supported
                values mirror ``aggregate_entries`` plus ``"tags"`` (unnests
                the tags array).  When ``group_by="tags"`` the ``tag_prefix``
                filter key is honoured.
            output: When ``"stats"``, returns aggregate statistics:
                ``entries_by_type``, ``entries_by_status``, ``total_entries``,
                ``storage_bytes``.  Mutually exclusive with *group_by*.

        Returns:
            ``list[Entry]`` in default mode; ``dict[str, Any]`` when
            *group_by* or *output="stats"* is supplied.
        """
        ...

    async def count_entries(
        self,
        filters: dict[str, Any] | None,
    ) -> int:
        """
        Count entries matching the given filters without fetching them.

        Parameters:
            filters (dict[str, Any] | None): Same filter keys as ``list_entries``.

        Returns:
            int: Total number of matching entries.
        """
        ...

    async def log_search(
        self,
        query: str,
        result_entry_ids: list[str],
        result_scores: list[float],
        session_id: str | None = None,
    ) -> str:
        """
        Record a search event in the search_log and return the created log row ID.

        Records the query text, the ordered list of returned entry IDs with their corresponding similarity scores, and an optional session identifier for grouping related searches. The order of result_entry_ids must match the order of result_scores.

        Parameters:
            query (str): The natural-language query string.
            result_entry_ids (list[str]): Ordered list of entry UUIDs returned by the search.
            result_scores (list[float]): Ordered list of similarity scores corresponding to result_entry_ids.
            session_id (str | None): Optional opaque string that groups searches from the same user session.

        Returns:
            str: The UUID string of the newly created search_log row.
        """
        ...

    async def log_feedback(
        self,
        search_id: str,
        entry_id: str,
        signal: str,
    ) -> str:
        """Record implicit feedback for a search result and return its ID.

        Appends a row to the ``feedback_log`` table linking a specific
        search event to the entry the user interacted with.

        Args:
            search_id: UUID of the ``search_log`` row this feedback relates
                to.
            entry_id: UUID of the ``entries`` row the user interacted with.
            signal: The type of interaction signal (e.g. ``"retrieved"``,
                ``"applied"``, ``"ignored"``).

        Returns:
            The UUID string of the newly created ``feedback_log`` row.
        """
        ...

    async def get_searches_for_entry(self, entry_id: str, since: datetime) -> list[str]:
        """Return IDs of search_log rows that include entry_id and are newer than since.

        Queries the persistent ``search_log`` table so the result is correct
        across process restarts (e.g. Lambda invocations).

        Args:
            entry_id: UUID of the entry to look up in search results.
            since: Inclusive lower bound on ``search_log.timestamp``.

        Returns:
            List of search_log row IDs (UUID strings) for matching searches.
        """
        ...

    async def list_feed_sources(self) -> list[dict[str, Any]]:
        """Return all persisted feed sources as dicts.

        Each dict contains keys: ``url``, ``source_type``, ``label``,
        ``poll_interval_minutes``, ``trust_weight``.

        Returns:
            List of feed source dicts ordered by creation time.
        """
        ...

    async def add_feed_source(
        self,
        url: str,
        source_type: str,
        label: str = "",
        poll_interval_minutes: int = 60,
        trust_weight: float = 1.0,
    ) -> dict[str, Any]:
        """Persist a new feed source and return it as a dict.

        Args:
            url: Feed URL (used as primary key).
            source_type: Adapter type (e.g. ``"rss"``, ``"github"``).
            label: Human-readable label.
            poll_interval_minutes: Poll frequency in minutes.
            trust_weight: Relevance multiplier in ``[0.0, 1.0]``.

        Returns:
            Dict with the stored feed source fields.

        Raises:
            ValueError: If a source with the same URL already exists.
        """
        ...

    async def remove_feed_source(self, url: str) -> bool:
        """Remove a feed source by URL.

        Args:
            url: The exact URL of the source to remove.

        Returns:
            ``True`` if the source existed and was removed, ``False``
            otherwise.
        """
        ...

    async def aggregate_entries(
        self,
        group_by: str,
        filters: dict[str, Any] | None,
        limit: int,
    ) -> dict[str, Any]:
        """Return entry counts grouped by a field, sorted by count descending.

        Args:
            group_by: Logical field name to group by (e.g. ``"entry_type"``,
                ``"metadata.source_url"``).  The caller is responsible for
                validating this against an allowlist before passing it in.
            filters: Optional metadata constraints (same format as
                :meth:`list_entries`).
            limit: Maximum number of groups to return.

        Returns:
            Dict with ``"groups"`` (limited list of ``{"value": ..., "count": ...}``),
            ``"total_groups"`` (int), and ``"total_entries"`` (int).
        """
        ...

    async def add_relation(
        self,
        from_id: str,
        to_id: str,
        relation_type: str,
    ) -> str:
        """Create a typed relation between two entries and return its UUID.

        Args:
            from_id: UUID string of the source entry.
            to_id: UUID string of the target entry.
            relation_type: Freeform label for the relation (e.g. ``"link"``,
                ``"blocks"``, ``"related"``).

        Returns:
            The UUID string of the newly created relation row.

        Raises:
            ValueError: If either ``from_id`` or ``to_id`` does not exist in
                the store.
        """
        ...

    async def get_related(
        self,
        entry_id: str,
        direction: str = "both",
        relation_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return relations for an entry, optionally filtered by direction and type.

        Args:
            entry_id: UUID string of the entry whose relations to fetch.
            direction: One of ``"outgoing"`` (entry is ``from_id``),
                ``"incoming"`` (entry is ``to_id``), or ``"both"``
                (default, returns all).
            relation_type: Optional filter restricting results to rows with
                this ``relation_type`` value.  ``None`` returns all types.

        Returns:
            List of dicts, each containing keys: ``id``, ``from_id``,
            ``to_id``, ``relation_type``, ``created_at`` (ISO 8601 str).
            Ordered by ascending ``created_at``.
        """
        ...

    async def remove_relation(self, relation_id: str) -> bool:
        """Delete a relation row by its UUID.

        Args:
            relation_id: UUID string of the ``entry_relations`` row to remove.

        Returns:
            ``True`` if the row existed and was deleted, ``False`` if no row
            with that ID existed.
        """
        ...

    async def get_metadata(self, key: str) -> str | None:
        """Read a value from the ``_meta`` key-value table.

        Args:
            key: Metadata key to look up.

        Returns:
            The stored string value, or ``None`` if the key does not exist.
        """
        ...

    async def set_metadata(self, key: str, value: str) -> None:
        """Write a value to the ``_meta`` key-value table (upsert).

        Args:
            key: Metadata key.
            value: String value to store.
        """
        ...

    async def get_tag_vocabulary(self, prefix: str | None = None) -> dict[str, int]:
        """Return a mapping of tag to occurrence count across active entries.

        Counts how many active (non-archived) entries carry each tag.  When
        *prefix* is supplied, only tags that equal the prefix or start with
        ``"{prefix}/"`` are included in the result.

        Args:
            prefix: Optional hierarchical tag prefix to filter by (e.g.
                ``"python"`` matches ``"python"`` and ``"python/3.11"`` but not
                ``"python-legacy"``).

        Returns:
            Dict mapping each matching tag string to the number of active
            entries that carry it, sorted by count descending then tag
            ascending.  Returns an empty dict when the store contains no
            active entries with matching tags.
        """
        ...

    async def query_audit_log(
        self,
        filters: dict[str, Any] | None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query the ``audit_log`` table with optional filters.

        Supports filtering by user, operation (tool name), and date range.
        Results are ordered by timestamp descending.

        Supported filter keys:
            - ``user`` (str) -- match ``user_id`` exactly
            - ``operation`` (str) -- match ``tool`` exactly
            - ``date_from`` (str) -- inclusive lower bound on ``timestamp`` (ISO 8601)
            - ``date_to`` (str) -- inclusive upper bound on ``timestamp`` (ISO 8601)

        Args:
            filters: Optional dict of filter constraints.  ``None`` means no
                filtering.
            limit: Maximum number of rows to return.  Must be in [1, 500];
                values below 1 are clamped to 1 and values above 500 are
                clamped to 500.  Default is 50.

        Returns:
            List of dicts, each containing keys: ``id``, ``timestamp``
            (ISO 8601 str), ``user_id``, ``tool``, ``entry_id``, ``action``,
            ``outcome``.  Ordered by descending timestamp.
        """
        ...
