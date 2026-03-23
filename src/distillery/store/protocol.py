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
        """List entries with optional metadata filtering and pagination.

        Unlike ``search``, this method does not perform semantic ranking -- it
        returns entries in insertion order (descending ``created_at``).

        Supports the same filter keys as ``search`` (``entry_type``,
        ``author``, ``project``, ``tags``, ``status``, date ranges).

        Args:
            filters: Optional dict of metadata constraints.
            limit: Maximum number of entries to return per page.
            offset: Number of entries to skip (for pagination).

        Returns:
            List of ``Entry`` objects matching the filters.
        """
        ...
