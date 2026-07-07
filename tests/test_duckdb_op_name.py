"""Unit tests for ``distillery.store.duckdb._op_name``.

Lives in its own module (not ``test_duckdb_store.py``) because that module
applies ``pytestmark = pytest.mark.integration``. Double-marking these
pure-helper tests as both ``unit`` and ``integration`` makes marker-based
selection unreliable.
"""

from __future__ import annotations

import functools

import pytest

from distillery.store.duckdb import DuckDBStore, _op_name

pytestmark = pytest.mark.unit


def test_bound_method_uses_method_name() -> None:
    assert _op_name(DuckDBStore._sync_delete) == "_sync_delete"


def test_closure_uses_enclosing_function_name() -> None:
    def search():
        def _sync():
            pass

        return _sync

    assert _op_name(search()) == "search"


def test_lambda_uses_enclosing_function_name() -> None:
    def get():
        return lambda conn: conn

    assert _op_name(get()) == "get"


def test_callable_without_qualname_falls_back_to_verbatim_repr() -> None:
    # functools.partial instances expose no __qualname__.
    fn = functools.partial(sorted)
    assert _op_name(fn) == repr(fn)


def test_local_callable_instance_repr_is_not_split_like_a_qualname() -> None:
    # The instance repr contains dots and "<locals>"; it must come back
    # verbatim, not collapse to the enclosing function name ("outer").
    def outer():
        class _Op:
            def __call__(self) -> None:
                pass

        return _Op()

    inst = outer()
    assert _op_name(inst) == repr(inst)
