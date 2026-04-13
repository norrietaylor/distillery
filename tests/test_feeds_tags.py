"""Tests for distillery.feeds.tags: sanitise_label().

The sanitise_label() function is a new helper added in this PR to normalise
external labels (GitHub, RSS, etc.) into Distillery-conforming tag strings.

Tag grammar: ``[a-z0-9][a-z0-9-]*`` — lowercase alphanumeric, with internal
hyphens allowed, must start with a letter or digit.
"""

from __future__ import annotations

import pytest

from distillery.feeds.tags import sanitise_label

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Happy-path: labels that produce valid tags
# ---------------------------------------------------------------------------


class TestSanitiseLabelValid:
    """Labels that should produce a valid, non-None tag string."""

    def test_already_valid_label(self) -> None:
        """A label already in tag-safe form is returned unchanged."""
        assert sanitise_label("python") == "python"

    def test_already_valid_label_with_hyphen(self) -> None:
        assert sanitise_label("my-label") == "my-label"

    def test_lowercase_conversion(self) -> None:
        """Uppercase letters are lowercased."""
        assert sanitise_label("Python") == "python"

    def test_uppercase_all_caps(self) -> None:
        assert sanitise_label("RUST") == "rust"

    def test_mixed_case(self) -> None:
        assert sanitise_label("MyFeature") == "myfeature"

    def test_spaces_become_hyphens(self) -> None:
        """Spaces are converted to hyphens."""
        assert sanitise_label("my label") == "my-label"

    def test_underscores_become_hyphens(self) -> None:
        """Underscores are converted to hyphens."""
        assert sanitise_label("my_label") == "my-label"

    def test_mixed_spaces_and_underscores(self) -> None:
        """Both spaces and underscores become hyphens, collapsing consecutive ones."""
        assert sanitise_label("my label_here") == "my-label-here"

    def test_consecutive_hyphens_collapsed(self) -> None:
        """Multiple consecutive hyphens are collapsed to one."""
        assert sanitise_label("my--label") == "my-label"

    def test_spaces_producing_consecutive_hyphens(self) -> None:
        """Consecutive spaces produce consecutive hyphens, which are then collapsed."""
        assert sanitise_label("my  label") == "my-label"

    def test_underscores_producing_consecutive_hyphens(self) -> None:
        assert sanitise_label("my__label") == "my-label"

    def test_leading_hyphen_stripped(self) -> None:
        """A leading hyphen (after normalisation) is stripped."""
        # If the label starts with a hyphen, the result should have it stripped.
        # e.g. "-python" -> "python"
        result = sanitise_label("-python")
        assert result == "python"

    def test_trailing_hyphen_stripped(self) -> None:
        """A trailing hyphen (after normalisation) is stripped."""
        result = sanitise_label("python-")
        assert result == "python"

    def test_digit_only_label(self) -> None:
        """A label consisting of only digits is valid (starts with [a-z0-9])."""
        assert sanitise_label("123") == "123"

    def test_label_starting_with_digit(self) -> None:
        assert sanitise_label("1st-place") == "1st-place"

    def test_numeric_label(self) -> None:
        """Pure numeric labels like GitHub issue numbers are valid."""
        assert sanitise_label("42") == "42"

    def test_github_label_bug(self) -> None:
        """Common GitHub label 'bug' is returned as-is."""
        assert sanitise_label("bug") == "bug"

    def test_github_label_enhancement(self) -> None:
        assert sanitise_label("enhancement") == "enhancement"

    def test_github_label_with_colon_like_prefix(self) -> None:
        """Labels with spaces like 'good first issue' get hyphens."""
        assert sanitise_label("good first issue") == "good-first-issue"

    def test_complex_github_label(self) -> None:
        """GitHub label with mixed case and spaces."""
        assert sanitise_label("Good First Issue") == "good-first-issue"

    def test_label_with_numbers_and_letters(self) -> None:
        assert sanitise_label("api-v2") == "api-v2"

    def test_label_with_trailing_space(self) -> None:
        """Labels with trailing whitespace produce hyphens that are then stripped."""
        result = sanitise_label("python ")
        assert result == "python"

    def test_label_with_leading_space(self) -> None:
        result = sanitise_label(" python")
        assert result == "python"

    def test_underscore_at_start(self) -> None:
        """Leading underscore converts to hyphen, which is then stripped."""
        result = sanitise_label("_python")
        assert result == "python"

    def test_underscore_at_end(self) -> None:
        result = sanitise_label("python_")
        assert result == "python"


# ---------------------------------------------------------------------------
# None-returning cases: labels that cannot produce a valid tag
# ---------------------------------------------------------------------------


class TestSanitiseLabelReturnsNone:
    """Labels that should return None (cannot be normalised to a valid tag)."""

    def test_empty_string_returns_none(self) -> None:
        """An empty string cannot produce a valid tag."""
        assert sanitise_label("") is None

    def test_only_hyphens_returns_none(self) -> None:
        """A string of only hyphens, after stripping, is empty."""
        assert sanitise_label("---") is None

    def test_only_spaces_returns_none(self) -> None:
        """Spaces → hyphens → stripped → empty string."""
        assert sanitise_label("   ") is None

    def test_only_underscores_returns_none(self) -> None:
        assert sanitise_label("___") is None

    def test_special_characters_only_returns_none(self) -> None:
        """Labels with only special characters (not alphanumeric or space/underscore)
        produce no valid tag content."""
        assert sanitise_label("!!!") is None

    def test_label_with_colons_only(self) -> None:
        """Colons are not part of the allowed character set."""
        assert sanitise_label("::") is None

    def test_label_with_at_sign(self) -> None:
        """@ is not allowed in Distillery tags."""
        assert sanitise_label("@user") is None

    def test_label_with_dot_only(self) -> None:
        """Dots are not allowed in Distillery tags."""
        assert sanitise_label(".") is None

    def test_label_with_slash_only(self) -> None:
        """Slashes produce tags with slashes which don't match the grammar."""
        # Note: "/" is not converted by the normalisation, so "a/b" → "a/b"
        # which does NOT match [a-z0-9][a-z0-9-]*, so returns None.
        assert sanitise_label("/") is None


# ---------------------------------------------------------------------------
# Boundary and regression cases
# ---------------------------------------------------------------------------


class TestSanitiseLabelBoundary:
    """Boundary conditions and regression tests."""

    def test_single_letter(self) -> None:
        """A single letter is a valid tag."""
        assert sanitise_label("a") == "a"

    def test_single_digit(self) -> None:
        """A single digit is a valid tag."""
        assert sanitise_label("1") == "1"

    def test_long_label(self) -> None:
        """Long labels that are otherwise valid are accepted."""
        long_label = "a" * 100
        assert sanitise_label(long_label) == long_label

    def test_mixed_special_valid(self) -> None:
        """Labels with some non-conforming chars — only valid portion kept
        is not possible; full match is required."""
        # "c++" → "c" after stripping non-alphanum... but "+" is not handled
        # by the normalisation (only space/underscore → hyphen). So "c++" stays
        # as "c++" after lowercasing, and "c++" doesn't match [a-z0-9][a-z0-9-]*
        assert sanitise_label("c++") is None

    def test_label_with_period(self) -> None:
        """Periods are not converted and result in None."""
        assert sanitise_label("v1.0") is None

    def test_github_area_label(self) -> None:
        """GitHub 'area: auth' style labels become 'area--auth' -> 'area-auth'."""
        # "area: auth" -> lowercase -> "area: auth"
        # spaces -> hyphens -> "area:-auth"
        # But ":" is not converted, so result has ":", which fails validation.
        # Returns None (the colon prevents a valid match).
        assert sanitise_label("area: auth") is None

    def test_numeric_hyphen_label(self) -> None:
        """Hyphen-separated numbers are valid."""
        assert sanitise_label("v2-0") == "v2-0"

    def test_return_type_is_str_or_none(self) -> None:
        """The function returns str or None, never another type."""
        result = sanitise_label("test")
        assert isinstance(result, str)
        none_result = sanitise_label("")
        assert none_result is None

    def test_idempotent_on_valid_tags(self) -> None:
        """Running sanitise_label on an already-normalised tag is a no-op."""
        tag = "good-tag-name"
        assert sanitise_label(tag) == tag

    def test_consecutive_mixed_separators(self) -> None:
        """Mixed underscores and spaces between words collapse to one hyphen."""
        # "a _ b" -> "a---b" -> "a-b"
        assert sanitise_label("a _ b") == "a-b"

    def test_all_digits_with_hyphen(self) -> None:
        """Digit-hyphen-digit pattern is valid."""
        assert sanitise_label("3-5") == "3-5"

    def test_label_matches_tag_grammar_invariant(self) -> None:
        """Any non-None result must match the Distillery tag grammar."""
        import re

        _TAG_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")
        test_labels = [
            "python",
            "My Label",
            "good_first_issue",
            "  spaced  ",
            "UPPER",
            "mixed-Case",
            "under_score",
            "a",
            "1",
            "123abc",
        ]
        for label in test_labels:
            result = sanitise_label(label)
            if result is not None:
                assert _TAG_RE.fullmatch(result), (
                    f"sanitise_label({label!r}) = {result!r} doesn't match tag grammar"
                )