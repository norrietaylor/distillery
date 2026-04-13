"""Tests for distillery.feeds.tags.sanitise_label.

Covers the label normalisation steps:
1. Lowercase
2. Spaces and underscores become hyphens
3. Consecutive hyphens collapsed
4. Leading/trailing hyphens stripped
5. Returns None when result does not match the tag grammar
"""

from __future__ import annotations

import pytest

from distillery.feeds.tags import sanitise_label

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Basic normalisation
# ---------------------------------------------------------------------------


class TestSanitiseLabelNormalisation:
    """Tests for the normalisation pipeline in sanitise_label()."""

    def test_already_valid_label_returned_unchanged(self) -> None:
        """A label already in tag grammar is returned as-is."""
        assert sanitise_label("bug") == "bug"

    def test_uppercase_lowercased(self) -> None:
        """Uppercase letters are lowercased."""
        assert sanitise_label("BUG") == "bug"

    def test_mixed_case_lowercased(self) -> None:
        """Mixed-case label is fully lowercased."""
        assert sanitise_label("HighPriority") == "highpriority"

    def test_spaces_become_hyphens(self) -> None:
        """Spaces are converted to hyphens."""
        assert sanitise_label("high priority") == "high-priority"

    def test_underscores_become_hyphens(self) -> None:
        """Underscores are converted to hyphens."""
        assert sanitise_label("my_feature") == "my-feature"

    def test_consecutive_hyphens_collapsed(self) -> None:
        """Multiple consecutive hyphens are collapsed to a single hyphen."""
        assert sanitise_label("a---b") == "a-b"

    def test_consecutive_hyphens_from_spaces_collapsed(self) -> None:
        """Multiple spaces that become hyphens are collapsed."""
        assert sanitise_label("a   b") == "a-b"

    def test_leading_hyphens_stripped(self) -> None:
        """Hyphens at the start of the result are stripped."""
        assert sanitise_label("-feature") == "feature"

    def test_trailing_hyphens_stripped(self) -> None:
        """Hyphens at the end of the result are stripped."""
        assert sanitise_label("feature-") == "feature"

    def test_both_leading_and_trailing_hyphens_stripped(self) -> None:
        """Leading and trailing hyphens are both removed."""
        assert sanitise_label("-feature-") == "feature"

    def test_mixed_transformations(self) -> None:
        """All transformations compose correctly on a realistic label."""
        assert sanitise_label("My Feature_Request") == "my-feature-request"

    def test_label_with_numbers_valid(self) -> None:
        """Labels containing numbers are preserved."""
        assert sanitise_label("v3-release") == "v3-release"

    def test_single_character_label(self) -> None:
        """A single alphanumeric character is a valid tag."""
        assert sanitise_label("a") == "a"

    def test_label_starting_with_digit(self) -> None:
        """Labels starting with a digit are valid."""
        assert sanitise_label("2024-release") == "2024-release"

    def test_underscore_then_space_normalised(self) -> None:
        """Labels with both underscores and spaces normalise correctly."""
        assert sanitise_label("my_feature name") == "my-feature-name"

    def test_consecutive_hyphens_from_underscores_and_spaces(self) -> None:
        """Underscores adjacent to spaces/hyphens collapse to a single hyphen."""
        assert sanitise_label("a_ b") == "a-b"


# ---------------------------------------------------------------------------
# Returns None for invalid labels
# ---------------------------------------------------------------------------


class TestSanitiseLabelReturnsNone:
    """Tests where sanitise_label() returns None for unconvertible labels."""

    def test_all_hyphens_returns_none(self) -> None:
        """A label of only hyphens becomes empty after stripping → None."""
        assert sanitise_label("---") is None

    def test_all_spaces_returns_none(self) -> None:
        """A label of only spaces collapses to a single hyphen, then strips → None."""
        assert sanitise_label("   ") is None

    def test_all_underscores_returns_none(self) -> None:
        """A label of only underscores collapses and strips → None."""
        assert sanitise_label("___") is None

    def test_empty_string_returns_none(self) -> None:
        """An empty string produces no valid tag."""
        assert sanitise_label("") is None

    def test_label_with_dot_returns_none(self) -> None:
        """Dots are not part of the tag grammar."""
        assert sanitise_label("v1.0") is None

    def test_label_with_colon_returns_none(self) -> None:
        """Colons are not part of the tag grammar."""
        assert sanitise_label("type:bug") is None

    def test_label_with_slash_returns_none(self) -> None:
        """Forward slashes are not allowed in flat label context.

        The sanitiser only handles flat labels; hierarchical tags are composed
        at a higher level. Slashes are not converted and leave the label
        non-conforming.
        """
        assert sanitise_label("area/auth") is None

    def test_label_with_at_sign_returns_none(self) -> None:
        """@ signs do not map to valid tag characters."""
        assert sanitise_label("@owner") is None

    def test_label_with_hash_returns_none(self) -> None:
        """# signs do not map to valid tag characters."""
        assert sanitise_label("#issue") is None

    def test_label_consisting_only_of_special_chars_returns_none(self) -> None:
        """Non-alphanumeric, non-hyphen characters that are not spaces/underscores
        leave the label invalid after normalisation."""
        assert sanitise_label("!!!") is None


# ---------------------------------------------------------------------------
# Representative real-world GitHub labels
# ---------------------------------------------------------------------------


class TestSanitiseLabelGitHubLabels:
    """Smoke tests with labels found on real GitHub repositories."""

    @pytest.mark.parametrize(
        "label, expected",
        [
            ("bug", "bug"),
            ("enhancement", "enhancement"),
            ("good first issue", "good-first-issue"),
            ("help wanted", "help-wanted"),
            ("wontfix", "wontfix"),
            ("high-priority", "high-priority"),
            ("needs_review", "needs-review"),
            ("CI/CD", None),           # slash makes it invalid
            ("breaking change", "breaking-change"),
            # Colons remain after normalisation and fail the tag grammar:
            ("Type: Bug", None),
            ("Status: In Progress", None),
        ],
    )
    def test_github_label_normalisation(self, label: str, expected: str | None) -> None:
        assert sanitise_label(label) == expected