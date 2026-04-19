"""Unit tests for error codes and validation helpers in distillery.mcp.tools._errors.

Tests cover:
  - ToolErrorCode enum with 4 standardized codes
  - tool_error() helper for formatted error tuples
  - validate_limit() helper with min/max/default constraints
  - Edge cases and type coercion
"""

from __future__ import annotations

import pytest

from distillery.mcp.tools._errors import ToolErrorCode, tool_error, validate_limit

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# ToolErrorCode enum tests
# ---------------------------------------------------------------------------


class TestToolErrorCode:
    """Tests for the ToolErrorCode enum."""

    def test_has_all_required_codes(self) -> None:
        """Verify all four standard codes are defined."""
        assert ToolErrorCode.INVALID_PARAMS == "INVALID_PARAMS"
        assert ToolErrorCode.NOT_FOUND == "NOT_FOUND"
        assert ToolErrorCode.CONFLICT == "CONFLICT"
        assert ToolErrorCode.INTERNAL == "INTERNAL"

    def test_codes_are_str_enum(self) -> None:
        """Verify codes are StrEnum values (can be used as strings)."""
        code = ToolErrorCode.INVALID_PARAMS
        assert isinstance(code, str)
        assert code == "INVALID_PARAMS"
        assert str(code) == "INVALID_PARAMS"

    def test_all_codes_listed(self) -> None:
        """Verify there are exactly 9 codes (no accidental additions)."""
        codes = list(ToolErrorCode)
        assert len(codes) == 9
        assert set(codes) == {
            ToolErrorCode.INVALID_PARAMS,
            ToolErrorCode.NOT_FOUND,
            ToolErrorCode.CONFLICT,
            ToolErrorCode.INTERNAL,
            ToolErrorCode.FORBIDDEN,
            ToolErrorCode.BUDGET_EXCEEDED,
            ToolErrorCode.RATE_LIMITED,
            ToolErrorCode.UPSTREAM_RATE_LIMITED,
            ToolErrorCode.UPSTREAM_ERROR,
        }


# ---------------------------------------------------------------------------
# tool_error() helper tests
# ---------------------------------------------------------------------------


class TestToolError:
    """Tests for the tool_error() helper."""

    def test_returns_tuple(self) -> None:
        """Verify tool_error returns a (code, message) tuple."""
        result = tool_error(ToolErrorCode.NOT_FOUND, "Entry not found")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_with_enum_code(self) -> None:
        """Verify tool_error works with ToolErrorCode enum values."""
        code, msg = tool_error(ToolErrorCode.NOT_FOUND, "Entry not found")
        assert code == ToolErrorCode.NOT_FOUND
        assert msg == "Entry not found"

    def test_with_string_code(self) -> None:
        """Verify tool_error works with string codes for flexibility."""
        code, msg = tool_error("CUSTOM_CODE", "Custom error")
        assert code == "CUSTOM_CODE"
        assert msg == "Custom error"

    def test_preserves_message(self) -> None:
        """Verify tool_error preserves the message exactly."""
        message = "This is a detailed error message with special chars: @#$%"
        code, msg = tool_error(ToolErrorCode.INVALID_PARAMS, message)
        assert msg == message

    def test_all_error_codes(self) -> None:
        """Verify tool_error works with all standard codes."""
        for error_code in ToolErrorCode:
            code, msg = tool_error(error_code, "Test message")
            assert code == error_code
            assert msg == "Test message"


# ---------------------------------------------------------------------------
# validate_limit() helper tests
# ---------------------------------------------------------------------------


class TestValidateLimit:
    """Tests for the validate_limit() helper."""

    def test_returns_default_when_none(self) -> None:
        """Verify validate_limit returns default when value is None."""
        result = validate_limit(None, min_val=1, max_val=100, default=50)
        assert result == 50

    def test_accepts_valid_integer(self) -> None:
        """Verify validate_limit accepts valid integers."""
        result = validate_limit(50, min_val=1, max_val=100)
        assert result == 50

    def test_coerces_string_to_int(self) -> None:
        """Verify validate_limit coerces string integers."""
        result = validate_limit("75", min_val=1, max_val=100)
        assert result == 75
        assert isinstance(result, int)

    def test_coerces_float_to_int(self) -> None:
        """Verify validate_limit coerces floats (truncates)."""
        result = validate_limit(75.9, min_val=1, max_val=100)
        assert result == 75
        assert isinstance(result, int)

    def test_enforces_min_boundary(self) -> None:
        """Verify validate_limit enforces minimum boundary."""
        result = validate_limit(0, min_val=1, max_val=100)
        assert isinstance(result, tuple)
        code, msg = result
        assert code == ToolErrorCode.INVALID_PARAMS
        assert "must be >= 1" in msg

    def test_enforces_max_boundary(self) -> None:
        """Verify validate_limit enforces maximum boundary."""
        result = validate_limit(101, min_val=1, max_val=100)
        assert isinstance(result, tuple)
        code, msg = result
        assert code == ToolErrorCode.INVALID_PARAMS
        assert "must be <= 100" in msg

    def test_rejects_invalid_string(self) -> None:
        """Verify validate_limit rejects non-numeric strings."""
        result = validate_limit("not-a-number", min_val=1, max_val=100)
        assert isinstance(result, tuple)
        code, msg = result
        assert code == ToolErrorCode.INVALID_PARAMS
        assert "must be an integer" in msg

    def test_rejects_none_like_types(self) -> None:
        """Verify validate_limit rejects types that cannot be coerced."""
        result = validate_limit({"limit": 50}, min_val=1, max_val=100)
        assert isinstance(result, tuple)
        code, msg = result
        assert code == ToolErrorCode.INVALID_PARAMS

    def test_edge_case_min_equals_value(self) -> None:
        """Verify validate_limit accepts value equal to min."""
        result = validate_limit(1, min_val=1, max_val=100)
        assert result == 1

    def test_edge_case_max_equals_value(self) -> None:
        """Verify validate_limit accepts value equal to max."""
        result = validate_limit(100, min_val=1, max_val=100)
        assert result == 100

    def test_default_parameters(self) -> None:
        """Verify validate_limit uses sensible defaults (1-1000, default 50)."""
        result = validate_limit(None)
        assert result == 50

        result = validate_limit(1)
        assert result == 1

        result = validate_limit(1000)
        assert result == 1000

    def test_custom_defaults(self) -> None:
        """Verify validate_limit respects custom min/max/default."""
        result = validate_limit(None, min_val=10, max_val=500, default=100)
        assert result == 100

        result = validate_limit(5, min_val=10, max_val=500)
        assert isinstance(result, tuple)  # below min

        result = validate_limit(600, min_val=10, max_val=500)
        assert isinstance(result, tuple)  # above max

    def test_error_messages_include_limits(self) -> None:
        """Verify error messages mention the actual min/max values."""
        _, msg_min = validate_limit(0, min_val=10, max_val=500)
        assert "10" in msg_min

        _, msg_max = validate_limit(600, min_val=10, max_val=500)
        assert "500" in msg_max

    def test_zero_is_valid_if_allowed(self) -> None:
        """Verify validate_limit allows 0 if min_val permits it."""
        result = validate_limit(0, min_val=0, max_val=100)
        assert result == 0

    def test_negative_is_valid_if_allowed(self) -> None:
        """Verify validate_limit allows negative values if min_val permits it."""
        result = validate_limit(-10, min_val=-100, max_val=100)
        assert result == -10

    def test_large_numbers(self) -> None:
        """Verify validate_limit handles large numbers correctly."""
        result = validate_limit(999999, min_val=1, max_val=1000000)
        assert result == 999999

        result = validate_limit(1000001, min_val=1, max_val=1000000)
        assert isinstance(result, tuple)  # exceeds max
