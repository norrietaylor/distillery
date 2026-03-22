"""Data models for the classification and deduplication subsystem.

This module defines the result dataclasses and action enum used by
:class:`~distillery.classification.engine.ClassificationEngine` and
:class:`~distillery.classification.dedup.DeduplicationChecker`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from distillery.models import EntryStatus, EntryType
    from distillery.store.protocol import SearchResult


class DeduplicationAction(str, Enum):
    """The action a caller should take after a deduplication check.

    Attributes:
        SKIP: The content is an exact (or near-exact) duplicate of an existing
            entry.  The caller should discard the new content and return the
            existing entry's ID.
        MERGE: The content is very similar to an existing entry and should be
            merged with it (e.g. append new details to the existing record).
        LINK: The content is related to an existing entry but distinct enough
            to create a new entry; the new entry should reference the similar
            one(s).
        CREATE: No sufficiently similar entry exists -- the caller should create
            a new entry without linking.
    """

    SKIP = "skip"
    MERGE = "merge"
    LINK = "link"
    CREATE = "create"


@dataclass
class ClassificationResult:
    """The outcome of classifying a knowledge entry.

    Attributes:
        entry_type: Predicted semantic category (e.g. ``"session"``,
            ``"bookmark"``).  Falls back to ``"inbox"`` on parse failure.
        confidence: Model's confidence in the predicted category, in
            ``[0.0, 1.0]``.  Set to ``0.0`` on parse failure.
        status: Suggested lifecycle state.  ``"active"`` when confidence
            meets or exceeds the configured threshold; ``"pending_review"``
            otherwise.
        reasoning: Human-readable explanation from the LLM.  May be empty
            on parse failure.
        suggested_tags: Suggested string labels for the entry.
        suggested_project: Optional project name extracted from content.
    """

    entry_type: "EntryType"
    confidence: float
    status: "EntryStatus"
    reasoning: str = ""
    suggested_tags: list[str] = field(default_factory=list)
    suggested_project: str | None = None


@dataclass
class DeduplicationResult:
    """The outcome of a deduplication check.

    Attributes:
        action: The recommended action the caller should take.
        similar_entries: Similar entries found by the store (may be empty
            when *action* is ``CREATE``).
        highest_score: The cosine similarity score of the most similar entry,
            or ``0.0`` if no similar entries were found.
        reasoning: Human-readable explanation of why the action was chosen.
    """

    action: DeduplicationAction
    similar_entries: list["SearchResult"] = field(default_factory=list)
    highest_score: float = 0.0
    reasoning: str = ""
