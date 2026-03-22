"""Data models for Distillery.

This module defines the canonical ``Entry`` dataclass used throughout the
Distillery system, along with its associated enums and the ``SearchResult``
dataclass returned by semantic search operations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EntryType(str, Enum):
    """The semantic category of a knowledge entry.

    Attributes:
        SESSION: A captured work session or context snapshot.
        BOOKMARK: A saved URL or external reference.
        MINUTES: Notes from a meeting or discussion.
        MEETING: A meeting record (agenda, participants, outcomes).
        REFERENCE: A reference document, snippet, or fact.
        IDEA: An idea, hypothesis, or open question.
        INBOX: An unsorted entry awaiting classification.
    """

    SESSION = "session"
    BOOKMARK = "bookmark"
    MINUTES = "minutes"
    MEETING = "meeting"
    REFERENCE = "reference"
    IDEA = "idea"
    INBOX = "inbox"


class EntrySource(str, Enum):
    """The origin of an entry in the system.

    Attributes:
        CLAUDE_CODE: Created by a Claude Code skill (e.g. ``/distill``).
        MANUAL: Created directly by a human operator.
        IMPORT: Bulk-imported from an external source.
    """

    CLAUDE_CODE = "claude-code"
    MANUAL = "manual"
    IMPORT = "import"


class EntryStatus(str, Enum):
    """The lifecycle state of an entry.

    Attributes:
        ACTIVE: The entry is live and visible to searches.
        PENDING_REVIEW: The entry has been created but not yet reviewed.
        ARCHIVED: The entry has been soft-deleted and is hidden from searches.
    """

    ACTIVE = "active"
    PENDING_REVIEW = "pending_review"
    ARCHIVED = "archived"


def _utcnow() -> datetime:
    """Return the current UTC datetime with timezone info."""
    return datetime.now(tz=timezone.utc)


def _new_uuid() -> str:
    """Return a new UUID4 as a string."""
    return str(uuid.uuid4())


@dataclass
class Entry:
    """A single knowledge entry stored in the Distillery knowledge base.

    Fields are divided into required fields (must be supplied by the caller),
    auto-generated fields (set by the dataclass defaults), and optional fields
    (default to ``None`` or an empty collection).

    Required caller-supplied fields:
        content: The full text of the knowledge entry.
        entry_type: Semantic category (``EntryType`` enum).
        source: Where the entry originated (``EntrySource`` enum).
        author: The creator's identifier (e.g. a GitHub username).

    Auto-generated fields:
        id: UUID4 string, generated at construction time.
        created_at: UTC timestamp set at construction time.
        updated_at: UTC timestamp, updated on every change.
        version: Monotonically increasing edit counter, starts at 1.

    Optional fields:
        project: Optional project or repository name for scoping.
        tags: Arbitrary string labels for faceted retrieval.
        status: Lifecycle state, defaults to ``EntryStatus.ACTIVE``.
        metadata: Type-specific extension fields.  Common keys:

            - Session entries: ``session_id`` (str), ``session_type``
              (``"work"`` | ``"cowork"``)
            - Bookmark entries: ``url`` (str), ``summary`` (str)
            - Minutes entries: ``meeting_id`` (str)

    Example::

        from distillery.models import Entry, EntryType, EntrySource

        entry = Entry(
            content="Discussed caching strategy for the API layer.",
            entry_type=EntryType.SESSION,
            source=EntrySource.CLAUDE_CODE,
            author="alice",
            project="api-refactor",
            tags=["architecture", "caching"],
        )
        as_dict = entry.to_dict()
        restored = Entry.from_dict(as_dict)
        assert restored == entry
    """

    # --- required caller-supplied ---
    content: str
    entry_type: EntryType
    source: EntrySource
    author: str

    # --- auto-generated ---
    id: str = field(default_factory=_new_uuid)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    version: int = 1

    # --- optional ---
    project: str | None = None
    tags: list[str] = field(default_factory=list)
    status: EntryStatus = EntryStatus.ACTIVE
    metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """Serialise this entry to a JSON-compatible dictionary.

        All enum values are stored as their string values.  ``datetime``
        fields are stored as ISO 8601 strings with UTC offset (``+00:00``).

        Returns:
            A flat dictionary suitable for ``json.dumps`` or YAML serialisation.
        """
        return {
            "id": self.id,
            "content": self.content,
            "entry_type": self.entry_type.value,
            "source": self.source.value,
            "author": self.author,
            "project": self.project,
            "tags": list(self.tags),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Entry":
        """Reconstruct an ``Entry`` from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary with the same keys as :meth:`to_dict`.  Values
                for ``entry_type``, ``source``, and ``status`` may be either
                the enum instance or the underlying string value.

        Returns:
            A fully initialised ``Entry`` instance.

        Raises:
            KeyError: If a required key is absent from ``data``.
            ValueError: If an enum value string is not recognised.
        """

        def _parse_dt(value: str | datetime) -> datetime:
            if isinstance(value, datetime):
                return value
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt

        return cls(
            id=data["id"],
            content=data["content"],
            entry_type=EntryType(data["entry_type"]),
            source=EntrySource(data["source"]),
            author=data["author"],
            project=data.get("project"),
            tags=list(data.get("tags", [])),
            status=EntryStatus(data.get("status", EntryStatus.ACTIVE.value)),
            created_at=_parse_dt(data["created_at"]),
            updated_at=_parse_dt(data["updated_at"]),
            version=int(data.get("version", 1)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class SearchResult:
    """A single result returned by a semantic search or similarity query.

    Attributes:
        entry: The matched knowledge entry.
        score: Cosine similarity score in the range ``[0.0, 1.0]``.  Higher
            values indicate greater similarity.  For ``find_similar`` results
            this value exceeds the caller-supplied threshold.
    """

    entry: Entry
    score: float
