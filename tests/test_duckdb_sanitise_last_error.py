"""Unit tests for ``DuckDBStore._sanitise_last_error``.

Lives in its own module (not ``test_duckdb_store.py``) because that module
applies ``pytestmark = pytest.mark.integration``. Double-marking these
pure-helper tests as both ``unit`` and ``integration`` makes marker-based
selection unreliable.
"""

from __future__ import annotations

import pytest

from distillery.store.duckdb import _sanitise_last_error

pytestmark = pytest.mark.unit


def test_none_returns_none() -> None:
    assert _sanitise_last_error(None, 200) is None


def test_empty_returns_none() -> None:
    assert _sanitise_last_error("   \n\t", 200) is None


def test_short_error_is_preserved() -> None:
    assert _sanitise_last_error("upstream 502", 200) == "upstream 502"


def test_collapses_whitespace_and_newlines() -> None:
    raw = "Traceback:\n  File 'x'\n  ValueError: boom"
    assert _sanitise_last_error(raw, 200) == "Traceback: File 'x' ValueError: boom"


def test_truncates_when_longer_than_max_len() -> None:
    raw = "x" * 500
    result = _sanitise_last_error(raw, 50)
    assert result is not None
    assert len(result) == 50
    assert result.endswith("\u2026")
