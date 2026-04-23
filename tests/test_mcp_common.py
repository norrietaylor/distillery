"""Unit tests for distillery.mcp.tools._common validation helpers.

Covers ``validate_required``, ``validate_type``, ``validate_enum``, and
``validate_positive_int``.  These helpers shape every INVALID_PARAMS error
returned by the MCP tools, so their contract is asserted here explicitly —
agents rely on the error message to recover without replaying identical
payloads (issue #371).
"""

from __future__ import annotations

import pytest

from distillery.mcp.tools._common import (
    validate_enum,
    validate_positive_int,
    validate_required,
    validate_type,
)

pytestmark = pytest.mark.unit


class TestValidateRequired:
    """Tests for ``validate_required`` — field presence and non-emptiness."""

    def test_all_fields_present_returns_none(self) -> None:
        assert validate_required({"a": "x", "b": "y"}, "a", "b") is None

    def test_single_absent_field(self) -> None:
        msg = validate_required({"a": "x"}, "a", "b")
        assert msg == "Missing required fields: b"

    def test_multiple_absent_fields_listed_in_order(self) -> None:
        msg = validate_required({}, "a", "b", "c")
        assert msg == "Missing required fields: a, b, c"

    def test_explicit_none_treated_as_missing(self) -> None:
        msg = validate_required({"a": None}, "a")
        assert msg == "Missing required fields: a"

    def test_empty_string_reports_non_empty_message(self) -> None:
        """Issue #371: empty string is present, not missing."""
        msg = validate_required({"query": ""}, "query")
        assert msg == "Field 'query' must be a non-empty string"

    def test_whitespace_only_string_treated_as_empty(self) -> None:
        """Issue #371: whitespace-only strings are functionally empty."""
        msg = validate_required({"query": "   \t\n"}, "query")
        assert msg == "Field 'query' must be a non-empty string"

    def test_multiple_empty_fields(self) -> None:
        msg = validate_required({"a": "", "b": ""}, "a", "b")
        assert msg == "Fields must be non-empty strings: 'a', 'b'"

    def test_missing_takes_precedence_over_empty(self) -> None:
        """When both categories fail, report missing first so clients fix the
        more fundamental issue before retrying."""
        msg = validate_required({"a": ""}, "a", "b")
        assert msg == "Missing required fields: b"

    def test_zero_is_not_treated_as_missing(self) -> None:
        """Guards the #245 hint in issue #371: ``0`` is a valid int payload."""
        assert validate_required({"n": 0}, "n") is None

    def test_false_is_not_treated_as_missing(self) -> None:
        assert validate_required({"flag": False}, "flag") is None

    def test_empty_list_is_not_treated_as_missing(self) -> None:
        """Non-string falsy values are valid — only strings get the empty check."""
        assert validate_required({"tags": []}, "tags") is None

    def test_empty_dict_is_not_treated_as_missing(self) -> None:
        assert validate_required({"meta": {}}, "meta") is None

    def test_non_string_non_none_value_passes(self) -> None:
        assert validate_required({"n": 42, "flag": True}, "n", "flag") is None


class TestValidateType:
    """Tests for ``validate_type``."""

    def test_correct_type_returns_none(self) -> None:
        assert validate_type({"x": [1, 2]}, "x", list, "list") is None

    def test_wrong_type_returns_message(self) -> None:
        msg = validate_type({"x": "not-a-list"}, "x", list, "list of strings")
        assert msg == "Field 'x' must be a list of strings"

    def test_absent_field_is_ok(self) -> None:
        """validate_type only runs when the field is present — presence is the
        job of validate_required."""
        assert validate_type({}, "x", list, "list") is None

    def test_none_value_is_ok(self) -> None:
        assert validate_type({"x": None}, "x", list, "list") is None

    def test_tuple_of_types_accepted(self) -> None:
        assert validate_type({"n": 1.5}, "n", (int, float), "number") is None
        assert validate_type({"n": 1}, "n", (int, float), "number") is None


class TestValidateEnum:
    """Tests for ``validate_enum``."""

    def test_valid_value_returns_none(self) -> None:
        assert validate_enum({"action": "approve"}, "action", {"approve", "archive"}) is None

    def test_invalid_value_returns_message(self) -> None:
        msg = validate_enum({"action": "nuke"}, "action", {"approve", "archive"})
        assert msg is not None
        assert "nuke" in msg
        assert "approve" in msg and "archive" in msg

    def test_absent_field_is_ok(self) -> None:
        assert validate_enum({}, "action", {"approve"}) is None

    def test_non_string_value_rejected(self) -> None:
        """JSON arrays/objects arrive as list/dict — must not raise TypeError."""
        msg = validate_enum({"action": ["approve"]}, "action", {"approve"})
        assert msg is not None
        assert "approve" in msg

    def test_label_overrides_field_name_in_message(self) -> None:
        msg = validate_enum({"a": "bad"}, "a", {"good"}, label="choice")
        assert msg is not None
        assert "Invalid choice" in msg


class TestValidatePositiveInt:
    """Tests for ``validate_positive_int``."""

    def test_valid_int_returned(self) -> None:
        assert validate_positive_int({"limit": 10}, "limit") == 10

    def test_default_used_when_absent(self) -> None:
        assert validate_positive_int({}, "limit", default=5) == 5

    def test_missing_without_default_returns_error(self) -> None:
        result = validate_positive_int({}, "limit")
        assert isinstance(result, tuple)
        assert "required" in result[1].lower()

    def test_zero_rejected(self) -> None:
        result = validate_positive_int({"limit": 0}, "limit")
        assert isinstance(result, tuple)

    def test_negative_rejected(self) -> None:
        result = validate_positive_int({"limit": -1}, "limit")
        assert isinstance(result, tuple)

    def test_non_int_rejected(self) -> None:
        result = validate_positive_int({"limit": "10"}, "limit")
        assert isinstance(result, tuple)

    def test_bool_rejected(self) -> None:
        """``True`` is an int in Python — the validator must reject it anyway."""
        result = validate_positive_int({"limit": True}, "limit")
        assert isinstance(result, tuple)
