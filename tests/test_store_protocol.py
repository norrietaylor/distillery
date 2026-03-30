"""Tests for DistilleryStore protocol compliance via duck typing.

Verifies that ``DuckDBStore`` satisfies the ``DistilleryStore`` Protocol
structurally (duck typing) without relying on inheritance.
"""

from __future__ import annotations

import inspect

import pytest

from distillery.store.duckdb import DuckDBStore
from distillery.store.protocol import DistilleryStore

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Protocol structural compliance
# ---------------------------------------------------------------------------


class TestDistilleryStoreProtocolCompliance:
    """Verify that DuckDBStore satisfies the DistilleryStore protocol."""

    def test_duckdb_store_is_instance_of_protocol(self, mock_embedding_provider) -> None:
        """isinstance check against @runtime_checkable Protocol passes."""
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        assert isinstance(store, DistilleryStore)

    def test_store_method_exists(self, mock_embedding_provider) -> None:
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        assert hasattr(store, "store")
        assert callable(store.store)

    def test_get_method_exists(self, mock_embedding_provider) -> None:
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        assert hasattr(store, "get")
        assert callable(store.get)

    def test_update_method_exists(self, mock_embedding_provider) -> None:
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        assert hasattr(store, "update")
        assert callable(store.update)

    def test_delete_method_exists(self, mock_embedding_provider) -> None:
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        assert hasattr(store, "delete")
        assert callable(store.delete)

    def test_search_method_exists(self, mock_embedding_provider) -> None:
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        assert hasattr(store, "search")
        assert callable(store.search)

    def test_find_similar_method_exists(self, mock_embedding_provider) -> None:
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        assert hasattr(store, "find_similar")
        assert callable(store.find_similar)

    def test_list_entries_method_exists(self, mock_embedding_provider) -> None:
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        assert hasattr(store, "list_entries")
        assert callable(store.list_entries)

    def test_all_protocol_methods_are_coroutines(self, mock_embedding_provider) -> None:
        """Every required method must be an async coroutine function."""
        method_names = [
            "store",
            "get",
            "update",
            "delete",
            "search",
            "find_similar",
            "list_entries",
            "get_metadata",
            "set_metadata",
        ]
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        for name in method_names:
            method = getattr(store, name)
            assert inspect.iscoroutinefunction(method), (
                f"Expected {name!r} to be a coroutine function"
            )

    def test_protocol_method_signatures_match_store(self) -> None:
        """Parameter names on DuckDBStore must match the Protocol."""
        # store(entry)
        sig = inspect.signature(DuckDBStore.store)
        assert "entry" in sig.parameters

        # get(entry_id)
        sig = inspect.signature(DuckDBStore.get)
        assert "entry_id" in sig.parameters

        # update(entry_id, updates)
        sig = inspect.signature(DuckDBStore.update)
        assert "entry_id" in sig.parameters
        assert "updates" in sig.parameters

        # delete(entry_id)
        sig = inspect.signature(DuckDBStore.delete)
        assert "entry_id" in sig.parameters

        # search(query, filters, limit)
        sig = inspect.signature(DuckDBStore.search)
        assert "query" in sig.parameters
        assert "filters" in sig.parameters
        assert "limit" in sig.parameters

        # find_similar(content, threshold, limit)
        sig = inspect.signature(DuckDBStore.find_similar)
        assert "content" in sig.parameters
        assert "threshold" in sig.parameters
        assert "limit" in sig.parameters

        # list_entries(filters, limit, offset)
        sig = inspect.signature(DuckDBStore.list_entries)
        assert "filters" in sig.parameters
        assert "limit" in sig.parameters
        assert "offset" in sig.parameters
