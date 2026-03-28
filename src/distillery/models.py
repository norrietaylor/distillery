"""Data models for Distillery.

This module defines the canonical ``Entry`` dataclass used throughout the
Distillery system, along with its associated enums and the ``SearchResult``
dataclass returned by semantic search operations.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EntryType(StrEnum):
    """The semantic category of a knowledge entry.

    Attributes:
        SESSION: A captured work session or context snapshot.
        BOOKMARK: A saved URL or external reference.
        MINUTES: Notes from a meeting or discussion.
        MEETING: A meeting record (agenda, participants, outcomes).
        REFERENCE: A reference document, snippet, or fact.
        IDEA: An idea, hypothesis, or open question.
        INBOX: An unsorted entry awaiting classification.
        PERSON: A person profile entry (team member, contributor, contact).
        PROJECT: A project or repository record.
        DIGEST: A periodic digest or summary covering a date range.
        GITHUB: A GitHub artifact reference (issue, PR, discussion, release).
    """

    SESSION = "session"
    BOOKMARK = "bookmark"
    MINUTES = "minutes"
    MEETING = "meeting"
    REFERENCE = "reference"
    IDEA = "idea"
    INBOX = "inbox"
    PERSON = "person"
    PROJECT = "project"
    DIGEST = "digest"
    GITHUB = "github"


class EntrySource(StrEnum):
    """The origin of an entry in the system.

    Attributes:
        CLAUDE_CODE: Created by a Claude Code skill (e.g. ``/distill``).
        MANUAL: Created directly by a human operator.
        IMPORT: Bulk-imported from an external source.
    """

    CLAUDE_CODE = "claude-code"
    MANUAL = "manual"
    IMPORT = "import"


class EntryStatus(StrEnum):
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
    return datetime.now(tz=UTC)


def _new_uuid() -> str:
    """Return a new UUID4 as a string."""
    return str(uuid.uuid4())


_TAG_SEGMENT_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


def validate_tag(tag: str) -> None:
    """Validate a single tag string.

    Tags must be non-empty lowercase alphanumeric slugs, optionally joined by
    forward slashes to form a hierarchical namespace.  Each slash-separated
    segment must match ``[a-z0-9][a-z0-9\\-]*`` (starts with a letter or digit,
    may contain hyphens, no uppercase, no underscores, no consecutive or
    trailing slashes).

    Valid examples::

        "meeting-notes"
        "project/billing-v2/decisions"
        "team/backend"

    Invalid examples::

        "Project/Billing"   # uppercase not allowed
        "project/billing/"  # trailing slash
        "project//billing"  # empty segment

    Raises:
        ValueError: If the tag is empty, contains uppercase characters, has a
            trailing slash, or contains any empty segment.
    """
    if not tag:
        raise ValueError("Tag must not be empty.")
    segments = tag.split("/")
    for segment in segments:
        if not segment:
            raise ValueError(
                f"Tag {tag!r} is invalid: each slash-separated segment must be non-empty "
                "(no leading, trailing, or consecutive slashes)."
            )
        if not _TAG_SEGMENT_RE.match(segment):
            raise ValueError(
                f"Tag {tag!r} is invalid: segment {segment!r} must match "
                "[a-z0-9][a-z0-9-]* (lowercase alphanumeric plus hyphens only)."
            )


# ---------------------------------------------------------------------------
# Metadata schemas
# ---------------------------------------------------------------------------

#: Registry mapping each entry type that has structured metadata requirements
#: to a schema dict describing its ``required`` and ``optional`` fields.
#: Types not listed here (e.g. ``session``, ``bookmark``) accept any metadata.
TYPE_METADATA_SCHEMAS: dict[str, dict[str, Any]] = {
    "person": {
        "required": {
            "expertise": "list[str]",
        },
        "optional": {
            "github_username": "str",
            "team": "str",
            "role": "str",
            "email": "str",
        },
    },
    "project": {
        "required": {
            "repo": "str",
        },
        "optional": {
            "status": "str",
            "language": "str",
            "description": "str",
        },
    },
    "digest": {
        "required": {
            "period_start": "str",
            "period_end": "str",
        },
        "optional": {
            "sources": "list[str]",
            "summary": "str",
        },
    },
    "github": {
        "required": {
            "repo": "str",
            "ref_type": "str",
            "ref_number": "int",
        },
        "optional": {
            "title": "str",
            "url": "str",
            "state": "str",
        },
        "constraints": {
            "ref_type": ["issue", "pr", "discussion", "release"],
        },
    },
}


def validate_metadata(entry_type: str, metadata: dict[str, Any]) -> None:
    """Validate *metadata* against the schema for *entry_type*.

    For entry types not listed in :data:`TYPE_METADATA_SCHEMAS` this is a
    no-op -- legacy types accept arbitrary metadata.

    Args:
        entry_type: The string value of the entry type (e.g. ``"person"``).
        metadata: The metadata dict to validate.

    Raises:
        ValueError: If a required field is missing or a constrained field
            contains an invalid value.
    """
    schema = TYPE_METADATA_SCHEMAS.get(entry_type)
    if schema is None:
        return  # No schema for this type -- anything is valid.

    required_fields: dict[str, str] = schema.get("required", {})
    constraints: dict[str, list[str]] = schema.get("constraints", {})

    # Check required fields are present.
    for field_name in required_fields:
        if field_name not in metadata:
            raise ValueError(
                f"Metadata for entry_type={entry_type!r} is missing required field "
                f"{field_name!r} (type: {required_fields[field_name]})."
            )

    # Check field-level constraints (e.g. enum-like allowed values).
    for field_name, allowed_values in constraints.items():
        if field_name in metadata and metadata[field_name] not in allowed_values:
            raise ValueError(
                f"Metadata field {field_name!r} for entry_type={entry_type!r} "
                f"must be one of {', '.join(repr(v) for v in allowed_values)}; "
                f"got {metadata[field_name]!r}."
            )


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
    metadata: dict[str, Any] = field(default_factory=dict)
    accessed_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate all tags on construction.

        Raises:
            ValueError: If any tag in ``self.tags`` fails :func:`validate_tag`.
        """
        for tag in self.tags:
            validate_tag(tag)

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize this entry to a JSON-compatible flat dictionary.

        Enum fields (`entry_type`, `source`, `status`) are stored as their string values. Datetime fields (`created_at`, `updated_at`, `accessed_at`) are stored as ISO 8601 strings with UTC offset; `accessed_at` is `None` if unset. `tags` and `metadata` are shallow copies to avoid mutating internal state.

        Returns:
            dict: A flat dictionary suitable for JSON or YAML serialization.
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
            "accessed_at": self.accessed_at.isoformat() if self.accessed_at is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entry:
        """
        Create an Entry instance from a dictionary representation.

        Parameters:
            data (dict[str, Any]): Dictionary containing entry fields. Enum fields
                (`entry_type`, `source`, `status`) may be provided as enum members or
                their string values. Datetime fields (`created_at`, `updated_at`,
                `accessed_at`) may be ISO 8601 strings or datetime objects; naive
                datetimes are treated as UTC.

        Returns:
            Entry: A fully initialized Entry instance.

        Raises:
            KeyError: If a required key (e.g., `id`, `content`, `entry_type`,
                `source`, `created_at`, `updated_at`, `author`) is missing.
            ValueError: If a provided string does not match a valid enum member.
        """

        def _parse_dt(value: str | datetime) -> datetime:
            """
            Parse an ISO 8601 datetime string or return the given datetime, ensuring the result is timezone-aware (UTC if no timezone is present).

            Parameters:
                value (str | datetime): An ISO 8601 datetime string or a datetime object.

            Returns:
                datetime: A timezone-aware datetime; if `value` was a naive datetime or a string without timezone, the returned datetime will have its timezone set to UTC.
            """
            if isinstance(value, datetime):
                return value
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt

        accessed_at_raw = data.get("accessed_at")
        accessed_at = _parse_dt(accessed_at_raw) if accessed_at_raw is not None else None

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
            accessed_at=accessed_at,
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
