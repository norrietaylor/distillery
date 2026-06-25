"""DistilleryStore protocol and SearchResult dataclass.

This module defines the abstract storage interface that all storage backends
must satisfy. Using Python's Protocol class enables structural subtyping,
so any class implementing the required async methods is a valid backend.
"""

from __future__ import annotations

from collections.abc import Sequence
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

    async def rollback(self) -> None:
        """Roll back any aborted transaction on the shared connection.

        Safe to call at any time.  Intended for MCP tool handlers that
        touch the underlying connection directly (e.g. the per-request
        embedding-budget counter) so they can clear an aborted-transaction
        state before subsequent requests hit the same connection.  See
        issue #363.
        """
        ...

    async def probe_readiness(self) -> tuple[bool, str | None]:
        """Return ``(True, None)`` when the store can answer a trivial query.

        Returns ``(False, message)`` when the underlying database is
        present but unqueryable (e.g. partial WAL replay, half-applied
        migration, corrupt segment) so health probes can surface the
        durable failure instead of silently falling back to null in the
        ``distillery_status`` payload.  See issue #363 follow-up.
        """
        ...

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

    async def store_batch(self, entries: Sequence[Entry]) -> list[str]:
        """Batch-store entries and return their IDs.

        Embeds all entry contents in a single batch call and inserts all
        entries in one transaction.  No deduplication or conflict checks
        are performed — this method is designed for bulk ingestion.

        Args:
            entries: Sequence of ``Entry`` instances to persist.

        Returns:
            List of UUID strings for the stored entries, in the same
            order as the input sequence.
        """
        ...

    async def get(self, entry_id: str, *, include_archived: bool = False) -> Entry | None:
        """Retrieve an entry by its ID.

        Args:
            entry_id: The UUID string of the entry to fetch.
            include_archived: If ``True``, soft-deleted entries (status
                ``archived``) are also returned.  Defaults to ``False`` so
                callers must opt in to seeing archived data.

        Returns:
            The matching ``Entry``, or ``None`` if no entry with that ID
            exists or if the entry has been soft-deleted (status ``archived``)
            and ``include_archived`` is ``False``.
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
            - ``tags`` (list[str]) -- matches entries containing *all* listed
              tags (AND / intersection)
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

    async def find_similar_by_id(
        self,
        source_entry_id: str,
        threshold: float,
        limit: int,
    ) -> list[SearchResult] | None:
        """Single-seed similarity using the entry's STORED embedding.

        Reuses the entry's already-computed embedding vector — no re-embed and
        no embedding-budget spend.

        Args:
            source_entry_id: UUID string of the entry whose stored embedding is
                used as the similarity probe.
            threshold: Minimum cosine similarity (inclusive) in ``[0.0, 1.0]``.
            limit: Maximum number of results to return.

        Returns:
            List of ``SearchResult`` objects (archived excluded; the seed itself
            is NOT excluded — the caller handles self/linked exclusion), sorted
            by descending score; or ``None`` when the entry is missing or has no
            stored embedding (so the caller can fall back to the embed path).
        """
        ...

    async def find_similar_by_ids(
        self,
        source_entry_ids: list[str],
        threshold: float,
        limit: int,
        exclude_linked: bool,
    ) -> dict[str, list[SearchResult]]:
        """Batch similarity using each entry's STORED embedding.

        For a list of source entry ids, reuses each entry's already-stored
        embedding vector (no re-embed, no embedding-budget spend) and runs all
        similarity queries in one read acquisition.

        Args:
            source_entry_ids: UUID strings of the seed entries.
            threshold: Minimum cosine similarity (inclusive) in ``[0.0, 1.0]``.
            limit: Maximum number of results to return per seed.
            exclude_linked: When ``True``, results for each seed also exclude
                ids linked to that seed via ``entry_relations`` (either
                direction, any relation_type). The seed itself is always
                self-excluded.

        Returns:
            Dict keyed by every requested id; each value is the list of
            ``SearchResult`` objects for that seed (archived, self, and — when
            *exclude_linked* — linked ids removed), sorted by descending score
            and capped at *limit*. A seed with no stored embedding maps to an
            empty list rather than raising.
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
                ``entry_type``, ``author``, ``project``, ``tags`` (matches
                entries containing all listed tags — AND / intersection),
                ``status`` (str or list[str] — a list matches any of the
                listed statuses via SQL ``IN``), ``verification`` (one of
                "unverified", "testing", "verified"), ``date_from``, ``date_to``.
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

        Notes:
            This method performs no implicit status filtering. Callers that want
            to exclude archived entries by default must pass
            ``status=["active", "pending_review"]`` (or similar) explicitly. The
            MCP ``distillery_list`` tool applies this default on behalf of the
            caller.
        """
        ...

    async def count_entries(
        self,
        filters: dict[str, Any] | None,
        *,
        stale_days: int | None = None,
    ) -> int:
        """
        Count entries matching the given filters without fetching them.

        Parameters:
            filters (dict[str, Any] | None): Same filter keys as ``list_entries``.
            stale_days: When set, only count entries whose last access
                (``COALESCE(accessed_at, updated_at)``) is older than N days.

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
        ``poll_interval_minutes``, ``trust_weight``, ``last_polled_at``
        (ISO 8601 string or ``None``), ``last_item_count`` (int),
        ``last_error`` (str or ``None``), ``next_poll_at``
        (ISO 8601 string or ``None``), per-source threshold
        overrides ``threshold_alert`` / ``threshold_digest`` (float in
        ``[0.0, 1.0]`` or ``None`` to fall back to the global
        ``feeds.thresholds`` values), and ``mode`` (adapter surface
        selector; empty string means "adapter default").

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
        threshold_alert: float | None = None,
        threshold_digest: float | None = None,
        mode: str = "",
    ) -> dict[str, Any]:
        """Persist a new feed source and return it as a dict.

        Args:
            url: Feed URL (used as primary key).
            source_type: Adapter type (e.g. ``"rss"``, ``"github"``).
            label: Human-readable label.
            poll_interval_minutes: Poll frequency in minutes.
            trust_weight: Relevance multiplier in ``[0.0, 1.0]``.
            threshold_alert: Optional per-source override of
                ``feeds.thresholds.alert`` in ``[0.0, 1.0]``.  ``None``
                falls back to the global value.
            threshold_digest: Optional per-source override of
                ``feeds.thresholds.digest`` in ``[0.0, 1.0]``.  ``None``
                falls back to the global value.
            mode: Adapter-specific surface selector.  For ``github`` sources
                ``"releases"`` (default) or ``"events"``.  Empty string means
                "adapter default".

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

    async def record_poll_status(
        self,
        url: str,
        *,
        polled_at: datetime,
        item_count: int,
        error: str | None,
    ) -> bool:
        """Persist the outcome of a poll against a feed source.

        Args:
            url: The feed source URL (primary key).
            polled_at: UTC timestamp of the poll attempt.
            item_count: Items successfully ingested during the poll.
            error: Error message when the poll failed, or ``None`` on
                success.  Implementations must truncate and sanitise the
                value before persistence.

        Returns:
            ``True`` if the row was updated, ``False`` if no source with
            *url* exists.
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
        weight: float | None = None,
        valid_at: str | datetime | None = None,
        invalid_at: str | datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a typed relation between two entries and return its UUID.

        Args:
            from_id: UUID string of the source entry.
            to_id: UUID string of the target entry.
            relation_type: Freeform label for the relation (e.g. ``"link"``,
                ``"blocks"``, ``"related"``).
            weight: Optional edge strength (e.g. interest/engagement magnitude).
            valid_at: Optional instant the relationship became true (datetime or
                ISO 8601 string).
            invalid_at: Optional instant it stopped being true (``None`` = still
                valid) — the bi-temporal validity window.
            metadata: Optional arbitrary per-edge attributes (JSON-serialisable).

        Returns:
            The UUID string of the relation row.  Idempotent on the
            ``(from_id, to_id, relation_type)`` triple; on a re-assert the
            supplied (non-``None``) attributes are upserted onto the existing row.

        Raises:
            ValueError: If either ``from_id`` or ``to_id`` does not exist in
                the store.
        """
        ...

    async def verify_entries_readable(self, entry_ids: Sequence[str]) -> None:
        """Verify the ``entries`` table is readable after a bulk rewrite.

        Call after any operation that bulk-rewrites ``entries`` across the
        variable-length VARCHAR / embedding columns (dedup, merge, batch
        rewrite).  Implementations checkpoint, read back the touched rows
        (materialising the variable-length columns rather than relying on
        ``COUNT(*)``), and run a bounded integrity sweep, then fail loud if any
        step errors (issue #584).

        Args:
            entry_ids: UUID strings of the rows touched by the rewrite.

        Raises:
            Exception: If the post-rewrite read-back fails — the table is no
                longer readable and the caller must not report success.
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
            ``to_id``, ``relation_type``, ``created_at`` (ISO 8601 str),
            ``weight`` (float | None), ``valid_at`` / ``invalid_at`` (ISO 8601
            str | None), ``metadata`` (dict | None).
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

    async def list_relations(self) -> list[dict[str, Any]]:
        """Return every row from ``entry_relations`` as a list of dicts.

        Intended for graph metrics computation that needs the entire relations
        subgraph in one shot.  Implementations must run any underlying sync
        I/O off the event loop so async callers are not blocked.

        Returns:
            List of dicts with keys: ``id``, ``from_id``, ``to_id``,
            ``relation_type``, ``created_at`` (ISO 8601 str), ``weight``
            (float | None), ``valid_at`` / ``invalid_at`` (ISO 8601 str | None),
            ``metadata`` (dict | None).  Ordered by ascending ``created_at``.
        """
        ...

    async def add_relation_candidate(
        self,
        from_id: str,
        to_id: str,
        relation_type: str,
        suggestion_score: float,
    ) -> str:
        """Persist a pending relation candidate as an ``entry_relations`` row.

        Writes the candidate with ``metadata.review_status = "pending"`` and
        ``metadata.suggestion_score = suggestion_score``.  Idempotent: if a row
        for the same ``(from_id, to_id, relation_type)`` already exists (as a
        live edge or an existing pending candidate) the existing row's UUID is
        returned without modification.  No new database table is introduced.

        Args:
            from_id: UUID string of the source entry.
            to_id: UUID string of the target entry.
            relation_type: Relation type label (e.g. ``"related"``).
            suggestion_score: Confidence score from the suggester (0.0–1.0).

        Returns:
            The UUID string of the relation row (existing or newly created).

        Raises:
            ValueError: If ``suggestion_score`` is outside ``0.0–1.0``, or if
                either ``from_id`` or ``to_id`` does not exist in the store.
        """
        ...

    async def list_relation_candidates(self) -> list[dict[str, Any]]:
        """Return all pending relation candidates ordered by score descending.

        Pending candidates are ``entry_relations`` rows whose metadata carries
        ``review_status = "pending"``.  Only such rows are returned; live edges
        (no ``review_status`` or ``review_status != "pending"``) are excluded.

        Returns:
            List of dicts with keys: ``id``, ``from_id``, ``to_id``,
            ``relation_type``, ``suggestion_score`` (float), ``created_at``
            (ISO 8601 str), ``weight`` (float | None), ``metadata``
            (dict | None).  Ordered by ``suggestion_score`` descending (ties
            broken by ascending ``created_at``).
        """
        ...

    async def promote_entities(
        self,
        threshold: int,
        reserved_prefixes: list[str] | None = None,
        aliases: dict[str, str] | None = None,
    ) -> dict[str, int]:
        """Promote recurring ``entity/*`` and ``tech/*`` tags to entity nodes.

        Scans the tag vocabulary, resolves each tag through the controlled-
        vocabulary *aliases* map and then the ``normalize_tag`` separator-
        collapse so variant spellings (``entity/cloudflare/workers`` vs
        ``entity/cloudflare-workers``) and declared aliases
        (``entity/cloudflare-sandboxes`` -> ``entity/cloudflare``) converge to
        one canonical key, and for every canonical ``entity/*`` / ``tech/*`` tag
        appearing on at least *threshold* entries:

          * finds-or-creates exactly one ``entity`` entry keyed idempotently on
            the canonical tag (stored as ``metadata.source_tag``); no duplicate
            node is created on re-run.
          * for every entry carrying the (canonical) tag, creates a
            ``mentions`` edge from that entry to the entity node, idempotent on
            the ``(from_id, to_id, relation_type)`` unique index.

        Fully idempotent: a second consecutive run creates zero nodes and zero
        edges.

        Args:
            threshold: Minimum number of entries a canonical tag must appear on
                before it is promoted.
            reserved_prefixes: Tag namespace prefixes eligible for
                ``normalize_tag`` collapsing (typically
                ``config.tags.reserved_prefixes``).  ``entity`` and ``tech`` are
                always treated as reserved for promotion regardless of this
                argument.  ``None`` is treated as an empty list.
            aliases: Controlled-vocabulary ``alias -> canonical`` map (typically
                ``config.tags.aliases``) applied before the separator-collapse so
                aliased variants promote to the same node.  ``None`` is treated
                as an empty map.

        Returns:
            Dict with ``entities_created`` (new entity nodes inserted),
            ``entities_reused`` (qualifying tags whose node already existed),
            and ``mentions_created`` (``mentions`` edges inserted).
        """
        ...

    async def canonicalize_existing_tags(
        self,
        aliases: dict[str, str],
        reserved_prefixes: list[str] | None = None,
        normalize_namespaces: bool = False,
    ) -> dict[str, int]:
        """Rewrite stored tags through the controlled vocabulary (issue #653).

        Backfill for ontology #3: scans every non-archived entry and rewrites
        its tag list via :func:`distillery.feeds.tags.canonicalize_tags`
        (alias substitution, then optional namespace normalization, then an
        order-preserving dedupe). Only entries whose tag list actually changes
        are written, so the operation is idempotent — a second run rewrites zero
        rows. Embeddings are not recomputed (tags do not feed embeddings) and
        ``updated_at`` is left untouched so recency signals are preserved.

        Run this before a full :meth:`promote_entities` re-run so entity nodes
        key off the canonical tag form.

        Args:
            aliases: Flattened ``alias -> canonical`` map
                (``config.tags.aliases``).
            reserved_prefixes: Prefixes eligible for namespace normalization
                (only used when *normalize_namespaces* is true). ``None`` is an
                empty list.
            normalize_namespaces: When true, also apply the ``normalize_tag``
                separator-collapse (typically ``config.tags.enforce_namespaces``).

        Returns:
            Dict with ``entries_scanned``, ``entries_rewritten`` and
            ``tags_collapsed`` (total tags removed by within-entry dedupe).
        """
        ...

    async def reconcile_relations(self) -> dict[str, int]:
        """Re-run idempotent edge-population mechanisms and return insert counts.

        Recovery hook for ``distillery_relations action="reconcile"`` (issue
        #490 mechanism #9).  Re-scans every entry's ``metadata.related_entries``
        and inserts any missing rows into ``entry_relations``; relies on the
        unique ``(from_id, to_id, relation_type)`` index for idempotency.

        Returns:
            Dict with at least ``metadata_links`` (rows inserted from
            ``metadata.related_entries``) and ``total``.  Future mechanisms
            (#3-#8 in issue #490) will contribute additional named keys
            without changing the existing contract.
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

    async def get_link_suggestion_seeds(self, limit: int) -> list[str]:
        """Return entry IDs for low-degree / orphan nodes to seed the link-suggestion sweep.

        Selects active (non-archived) entries that are structural candidates for
        edge creation: true orphans (no row in ``entry_relations`` as either
        endpoint) first, then low-degree nodes (fewest relations), both ordered
        so the most-neglected entries are swept first.  The result is bounded by
        *limit* to prevent runaway scans on large graphs.

        The caller passes ``config.link_suggestion.max_candidates_per_run`` as
        *limit*; this method never scores all non-existent edges globally.

        Args:
            limit: Maximum number of entry IDs to return.  Must be a positive
                integer.

        Returns:
            List of entry UUID strings, length at most *limit*, ordered by
            ascending relation-degree then ascending ``created_at`` (oldest
            orphan / lowest-degree node first).  Never includes archived entries.
        """
        ...

    async def suggest_links(
        self,
        *,
        auto_create_threshold: float = 0.85,
        review_floor: float = 0.60,
        max_candidates_per_run: int = 200,
        max_neighbours_per_seed: int = 10,
    ) -> dict[str, int]:
        """Sweep low-degree nodes, score candidate edges, and route by threshold.

        The headless link-suggestion core (issue #653 step 3).  Generates
        candidate edges for each seed node, routes by stored-embedding cosine
        score, and returns count totals.  Performs no LLM or embedding
        inference.  All writes are idempotent, so a second consecutive run
        reports ``edges_created == 0`` and ``candidates_queued == 0``.

        Args:
            auto_create_threshold: Score at/above which a pair becomes a live
                edge.  Defaults to ``0.85``.
            review_floor: Minimum score for a pair to be queued for review
                rather than discarded.  Defaults to ``0.60``.
            max_candidates_per_run: Upper bound on the number of seed nodes
                swept in a single run.  Defaults to ``200``.
            max_neighbours_per_seed: Cap on candidate targets considered per
                seed from each source.  Defaults to ``10``.

        Returns:
            Counts dict with keys ``edges_created``, ``candidates_queued``,
            ``discarded``, and ``nodes_scanned``.
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
