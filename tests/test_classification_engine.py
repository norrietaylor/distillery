"""Tests for ClassificationEngine -- prompt building and response parsing.

All tests use mocked LLM responses (plain strings) to avoid any external
API calls.  The engine's job is purely to format prompts and parse JSON.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from distillery.classification import ClassificationEngine, ClassificationResult
from distillery.config import ClassificationConfig
from distillery.models import EntryStatus, EntryType

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(threshold: float = 0.6) -> ClassificationEngine:
    """Return a ClassificationEngine with the given confidence threshold."""
    return ClassificationEngine(ClassificationConfig(confidence_threshold=threshold))


def _json_response(
    entry_type: str,
    confidence: float,
    reasoning: str = "Test reasoning.",
    suggested_tags: list[str] | None = None,
    suggested_project: str | None = None,
    kind: str | None = "reference",
    *,
    omit_kind: bool = False,
) -> str:
    """Build a well-formed JSON response string as if from an LLM.

    Args:
        kind: Value for the ``kind`` field.  Defaults to ``"reference"`` so
            existing tests that don't care about the axis still produce a
            well-formed payload.  Set ``omit_kind=True`` to drop the field
            entirely (back-compat / unknown-LLM responses).
    """
    payload: dict[str, Any] = {
        "entry_type": entry_type,
        "confidence": confidence,
        "reasoning": reasoning,
        "suggested_tags": suggested_tags or [],
        "suggested_project": suggested_project,
    }
    if not omit_kind:
        payload["kind"] = kind
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Classification by entry type
# ---------------------------------------------------------------------------


class TestClassificationByType:
    """Engine correctly classifies each valid entry type."""

    @pytest.mark.parametrize(
        "entry_type_str, entry_type_enum",
        [
            ("session", EntryType.SESSION),
            ("bookmark", EntryType.BOOKMARK),
            ("minutes", EntryType.MINUTES),
            ("meeting", EntryType.MEETING),
            ("reference", EntryType.REFERENCE),
            ("idea", EntryType.IDEA),
            ("inbox", EntryType.INBOX),
        ],
    )
    def test_classifies_each_entry_type(
        self, entry_type_str: str, entry_type_enum: EntryType
    ) -> None:
        engine = _make_engine()
        response = _json_response(entry_type_str, 0.85, "Some reasoning.")
        result = engine.parse_response(response)

        assert result.entry_type == entry_type_enum
        assert result.confidence == pytest.approx(0.85)

    def test_session_entry_type_with_high_confidence(self) -> None:
        engine = _make_engine()
        response = _json_response(
            "session",
            0.85,
            "The content describes a work session.",
            suggested_tags=["auth", "oauth2"],
        )
        result = engine.parse_response(response)

        assert result.entry_type == EntryType.SESSION
        assert result.confidence == pytest.approx(0.85)
        assert result.reasoning != ""
        assert len(result.suggested_tags) > 0

    def test_bookmark_entry_type(self) -> None:
        engine = _make_engine()
        response = _json_response("bookmark", 0.92, "URL reference detected.")
        result = engine.parse_response(response)

        assert result.entry_type == EntryType.BOOKMARK
        assert result.confidence == pytest.approx(0.92)

    def test_meeting_entry_type(self) -> None:
        engine = _make_engine()
        response = _json_response("meeting", 0.78, "Sprint planning mentioned.")
        result = engine.parse_response(response)

        assert result.entry_type == EntryType.MEETING
        assert result.confidence == pytest.approx(0.78)


# ---------------------------------------------------------------------------
# Confidence thresholding
# ---------------------------------------------------------------------------


class TestConfidenceThresholding:
    """Status is set correctly based on confidence vs threshold."""

    def test_below_threshold_sets_pending_review(self) -> None:
        engine = _make_engine(threshold=0.6)
        response = _json_response("idea", 0.45)
        result = engine.parse_response(response)

        assert result.status == EntryStatus.PENDING_REVIEW
        assert result.confidence == pytest.approx(0.45)

    def test_at_threshold_sets_active(self) -> None:
        engine = _make_engine(threshold=0.6)
        response = _json_response("reference", 0.6)
        result = engine.parse_response(response)

        assert result.status == EntryStatus.ACTIVE
        assert result.confidence == pytest.approx(0.6)

    def test_above_threshold_sets_active(self) -> None:
        engine = _make_engine(threshold=0.6)
        response = _json_response("reference", 0.88)
        result = engine.parse_response(response)

        assert result.status == EntryStatus.ACTIVE

    def test_high_threshold_with_medium_confidence_sets_pending(self) -> None:
        engine = _make_engine(threshold=0.9)
        response = _json_response("session", 0.85)
        result = engine.parse_response(response)

        assert result.status == EntryStatus.PENDING_REVIEW

    def test_low_threshold_with_low_confidence_sets_active(self) -> None:
        engine = _make_engine(threshold=0.2)
        response = _json_response("idea", 0.3)
        result = engine.parse_response(response)

        assert result.status == EntryStatus.ACTIVE


# ---------------------------------------------------------------------------
# Parse failure / graceful fallback
# ---------------------------------------------------------------------------


class TestParseFailure:
    """Engine falls back gracefully on malformed LLM output."""

    def test_malformed_non_json_returns_inbox_fallback(self) -> None:
        engine = _make_engine()
        result = engine.parse_response("Sorry, I cannot classify this content.")

        assert result.entry_type == EntryType.INBOX
        assert result.confidence == pytest.approx(0.0)
        assert result.status == EntryStatus.PENDING_REVIEW

    def test_empty_string_returns_fallback(self) -> None:
        engine = _make_engine()
        result = engine.parse_response("")

        assert result.entry_type == EntryType.INBOX
        assert result.confidence == pytest.approx(0.0)
        assert result.status == EntryStatus.PENDING_REVIEW

    def test_json_missing_entry_type_returns_fallback(self) -> None:
        engine = _make_engine()
        result = engine.parse_response('{"confidence": 0.9}')

        assert result.entry_type == EntryType.INBOX
        assert result.confidence == pytest.approx(0.0)

    def test_json_missing_confidence_returns_fallback(self) -> None:
        engine = _make_engine()
        result = engine.parse_response('{"entry_type": "session"}')

        assert result.entry_type == EntryType.INBOX
        assert result.confidence == pytest.approx(0.0)

    def test_unknown_entry_type_defaults_to_inbox(self) -> None:
        engine = _make_engine()
        response = _json_response("unknown_type_xyz", 0.85)
        result = engine.parse_response(response)

        assert result.entry_type == EntryType.INBOX

    def test_markdown_code_fence_stripped_correctly(self) -> None:
        engine = _make_engine()
        raw_json = _json_response("session", 0.9)
        wrapped = f"```json\n{raw_json}\n```"
        result = engine.parse_response(wrapped)

        assert result.entry_type == EntryType.SESSION
        assert result.confidence == pytest.approx(0.9)

    def test_code_fence_without_language_stripped(self) -> None:
        engine = _make_engine()
        raw_json = _json_response("bookmark", 0.75)
        wrapped = f"```\n{raw_json}\n```"
        result = engine.parse_response(wrapped)

        assert result.entry_type == EntryType.BOOKMARK


# ---------------------------------------------------------------------------
# Optional fields
# ---------------------------------------------------------------------------


class TestOptionalFields:
    """Suggested project and tags are correctly extracted."""

    def test_suggested_project_extracted(self) -> None:
        engine = _make_engine()
        response = _json_response("session", 0.88, "Billing work.", suggested_project="billing-v2")
        result = engine.parse_response(response)

        assert result.suggested_project == "billing-v2"

    def test_null_suggested_project_is_none(self) -> None:
        engine = _make_engine()
        response = _json_response("session", 0.88, "No project mentioned.")
        result = engine.parse_response(response)

        assert result.suggested_project is None

    def test_suggested_tags_extracted(self) -> None:
        engine = _make_engine()
        response = _json_response(
            "session",
            0.88,
            "Auth work.",
            suggested_tags=["auth", "oauth2", "security"],
            omit_kind=True,
        )
        result = engine.parse_response(response)

        assert "auth" in result.suggested_tags
        assert "oauth2" in result.suggested_tags
        assert len(result.suggested_tags) == 3

    def test_empty_suggested_tags_is_empty_list(self) -> None:
        engine = _make_engine()
        response = _json_response("session", 0.88, omit_kind=True)
        result = engine.parse_response(response)

        assert result.suggested_tags == []

    def test_reasoning_is_populated(self) -> None:
        engine = _make_engine()
        response = _json_response("session", 0.85, "Clear session description.")
        result = engine.parse_response(response)

        assert result.reasoning == "Clear session description."


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestPromptBuilding:
    """build_prompt returns a non-empty string containing the content."""

    def test_prompt_contains_content(self) -> None:
        engine = _make_engine()
        content = "Explored auth module, tried OAuth2 flow"
        prompt = engine.build_prompt(content)

        assert content in prompt
        assert len(prompt) > len(content)

    def test_prompt_lists_classifier_entry_types(self) -> None:
        engine = _make_engine()
        prompt = engine.build_prompt("anything")

        # ``entity`` is an auto-promotion-only node type that requires
        # ``canonical_name``/``source_tag`` metadata the classifier cannot
        # produce, so it is deliberately excluded from classifier choices.
        for et in EntryType:
            if et is EntryType.ENTITY:
                assert et.value not in prompt
            else:
                assert et.value in prompt

    def test_prompt_requests_json_format(self) -> None:
        engine = _make_engine()
        prompt = engine.build_prompt("anything")

        assert "JSON" in prompt or "json" in prompt


# ---------------------------------------------------------------------------
# kind/ axis (issue #481)
# ---------------------------------------------------------------------------


class TestKindAxis:
    """The classifier emits a single ``kind/<value>`` tag per entry."""

    @pytest.mark.parametrize(
        "kind_value",
        [
            "release",
            "reference",
            "howto",
            "opinion",
            "incident",
            "announcement",
            "discussion",
        ],
    )
    def test_each_kind_round_trips(self, kind_value: str) -> None:
        engine = _make_engine()
        response = _json_response("feed", 0.85, kind=kind_value)
        result = engine.parse_response(response)

        assert result.suggested_kind == kind_value
        assert f"kind/{kind_value}" in result.suggested_tags

    def test_kind_tag_is_de_duplicated_against_suggested_tags(self) -> None:
        """If the LLM also lists the kind tag explicitly, it must not duplicate."""
        engine = _make_engine()
        response = _json_response(
            "feed",
            0.9,
            suggested_tags=["domain/api", "kind/opinion"],
            kind="opinion",
        )
        result = engine.parse_response(response)

        assert result.suggested_kind == "opinion"
        # Exactly one kind/opinion entry, even though the LLM listed it twice.
        assert result.suggested_tags.count("kind/opinion") == 1

    def test_conflicting_kind_in_suggested_tags_is_replaced_by_canonical_kind(self) -> None:
        """Canonical ``kind`` field wins; conflicting kind/* in suggested_tags is dropped."""
        engine = _make_engine()
        response = _json_response(
            "feed",
            0.9,
            suggested_tags=["domain/api", "kind/opinion"],
            kind="release",
        )
        result = engine.parse_response(response)

        assert result.suggested_kind == "release"
        # Only the canonical kind tag remains; the stale kind/opinion is stripped.
        kind_tags = [t for t in result.suggested_tags if t.lower().startswith("kind/")]
        assert kind_tags == ["kind/release"]
        assert "domain/api" in result.suggested_tags

    def test_unknown_kind_yields_none_and_no_tag(self) -> None:
        engine = _make_engine()
        response = _json_response("feed", 0.8, kind="bogus-kind")
        result = engine.parse_response(response)

        assert result.suggested_kind is None
        assert not any(t.startswith("kind/") for t in result.suggested_tags)

    def test_missing_kind_yields_none_and_no_tag(self) -> None:
        engine = _make_engine()
        response = _json_response("feed", 0.8, omit_kind=True)
        result = engine.parse_response(response)

        assert result.suggested_kind is None
        assert not any(t.startswith("kind/") for t in result.suggested_tags)

    def test_kind_with_prefix_is_accepted(self) -> None:
        """LLMs sometimes emit ``kind/release``; strip the prefix gracefully."""
        engine = _make_engine()
        response = _json_response("feed", 0.8, kind="kind/release")
        result = engine.parse_response(response)

        assert result.suggested_kind == "release"
        assert "kind/release" in result.suggested_tags

    def test_kind_uppercase_normalised(self) -> None:
        engine = _make_engine()
        response = _json_response("feed", 0.8, kind="OPINION")
        result = engine.parse_response(response)

        assert result.suggested_kind == "opinion"
        assert "kind/opinion" in result.suggested_tags

    def test_fallback_result_has_no_kind(self) -> None:
        engine = _make_engine()
        result = engine.parse_response("not json")

        assert result.suggested_kind is None
        assert not any(tag.startswith("kind/") for tag in result.suggested_tags)


# ---------------------------------------------------------------------------
# Prompt contract (issue #481)
# ---------------------------------------------------------------------------


class TestPromptContract:
    """The classifier prompt must enumerate the ``kind`` axis enum."""

    def test_prompt_requires_kind_field(self) -> None:
        engine = _make_engine()
        prompt = engine.build_prompt("anything")

        assert '"kind"' in prompt

    @pytest.mark.parametrize(
        "kind_value",
        [
            "release",
            "reference",
            "howto",
            "opinion",
            "incident",
            "announcement",
            "discussion",
        ],
    )
    def test_prompt_lists_each_kind_value(self, kind_value: str) -> None:
        engine = _make_engine()
        prompt = engine.build_prompt("anything")

        assert kind_value in prompt

    def test_prompt_documents_pipe_separated_enum(self) -> None:
        """The contract line ``"kind": "<one of: release|...>"`` is present."""
        engine = _make_engine()
        prompt = engine.build_prompt("anything")

        # Anchor on the full enum string the LLM must respect.
        expected_enum = "release|reference|howto|opinion|incident|announcement|discussion"
        assert expected_enum in prompt


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class TestReturnType:
    """parse_response always returns a ClassificationResult."""

    def test_returns_classification_result_instance(self) -> None:
        engine = _make_engine()
        result = engine.parse_response(_json_response("session", 0.9))
        assert isinstance(result, ClassificationResult)

    def test_fallback_returns_classification_result_instance(self) -> None:
        engine = _make_engine()
        result = engine.parse_response("not json at all")
        assert isinstance(result, ClassificationResult)
