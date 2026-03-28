"""DistilleryStore protocol and SearchResult dataclass.

This module defines the abstract storage interface that all storage backends
must satisfy. Using Python's Protocol class enables structural subtyping,
so any class implementing the required async methods is a valid backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
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

    async def list_entries(
        self,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
    ) -> list[Entry]:
        """
        List entries filtered by metadata with pagination.
        
        Returns entries in insertion order (sorted by descending `created_at`) and does not perform semantic ranking.
        
        Parameters:
            filters (dict[str, Any] | None): Optional metadata constraints. Supported keys: `entry_type`, `author`, `project`, `tags` (matches any tag), `status`, `date_from`, `date_to`.
            limit (int): Maximum number of entries to return.
            offset (int): Number of entries to skip for pagination.
        
        Returns:
            list[Entry]: Entries matching the filters, ordered by descending `created_at`.
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
