"""Tests for security utilities (error sanitization, logging filter)."""

from __future__ import annotations

import logging

import pytest

from distillery.security import SecretRedactFilter, sanitize_error

# ---------------------------------------------------------------------------
# sanitize_error()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSanitizeError:
    def test_redacts_jina_key(self) -> None:
        msg = "API key jina_abcdef1234567890 is invalid"
        result = sanitize_error(msg)
        assert "jina_abcdef1234567890" not in result
        assert "jina_abcd****" in result

    def test_redacts_openai_key(self) -> None:
        msg = "Invalid key: sk-proj1234567890abcdef"
        result = sanitize_error(msg)
        assert "sk-proj1234567890abcdef" not in result
        assert "sk-proj****" in result

    def test_redacts_ghp_token(self) -> None:
        msg = "Token ghp_abcdef1234567890 expired"
        result = sanitize_error(msg)
        assert "ghp_abcdef1234567890" not in result
        assert "ghp_abcd****" in result

    def test_redacts_gho_token(self) -> None:
        msg = "OAuth token gho_xyz1234567890 revoked"
        result = sanitize_error(msg)
        assert "gho_xyz1234567890" not in result
        assert "gho_xyz1****" in result

    def test_redacts_github_pat(self) -> None:
        msg = "PAT github_pat_abcdef1234567890 is invalid"
        result = sanitize_error(msg)
        assert "github_pat_abcdef1234567890" not in result
        assert "github_pat_abcd****" in result

    def test_preserves_safe_strings(self) -> None:
        safe = "Normal error: connection refused on port 8080"
        assert sanitize_error(safe) == safe

    def test_preserves_similar_but_safe_patterns(self) -> None:
        safe = "the skeleton key opens the door"
        assert sanitize_error(safe) == safe

    def test_redacts_multiple_keys(self) -> None:
        msg = "Keys: jina_key123456 and sk-other987654"
        result = sanitize_error(msg)
        assert "jina_key123456" not in result
        assert "sk-other987654" not in result


# ---------------------------------------------------------------------------
# SecretRedactFilter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSecretRedactFilter:
    def test_filter_sanitizes_message(self) -> None:
        filt = SecretRedactFilter()
        record = logging.LogRecord(
            name="distillery",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Key sk-secret1234567890 failed",
            args=None,
            exc_info=None,
        )
        filt.filter(record)
        assert "sk-secret1234567890" not in record.msg
        assert "sk-secr****" in record.msg

    def test_filter_sanitizes_tuple_args(self) -> None:
        filt = SecretRedactFilter()
        record = logging.LogRecord(
            name="distillery",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="Error with %s",
            args=("ghp_token1234567890",),
            exc_info=None,
        )
        filt.filter(record)
        assert isinstance(record.args, tuple)
        assert "ghp_token1234567890" not in record.args[0]

    def test_filter_returns_true(self) -> None:
        """Filter always returns True (mutation, not suppression)."""
        filt = SecretRedactFilter()
        record = logging.LogRecord(
            name="distillery",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Normal message",
            args=None,
            exc_info=None,
        )
        assert filt.filter(record) is True

    def test_filter_redacts_ghp_token_in_log_args(self) -> None:
        """GitHub classic PAT in log tuple args is redacted."""
        filt = SecretRedactFilter()
        record = logging.LogRecord(
            name="distillery",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="adapter token: %s",
            args=("ghp_realtoken123456789",),
            exc_info=None,
        )
        filt.filter(record)
        assert isinstance(record.args, tuple)
        assert "ghp_realtoken123456789" not in record.args[0]
        assert "ghp_real****" in record.args[0]

    def test_filter_redacts_github_pat_in_log_message(self) -> None:
        """GitHub fine-grained PAT in log message is redacted."""
        filt = SecretRedactFilter()
        record = logging.LogRecord(
            name="distillery",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="using token github_pat_abcdef1234567890",
            args=None,
            exc_info=None,
        )
        filt.filter(record)
        assert "github_pat_abcdef1234567890" not in record.msg
        assert "github_pat_abcd****" in record.msg

    def test_filter_redacts_gho_oauth_token_in_log_args(self) -> None:
        """GitHub OAuth token in log tuple args is redacted."""
        filt = SecretRedactFilter()
        record = logging.LogRecord(
            name="distillery",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="oauth token: %s",
            args=("gho_oauthtoken9876543",),
            exc_info=None,
        )
        filt.filter(record)
        assert isinstance(record.args, tuple)
        assert "gho_oauthtoken9876543" not in record.args[0]
        assert "gho_oaut****" in record.args[0]
