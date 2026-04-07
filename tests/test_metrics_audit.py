"""Tests for distillery_metrics with scope="audit" (T03).

Covers:
- scope="audit" returns all 4 sections: recent_logins, login_summary, active_users,
  recent_operations
- empty audit log returns zeroed login_summary and empty lists
- recent_logins contains only auth events (auth_login, auth_login_failed, auth_org_denied)
- recent_operations excludes auth events
- login_summary totals are correct (total_logins, unique_users, failed_attempts, org_denials)
- active_users built from all operations, ordered by last_seen DESC
- date_from filters narrow results across sections
- user filter narrows recent_operations and active_users only
- incompatible params (entry_type) return INVALID_PARAMS error
- invalid date_from type returns INVALID_PARAMS error
- invalid user type returns INVALID_PARAMS error
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.tools.analytics import _handle_metrics
from distillery.store.duckdb import DuckDBStore
from tests.conftest import MockEmbeddingProvider

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config() -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="mock-hash-4d", dimensions=4),
        classification=ClassificationConfig(confidence_threshold=0.6),
    )


def _parse(content: list) -> dict:  # type: ignore[type-arg]
    assert len(content) == 1
    return json.loads(content[0].text)  # type: ignore[no-any-return]


async def _audit(
    store: DuckDBStore,
    *,
    date_from: str | None = None,
    user: str | None = None,
    extra: dict | None = None,  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    """Call _handle_metrics with scope='audit' and return parsed response."""
    args: dict = {"scope": "audit"}  # type: ignore[type-arg]
    if date_from is not None:
        args["date_from"] = date_from
    if user is not None:
        args["user"] = user
    if extra:
        args.update(extra)
    config = _make_config()
    ep = MockEmbeddingProvider()
    response = await _handle_metrics(store, config, ep, args)
    return _parse(response)


async def _write(
    store: DuckDBStore,
    *,
    user_id: str = "alice",
    tool: str = "distill",
    entry_id: str = "e-1",
    action: str = "store",
    outcome: str = "success",
) -> None:
    await store.write_audit_log(
        user_id=user_id,
        tool=tool,
        entry_id=entry_id,
        action=action,
        outcome=outcome,
    )


def _ts_future(seconds: int = 0) -> str:
    """Return an ISO 8601 timestamp slightly in the future (to ensure ordering)."""
    dt = datetime.now(UTC) + timedelta(seconds=seconds)
    return dt.isoformat()


def _ts_past(days: float) -> str:
    dt = datetime.now(UTC) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store() -> AsyncGenerator[DuckDBStore, None]:
    s = DuckDBStore(db_path=":memory:", embedding_provider=MockEmbeddingProvider())
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# 1. Response structure
# ---------------------------------------------------------------------------


class TestAuditResponseStructure:
    async def test_all_four_sections_present(self, store: DuckDBStore) -> None:
        data = await _audit(store)
        assert set(data.keys()) >= {"recent_logins", "login_summary", "active_users",
                                     "recent_operations"}

    async def test_login_summary_keys_present(self, store: DuckDBStore) -> None:
        data = await _audit(store)
        summary = data["login_summary"]
        assert set(summary.keys()) >= {
            "total_logins", "unique_users", "failed_attempts", "org_denials"
        }


# ---------------------------------------------------------------------------
# 2. Empty audit log
# ---------------------------------------------------------------------------


class TestEmptyAuditLog:
    async def test_empty_returns_zeroed_summary(self, store: DuckDBStore) -> None:
        data = await _audit(store)
        summary = data["login_summary"]
        assert summary["total_logins"] == 0
        assert summary["unique_users"] == 0
        assert summary["failed_attempts"] == 0
        assert summary["org_denials"] == 0

    async def test_empty_returns_empty_lists(self, store: DuckDBStore) -> None:
        data = await _audit(store)
        assert data["recent_logins"] == []
        assert data["active_users"] == []
        assert data["recent_operations"] == []


# ---------------------------------------------------------------------------
# 3. Auth events in recent_logins
# ---------------------------------------------------------------------------


class TestRecentLogins:
    async def test_auth_login_appears_in_recent_logins(self, store: DuckDBStore) -> None:
        await _write(store, user_id="alice", tool="auth_login")
        data = await _audit(store)
        tools_in_logins = [r["tool"] for r in data["recent_logins"]]
        assert "auth_login" in tools_in_logins

    async def test_auth_login_failed_appears_in_recent_logins(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="bob", tool="auth_login_failed")
        data = await _audit(store)
        tools_in_logins = [r["tool"] for r in data["recent_logins"]]
        assert "auth_login_failed" in tools_in_logins

    async def test_auth_org_denied_appears_in_recent_logins(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="carol", tool="auth_org_denied")
        data = await _audit(store)
        tools_in_logins = [r["tool"] for r in data["recent_logins"]]
        assert "auth_org_denied" in tools_in_logins

    async def test_non_auth_tool_excluded_from_recent_logins(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="recall")
        data = await _audit(store)
        assert data["recent_logins"] == []

    async def test_mixed_tools_only_auth_in_recent_logins(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="auth_login")
        await _write(store, user_id="alice", tool="recall")
        await _write(store, user_id="alice", tool="distill")
        data = await _audit(store)
        assert len(data["recent_logins"]) == 1
        assert data["recent_logins"][0]["tool"] == "auth_login"


# ---------------------------------------------------------------------------
# 4. Recent operations (non-auth)
# ---------------------------------------------------------------------------


class TestRecentOperations:
    async def test_non_auth_appears_in_recent_operations(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="recall")
        data = await _audit(store)
        tools = [r["tool"] for r in data["recent_operations"]]
        assert "recall" in tools

    async def test_auth_excluded_from_recent_operations(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="auth_login")
        data = await _audit(store)
        assert data["recent_operations"] == []

    async def test_mixed_tools_only_non_auth_in_operations(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="auth_login")
        await _write(store, user_id="alice", tool="recall")
        await _write(store, user_id="alice", tool="distill")
        data = await _audit(store)
        ops_tools = {r["tool"] for r in data["recent_operations"]}
        assert ops_tools == {"recall", "distill"}
        assert "auth_login" not in ops_tools


# ---------------------------------------------------------------------------
# 5. login_summary totals
# ---------------------------------------------------------------------------


class TestLoginSummary:
    async def test_total_logins_counts_auth_login_only(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="auth_login")
        await _write(store, user_id="bob", tool="auth_login")
        await _write(store, user_id="carol", tool="auth_login_failed")
        data = await _audit(store)
        assert data["login_summary"]["total_logins"] == 2

    async def test_failed_attempts_counts_auth_login_failed(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="auth_login_failed")
        await _write(store, user_id="alice", tool="auth_login_failed")
        data = await _audit(store)
        assert data["login_summary"]["failed_attempts"] == 2

    async def test_org_denials_counts_auth_org_denied(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="auth_org_denied")
        data = await _audit(store)
        assert data["login_summary"]["org_denials"] == 1

    async def test_unique_users_counts_distinct_user_ids(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="auth_login")
        await _write(store, user_id="alice", tool="auth_login")
        await _write(store, user_id="bob", tool="auth_login")
        data = await _audit(store)
        assert data["login_summary"]["unique_users"] == 2


# ---------------------------------------------------------------------------
# 6. active_users
# ---------------------------------------------------------------------------


class TestActiveUsers:
    async def test_active_users_has_correct_fields(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="recall")
        data = await _audit(store)
        assert len(data["active_users"]) == 1
        user_row = data["active_users"][0]
        assert "user_id" in user_row
        assert "last_seen" in user_row
        assert "operation_count" in user_row

    async def test_active_users_counts_operations_per_user(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="recall")
        await _write(store, user_id="alice", tool="distill")
        await _write(store, user_id="bob", tool="recall")
        data = await _audit(store)
        by_user = {u["user_id"]: u for u in data["active_users"]}
        assert by_user["alice"]["operation_count"] == 2
        assert by_user["bob"]["operation_count"] == 1

    async def test_active_users_ordered_by_last_seen_desc(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="recall")
        await _write(store, user_id="bob", tool="distill")
        data = await _audit(store)
        # Just confirm ordering is desc (bob wrote last)
        if len(data["active_users"]) == 2:  # noqa: SIM108
            first = data["active_users"][0]["last_seen"]
            second = data["active_users"][1]["last_seen"]
            assert first >= second


# ---------------------------------------------------------------------------
# 7. date_from filtering
# ---------------------------------------------------------------------------


class TestDateFromFilter:
    async def test_date_from_excludes_old_operations(
        self, store: DuckDBStore
    ) -> None:
        # Write an old auth_login and a recent one.
        # We can only control timestamps via direct DB insertion.
        conn = store.connection

        import uuid as _uuid

        old_ts = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO audit_log (id, user_id, tool, entry_id, action, outcome, timestamp) "
            "VALUES (?, 'alice', 'auth_login', 'e-old', 'login', 'success', ?)",
            [str(_uuid.uuid4()), old_ts],
        )

        recent_ts = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO audit_log (id, user_id, tool, entry_id, action, outcome, timestamp) "
            "VALUES (?, 'alice', 'auth_login', 'e-new', 'login', 'success', ?)",
            [str(_uuid.uuid4()), recent_ts],
        )

        cutoff = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        data = await _audit(store, date_from=cutoff)
        assert len(data["recent_logins"]) == 1
        assert data["recent_logins"][0]["entry_id"] == "e-new"

    async def test_date_from_filters_recent_operations(
        self, store: DuckDBStore
    ) -> None:
        conn = store.connection
        import uuid as _uuid

        old_ts = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO audit_log (id, user_id, tool, entry_id, action, outcome, timestamp) "
            "VALUES (?, 'alice', 'recall', 'e-old', 'retrieve', 'success', ?)",
            [str(_uuid.uuid4()), old_ts],
        )
        recent_ts = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO audit_log (id, user_id, tool, entry_id, action, outcome, timestamp) "
            "VALUES (?, 'alice', 'recall', 'e-new', 'retrieve', 'success', ?)",
            [str(_uuid.uuid4()), recent_ts],
        )

        cutoff = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        data = await _audit(store, date_from=cutoff)
        assert len(data["recent_operations"]) == 1
        assert data["recent_operations"][0]["entry_id"] == "e-new"


# ---------------------------------------------------------------------------
# 8. user filtering
# ---------------------------------------------------------------------------


class TestUserFilter:
    async def test_user_filter_narrows_recent_operations(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="recall")
        await _write(store, user_id="bob", tool="recall")
        data = await _audit(store, user="alice")
        for row in data["recent_operations"]:
            assert row["user_id"] == "alice"

    async def test_user_filter_narrows_active_users(
        self, store: DuckDBStore
    ) -> None:
        await _write(store, user_id="alice", tool="recall")
        await _write(store, user_id="bob", tool="recall")
        data = await _audit(store, user="alice")
        user_ids = {u["user_id"] for u in data["active_users"]}
        assert user_ids == {"alice"}

    async def test_user_filter_does_not_affect_login_summary(
        self, store: DuckDBStore
    ) -> None:
        """login_summary is based on recent_logins which uses only date_from, not user."""
        await _write(store, user_id="alice", tool="auth_login")
        await _write(store, user_id="bob", tool="auth_login")
        # Filter by alice — login_summary should still reflect all auth events
        data = await _audit(store, user="alice")
        # recent_logins uses base_filters (no user filter), so both logins appear
        assert data["login_summary"]["total_logins"] == 2


# ---------------------------------------------------------------------------
# 9. Incompatible params
# ---------------------------------------------------------------------------


class TestIncompatibleParams:
    async def test_entry_type_with_audit_scope_returns_error(
        self, store: DuckDBStore
    ) -> None:
        config = _make_config()
        ep = MockEmbeddingProvider()
        response = await _handle_metrics(
            store, config, ep, {"scope": "audit", "entry_type": "note"}
        )
        data = _parse(response)
        assert data.get("error") is not None or "error_code" in data or "error" in str(data)
        # More precisely: check the error_code field in the response
        assert data.get("error_code") == "INVALID_PARAMS" or (
            "INVALID_PARAMS" in str(data)
        )

    async def test_invalid_date_from_type_returns_error(
        self, store: DuckDBStore
    ) -> None:
        config = _make_config()
        ep = MockEmbeddingProvider()
        response = await _handle_metrics(
            store, config, ep, {"scope": "audit", "date_from": 12345}
        )
        data = _parse(response)
        assert "INVALID_PARAMS" in str(data)

    async def test_invalid_date_from_format_returns_error(
        self, store: DuckDBStore
    ) -> None:
        config = _make_config()
        ep = MockEmbeddingProvider()
        response = await _handle_metrics(
            store, config, ep, {"scope": "audit", "date_from": "not-a-date"}
        )
        data = _parse(response)
        assert "INVALID_PARAMS" in str(data)
        assert "ISO 8601" in str(data)

    async def test_invalid_user_type_returns_error(
        self, store: DuckDBStore
    ) -> None:
        config = _make_config()
        ep = MockEmbeddingProvider()
        response = await _handle_metrics(
            store, config, ep, {"scope": "audit", "user": 99}
        )
        data = _parse(response)
        assert "INVALID_PARAMS" in str(data)
