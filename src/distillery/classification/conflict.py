"""Conflict checker for Distillery.

This module provides :class:`ConflictChecker`, which detects whether new
content contradicts existing entries in the knowledge base.

The checker uses
:meth:`~distillery.store.protocol.DistilleryStore.find_similar` to retrieve
semantically similar entries and then delegates contradiction analysis to an
LLM via a prompt/response pattern -- the same architecture used by
:class:`~distillery.classification.engine.ClassificationEngine`.

The checker does *not* make any external API calls itself.  The MCP handler
builds the prompts, invokes the LLM for each candidate pair, then passes the
responses back to :meth:`ConflictChecker.check`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from distillery.store.protocol import DistilleryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_CONFLICT_PROMPT = """\
You are a knowledge-base conflict detector.  Your task is to decide whether \
two pieces of content contradict each other and return a JSON object.

A contradiction occurs when the two pieces of content make mutually exclusive \
claims about the same subject.  Merely discussing the same topic without \
disagreement is NOT a contradiction.

Existing entry:
\"\"\"
{existing_content}
\"\"\"

New entry:
\"\"\"
{new_content}
\"\"\"

Respond with ONLY valid JSON in this exact format:
{{
  "is_conflict": <true or false>,
  "reasoning": "<brief explanation of why the content does or does not contradict>"
}}
"""

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ConflictEntry:
    """A single conflicting entry detected by :class:`ConflictChecker`.

    Attributes:
        entry_id: The ID of the existing knowledge-base entry that conflicts
            with the new content.
        content_preview: A short preview of the conflicting entry's content
            (first line, up to 120 characters).
        similarity_score: The cosine similarity score between the new content
            and this entry, in ``[0.0, 1.0]``.
        conflict_reasoning: Human-readable explanation from the LLM describing
            why the two pieces of content contradict each other.
    """

    entry_id: str
    content_preview: str
    similarity_score: float
    conflict_reasoning: str


@dataclass
class ConflictResult:
    """The outcome of a conflict-detection check.

    Attributes:
        has_conflicts: ``True`` when at least one conflicting entry was found.
        conflicts: List of :class:`ConflictEntry` objects describing each
            detected conflict.  Empty when *has_conflicts* is ``False``.
    """

    has_conflicts: bool
    conflicts: list[ConflictEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ConflictChecker
# ---------------------------------------------------------------------------

_DEFAULT_CONFLICT_THRESHOLD: float = 0.60
_DEFAULT_CONFLICT_LIMIT: int = 5


class ConflictChecker:
    """Detect whether new content contradicts entries already in the store.

    The checker retrieves semantically similar entries via
    :meth:`~distillery.store.protocol.DistilleryStore.find_similar` and uses
    LLM-evaluated prompts to determine whether any of those entries
    contradict the new content.

    Because the checker does not call the LLM directly, callers must supply
    the LLM responses via the *llm_responses* argument of :meth:`check`.  The
    typical workflow is:

    1. Instantiate :class:`ConflictChecker`.
    2. Call :meth:`check` with ``llm_responses=None`` to discover which
       candidate pairs need LLM evaluation and obtain their prompts via
       :meth:`build_prompt`.
    3. Invoke the LLM for each prompt and collect the raw response strings.
    4. Call :meth:`check` again, passing the collected responses as
       *llm_responses*.

    Parameters
    ----------
    store:
        A :class:`~distillery.store.protocol.DistilleryStore` instance used
        to call :meth:`find_similar`.
    threshold:
        Minimum cosine similarity (inclusive) for a stored entry to be
        considered a conflict candidate.  Default ``0.60``.

    Example::

        from distillery.classification import ConflictChecker

        checker = ConflictChecker(store=my_store)
        # First pass: discover candidate entry IDs and build prompts
        result = await checker.check("Python 3 is recommended")
        # result.has_conflicts is False here (no llm_responses supplied yet)

        # Build prompts and call the LLM for each candidate
        # (application-specific LLM call omitted)

        # Second pass: supply LLM responses
        result = await checker.check(
            "Python 3 is recommended",
            llm_responses={"entry-id-1": (True, "Contradicts Python 2 claim")},
        )
        if result.has_conflicts:
            for conflict in result.conflicts:
                print(conflict.entry_id, conflict.conflict_reasoning)
    """

    def __init__(
        self,
        store: DistilleryStore,
        threshold: float = _DEFAULT_CONFLICT_THRESHOLD,
    ) -> None:
        self._store = store
        self._threshold = threshold

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def build_prompt(self, new_content: str, existing_content: str) -> str:
        """Return an LLM prompt that asks whether *new_content* contradicts
        *existing_content*.

        Args:
            new_content: The raw text of the candidate new entry.
            existing_content: The raw text of the existing knowledge-base
                entry to compare against.

        Returns:
            A ready-to-send prompt string following the same template
            convention as
            :data:`~distillery.classification.engine._CLASSIFY_PROMPT`.
        """
        return _CONFLICT_PROMPT.format(
            new_content=new_content,
            existing_content=existing_content,
        )

    def parse_response(self, llm_response: str) -> tuple[bool, str]:
        """Parse a structured JSON response from the LLM.

        Extracts ``is_conflict`` (bool) and ``reasoning`` (str) from the
        JSON payload.  If parsing fails for any reason the method returns a
        safe fallback of ``(False, "")``.

        Args:
            llm_response: The raw string returned by the LLM.

        Returns:
            A ``(is_conflict, reasoning)`` tuple where *is_conflict* is
            ``True`` when the LLM determined the two entries contradict each
            other.
        """
        try:
            return self._parse(llm_response)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ConflictChecker: failed to parse LLM response: %s", exc)
            return False, ""

    async def check(
        self,
        content: str,
        llm_responses: dict[str, tuple[bool, str]] | None = None,
    ) -> ConflictResult:
        """Evaluate *content* for conflicts against the existing knowledge base.

        Calls :meth:`~distillery.store.protocol.DistilleryStore.find_similar`
        to retrieve candidate entries at or above *threshold*.  If
        *llm_responses* are provided, each ``(is_conflict, reasoning)`` pair
        is used to decide whether the corresponding entry is a conflict.
        Entries without a corresponding *llm_responses* entry are omitted
        from the result (they need LLM evaluation first).

        Args:
            content: The raw text of the candidate new entry.
            llm_responses: Optional mapping from ``entry_id`` to the parsed
                LLM result ``(is_conflict, reasoning)``.  When ``None``, the
                method still queries the store for similar entries but returns
                an empty conflict list (caller needs to collect LLM responses
                first).

        Returns:
            A :class:`ConflictResult` describing any detected conflicts.
        """
        similar = await self._store.find_similar(
            content=content,
            threshold=self._threshold,
            limit=_DEFAULT_CONFLICT_LIMIT,
        )

        if not similar:
            return ConflictResult(has_conflicts=False, conflicts=[])

        if llm_responses is None:
            return ConflictResult(has_conflicts=False, conflicts=[])

        conflicts: list[ConflictEntry] = []
        for result in similar:
            entry_id = result.entry.id
            if entry_id not in llm_responses:
                # LLM has not evaluated this pair yet; skip it.
                continue
            is_conflict, reasoning = llm_responses[entry_id]
            if not is_conflict:
                continue
            lines = result.entry.content.splitlines()
            preview = lines[0][:120] if lines else result.entry.content[:120]
            conflicts.append(
                ConflictEntry(
                    entry_id=entry_id,
                    content_preview=preview,
                    similarity_score=result.score,
                    conflict_reasoning=reasoning,
                )
            )

        return ConflictResult(has_conflicts=bool(conflicts), conflicts=conflicts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse(self, llm_response: str) -> tuple[bool, str]:
        """Attempt to parse *llm_response* as JSON and extract fields."""
        import json
        import re

        text = llm_response.strip()
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

        data: dict[str, Any] = json.loads(text)

        is_conflict = bool(data["is_conflict"])
        reasoning = str(data.get("reasoning", ""))
        return is_conflict, reasoning
