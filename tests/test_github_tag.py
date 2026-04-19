"""Unit tests for the shared GitHub label → Distillery tag sanitiser.

Covers :func:`distillery.feeds.github_tag.sanitize_label`. The sanitiser
is the single source of truth used by both the server-side feeds adapter
and the ``/gh-sync`` skill; see issue #241.
"""

from __future__ import annotations

import pytest

from distillery.feeds.github_tag import sanitize_label

pytestmark = pytest.mark.unit


class TestSanitizeLabel:
    """Exercise the coercion rule and its boundary conditions."""

    def test_already_valid_label_is_returned_unchanged(self) -> None:
        assert sanitize_label("bug") == "bug"
        assert sanitize_label("high-priority") == "high-priority"

    def test_uppercase_is_lowercased(self) -> None:
        assert sanitize_label("Bug") == "bug"
        assert sanitize_label("CLA Signed") == "cla-signed"

    def test_spaces_become_hyphens(self) -> None:
        assert sanitize_label("high priority") == "high-priority"

    def test_underscores_become_hyphens(self) -> None:
        # Regression for issue #241: github_actions is a default label on
        # any repo using GitHub Actions and must survive sanitisation rather
        # than failing the whole entry.
        assert sanitize_label("github_actions") == "github-actions"

    def test_underscores_and_spaces_mixed(self) -> None:
        assert sanitize_label("High_Priority Bug") == "high-priority-bug"

    def test_consecutive_separators_collapse(self) -> None:
        assert sanitize_label("a  b") == "a-b"
        assert sanitize_label("a__b") == "a-b"
        assert sanitize_label("a -_ b") == "a-b"

    def test_leading_and_trailing_separators_are_stripped(self) -> None:
        assert sanitize_label("-leading") == "leading"
        assert sanitize_label("trailing-") == "trailing"
        assert sanitize_label("_wrapped_") == "wrapped"

    def test_digit_prefix_is_allowed(self) -> None:
        assert sanitize_label("9 lives") == "9-lives"

    def test_empty_input_returns_none(self) -> None:
        assert sanitize_label("") is None

    def test_separator_only_input_returns_none(self) -> None:
        assert sanitize_label("   ") is None
        assert sanitize_label("_") is None
        assert sanitize_label("---") is None

    def test_uncoercible_characters_return_none(self) -> None:
        # Punctuation not in the coercion map stays in the candidate and
        # fails the segment grammar, so the label is dropped entirely.
        assert sanitize_label("!!! urgent") is None
        assert sanitize_label("needs/review") is None  # forward slash is not a segment char
        assert sanitize_label("v1.0") is None  # dot is not a segment char

    def test_unicode_letters_are_dropped(self) -> None:
        # Distillery's tag grammar is ASCII-only; non-ASCII labels currently
        # have no well-defined coercion, so they are skipped rather than
        # silently normalised to something the caller did not choose.
        assert sanitize_label("café") is None
