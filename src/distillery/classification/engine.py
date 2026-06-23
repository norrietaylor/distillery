"""Classification engine for Distillery.

This module provides :class:`ClassificationEngine`, which is responsible for:

1. Formatting prompts that describe a piece of content for an LLM to classify.
2. Parsing the structured JSON response returned by the LLM.
3. Applying confidence thresholding to decide the entry's lifecycle status.

The engine does *not* make any external API calls itself.  The ``/classify``
skill supplies the actual LLM inference and passes the raw LLM response string
to :meth:`ClassificationEngine.parse_response`.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from distillery.models import EntryStatus, EntryType

from .models import ClassificationResult

if TYPE_CHECKING:
    from distillery.config import ClassificationConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_KIND_VALUES: tuple[str, ...] = (
    "release",
    "reference",
    "howto",
    "opinion",
    "incident",
    "announcement",
    "discussion",
)
"""Allowed values for the ``kind`` axis (without the ``kind/`` prefix).

The ``kind/`` namespace is the *content-type* axis, orthogonal to the
``entry_type`` (the *artifact form*).  See issue #481 for rationale.
"""


_CLASSIFY_PROMPT = """\
You are a knowledge-base classifier.  Your task is to classify the following \
content and return a JSON object.

Pick exactly one *entry_type* (the artifact form):
- session: A captured work session or context snapshot (e.g. "explored auth module").
- bookmark: A saved URL or external reference.
- minutes: Notes from a meeting or discussion.
- meeting: A structured meeting record with agenda, participants, and outcomes.
- reference: A reference document, code snippet, or factual note.
- idea: An idea, hypothesis, or open question.
- person: A profile or record about a specific person (team member, contributor, contact).
- project: A project or repository record with status and metadata.
- digest: A periodic digest or summary covering a date range.
- github: A GitHub artifact reference (issue, PR, discussion, or release).
- feed: An ambient feed item captured from a monitored source (RSS, GitHub, Hacker News).
- entity: A first-class graph node representing a recurring entity or concept (auto-created by promotion).
- inbox: Cannot be classified (use as a fallback).

Pick exactly one *kind* (the content-type axis, orthogonal to entry_type):
- release: product / version announcement, changelog, launch.
- reference: spec, RFC, doc, paper, persistent factual artifact.
- howto: tutorial, guide, walkthrough.
- opinion: essay, hot-take, position piece, retrospective.
- incident: outage, postmortem, security advisory.
- announcement: hire, funding, org news; non-product.
- discussion: thread, forum, comment-driven (HN/Reddit/Lobsters submissions \
when not classifiable as above).

Content to classify:
\"\"\"
{content}
\"\"\"

Respond with ONLY valid JSON in this exact format:
{{
  "entry_type": "<one of the entry_type categories above>",
  "kind": "<one of: release|reference|howto|opinion|incident|announcement|discussion>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<brief explanation>",
  "suggested_tags": ["<tag1>", "<tag2>"],
  "suggested_project": "<project name or null>"
}}
"""


# ---------------------------------------------------------------------------
# ClassificationEngine
# ---------------------------------------------------------------------------


class ClassificationEngine:
    """Format classification prompts and parse LLM responses.

    Parameters
    ----------
    config:
        A :class:`~distillery.config.ClassificationConfig` instance that
        supplies ``confidence_threshold``.

    Example::

        from distillery.classification import ClassificationEngine
        from distillery.config import ClassificationConfig

        engine = ClassificationEngine(ClassificationConfig(confidence_threshold=0.6))
        prompt = engine.build_prompt("Explored auth module, tried OAuth2 flow")
        # ... send prompt to LLM ...
        result = engine.parse_response(llm_output)
    """

    def __init__(self, config: ClassificationConfig) -> None:
        self._confidence_threshold = config.confidence_threshold

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def build_prompt(self, content: str) -> str:
        """Return an LLM prompt for classifying *content*.

        Args:
            content: The raw text of the knowledge entry to classify.

        Returns:
            A ready-to-send prompt string.
        """
        return _CLASSIFY_PROMPT.format(content=content)

    def parse_response(self, llm_response: str) -> ClassificationResult:
        """Parse a structured JSON response from the LLM.

        Extracts ``entry_type``, ``confidence``, ``reasoning``,
        ``suggested_tags``, and ``suggested_project`` from the JSON payload.
        If parsing fails for any reason the method returns a safe fallback
        result with ``entry_type=inbox``, ``confidence=0.0``, and
        ``status=pending_review``.

        Args:
            llm_response: The raw string returned by the LLM.

        Returns:
            A :class:`~distillery.classification.models.ClassificationResult`
            with parsed or fallback values.
        """
        try:
            return self._parse(llm_response)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ClassificationEngine: failed to parse LLM response: %s", exc)
            return self._fallback()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse(self, llm_response: str) -> ClassificationResult:
        """Attempt to parse *llm_response* as JSON and extract fields."""
        # Strip markdown code fences if the LLM wrapped the JSON.
        text = llm_response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            # Drop first line (``` or ```json) and last line (```)
            text = "\n".join(lines[1:-1]).strip()

        data: dict[str, Any] = json.loads(text)

        raw_type = str(data["entry_type"]).lower().strip()
        try:
            entry_type = EntryType(raw_type)
        except ValueError:
            logger.warning("ClassificationEngine: unknown entry_type %r, using inbox", raw_type)
            entry_type = EntryType.INBOX

        confidence = float(data["confidence"])
        confidence = max(0.0, min(1.0, confidence))

        reasoning = str(data.get("reasoning", ""))

        raw_tags = data.get("suggested_tags", [])
        suggested_tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []

        raw_project = data.get("suggested_project")
        suggested_project = str(raw_project) if raw_project else None

        # Parse the ``kind`` axis.  Strict: only known values are accepted.
        # Unknown / missing values yield ``suggested_kind=None`` and no tag.
        suggested_kind: str | None = None
        raw_kind = data.get("kind")
        if isinstance(raw_kind, str):
            normalised = raw_kind.lower().strip()
            # Tolerate values the LLM may emit with the prefix already attached.
            if normalised.startswith("kind/"):
                normalised = normalised[len("kind/") :]
            if normalised in _KIND_VALUES:
                suggested_kind = normalised
            elif normalised:
                logger.warning("ClassificationEngine: unknown kind %r, dropping", raw_kind)

        # Canonicalize the ``kind/`` axis: keep at most one ``kind/<value>`` tag,
        # always sourced from the dedicated ``kind`` field.  Strip any pre-existing
        # ``kind/*`` entries from suggested_tags (case-insensitive) to avoid
        # conflicting or duplicate kind tags, then append the canonical tag.
        suggested_tags = [
            tag for tag in suggested_tags if not tag.strip().lower().startswith("kind/")
        ]
        if suggested_kind is not None:
            suggested_tags.append(f"kind/{suggested_kind}")

        status = self._status_for(confidence)

        return ClassificationResult(
            entry_type=entry_type,
            confidence=confidence,
            status=status,
            reasoning=reasoning,
            suggested_tags=suggested_tags,
            suggested_project=suggested_project,
            suggested_kind=suggested_kind,
        )

    def _fallback(self) -> ClassificationResult:
        """Return a safe fallback result used when parsing fails."""
        return ClassificationResult(
            entry_type=EntryType.INBOX,
            confidence=0.0,
            status=EntryStatus.PENDING_REVIEW,
            reasoning="",
            suggested_tags=[],
            suggested_project=None,
            suggested_kind=None,
        )

    def _status_for(self, confidence: float) -> EntryStatus:
        """Map a confidence score to an :class:`~distillery.models.EntryStatus`.

        Args:
            confidence: Confidence score in ``[0.0, 1.0]``.

        Returns:
            ``ACTIVE`` when *confidence* meets or exceeds
            ``confidence_threshold``; ``PENDING_REVIEW`` otherwise.
        """
        if confidence >= self._confidence_threshold:
            return EntryStatus.ACTIVE
        return EntryStatus.PENDING_REVIEW
