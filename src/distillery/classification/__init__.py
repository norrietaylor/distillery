"""Classification and deduplication subsystem for Distillery.

This package provides:

- :class:`~distillery.classification.engine.ClassificationEngine` -- formats
  LLM prompts and parses structured JSON classification responses.
- :class:`~distillery.classification.dedup.DeduplicationChecker` -- uses
  ``DistilleryStore.find_similar()`` to detect near-duplicate content.
- :class:`~distillery.classification.conflict.ConflictChecker` -- uses
  ``DistilleryStore.find_similar()`` and LLM responses to detect contradictions.
- :class:`~distillery.classification.models.ClassificationResult` -- result
  dataclass returned by :class:`ClassificationEngine`.
- :class:`~distillery.classification.models.DeduplicationResult` -- result
  dataclass returned by :class:`DeduplicationChecker`.
- :class:`~distillery.classification.models.DeduplicationAction` -- enum of
  recommended actions (``skip``, ``merge``, ``link``, ``create``).
- :class:`~distillery.classification.conflict.ConflictResult` -- result
  dataclass returned by :class:`ConflictChecker`.
- :class:`~distillery.classification.conflict.ConflictEntry` -- a single
  conflicting entry detected by :class:`ConflictChecker`.

Quick start::

    from distillery.classification import (
        ClassificationEngine,
        ClassificationResult,
        ConflictChecker,
        ConflictEntry,
        ConflictResult,
        DeduplicationAction,
        DeduplicationChecker,
        DeduplicationResult,
    )
    from distillery.config import ClassificationConfig

    engine = ClassificationEngine(ClassificationConfig())
    prompt = engine.build_prompt("Explored auth module, tried OAuth2 flow")
    # ... invoke LLM with prompt ...
    result: ClassificationResult = engine.parse_response(llm_output)
"""

from __future__ import annotations

from .conflict import ConflictChecker, ConflictEntry, ConflictResult
from .dedup import DeduplicationChecker
from .engine import ClassificationEngine
from .models import ClassificationResult, DeduplicationAction, DeduplicationResult

__all__ = [
    "ClassificationEngine",
    "ClassificationResult",
    "ConflictChecker",
    "ConflictEntry",
    "ConflictResult",
    "DeduplicationAction",
    "DeduplicationChecker",
    "DeduplicationResult",
]
