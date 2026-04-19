"""Unit tests for the entry_type alias / suggestion helpers (issue #345).

Covers :func:`distillery.mcp.tools.crud._suggest_entry_type` and the
:func:`distillery.mcp.tools.crud._invalid_entry_type_response` helper that
wraps it into a structured INVALID_PARAMS response.
"""

from __future__ import annotations

import json

import pytest

from distillery.mcp.tools.crud import (
    _ENTRY_TYPE_ALIASES,
    _VALID_ENTRY_TYPES,
    _invalid_entry_type_response,
    _suggest_entry_type,
)

pytestmark = pytest.mark.unit


class TestSuggestEntryType:
    """Tests for the pure alias-lookup helper."""

    def test_note_maps_to_inbox(self) -> None:
        """Issue #345: the canonical example — ``'note'`` resolves to ``'inbox'``."""
        assert _suggest_entry_type("note") == "inbox"

    def test_case_insensitive(self) -> None:
        """Aliases match case-insensitively."""
        assert _suggest_entry_type("Note") == "inbox"
        assert _suggest_entry_type("NOTE") == "inbox"
        assert _suggest_entry_type("NoTeS") == "inbox"

    def test_strips_whitespace(self) -> None:
        """Surrounding whitespace is trimmed before lookup."""
        assert _suggest_entry_type("  note  ") == "inbox"

    @pytest.mark.parametrize(
        "alias,expected",
        [
            ("task", "idea"),
            ("todo", "idea"),
            ("issue", "github"),
            ("pr", "github"),
            ("article", "bookmark"),
            ("url", "bookmark"),
            ("link", "bookmark"),
            ("summary", "digest"),
            ("doc", "reference"),
            ("docs", "reference"),
            ("contact", "person"),
            ("repo", "project"),
        ],
    )
    def test_covers_common_aliases(self, alias: str, expected: str) -> None:
        """Each alias resolves to a canonical entry_type."""
        assert _suggest_entry_type(alias) == expected

    def test_unknown_value_returns_none(self) -> None:
        """Unknown strings do not produce a suggestion."""
        assert _suggest_entry_type("completely_bogus") is None
        assert _suggest_entry_type("") is None

    def test_non_string_returns_none(self) -> None:
        """Non-string inputs cannot be aliases; return ``None`` rather than raising."""
        assert _suggest_entry_type(None) is None
        assert _suggest_entry_type(42) is None
        assert _suggest_entry_type(["note"]) is None

    def test_every_alias_target_is_canonical(self) -> None:
        """Every alias must point at a real canonical entry_type.

        Regression guard: if someone adds an alias pointing at a typo or a
        removed type, this test catches it immediately.
        """
        for alias, target in _ENTRY_TYPE_ALIASES.items():
            assert target in _VALID_ENTRY_TYPES, (
                f"alias {alias!r} targets {target!r} which is not in _VALID_ENTRY_TYPES"
            )

    def test_no_alias_is_itself_canonical(self) -> None:
        """An alias must not collide with a canonical type (would be dead code)."""
        for alias in _ENTRY_TYPE_ALIASES:
            assert alias not in _VALID_ENTRY_TYPES, (
                f"alias {alias!r} is already a canonical entry_type — remove it from the map"
            )


class TestInvalidEntryTypeResponse:
    """Tests for the structured INVALID_PARAMS response builder."""

    @staticmethod
    def _parse(response: list) -> dict:  # type: ignore[type-arg]
        assert len(response) == 1
        return json.loads(response[0].text)

    def test_basic_shape_with_suggestion(self) -> None:
        payload = self._parse(_invalid_entry_type_response("note"))
        assert payload["error"] is True
        assert payload["code"] == "INVALID_PARAMS"
        assert "note" in payload["message"]
        assert "inbox" in payload["message"]
        assert "Did you mean" in payload["message"]
        details = payload["details"]
        assert details["field"] == "entry_type"
        assert details["provided"] == "note"
        assert details["suggestion"] == "inbox"
        assert sorted(details["allowed"]) == sorted(_VALID_ENTRY_TYPES)

    def test_no_suggestion_for_unknown_value(self) -> None:
        payload = self._parse(_invalid_entry_type_response("bogus"))
        assert payload["code"] == "INVALID_PARAMS"
        # The message omits the "Did you mean" sentence entirely — no empty hint.
        assert "Did you mean" not in payload["message"]
        assert "suggestion" not in payload["details"]
        # But ``allowed`` is always surfaced so clients can recover without
        # reparsing the message string.
        assert "inbox" in payload["details"]["allowed"]

    def test_custom_field_label(self) -> None:
        """Reclassify path uses ``new_entry_type`` — that name must appear in both message and details."""
        payload = self._parse(_invalid_entry_type_response("note", field="new_entry_type"))
        assert "new_entry_type" in payload["message"]
        assert payload["details"]["field"] == "new_entry_type"
        assert payload["details"]["suggestion"] == "inbox"

    def test_message_prefix_for_batch_context(self) -> None:
        """Batch ingest uses a prefix so callers know which item failed."""
        payload = self._parse(_invalid_entry_type_response("note", prefix="entries[3] has "))
        assert payload["message"].startswith("entries[3] has Invalid entry_type")
        assert payload["details"]["suggestion"] == "inbox"

    def test_non_string_value_has_no_suggestion(self) -> None:
        """A non-string rejected value still produces a stable error (no crash)."""
        payload = self._parse(_invalid_entry_type_response(42))
        assert payload["code"] == "INVALID_PARAMS"
        assert payload["details"]["provided"] == 42
        assert "suggestion" not in payload["details"]
