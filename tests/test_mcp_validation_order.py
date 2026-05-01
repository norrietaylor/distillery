"""Tests for issue #372: schema-level validation must run before DB lookup.

When a ``distillery_classify`` or ``distillery_resolve_review`` call carries
both a bad ``entry_id`` and an invalid enum / action, the response should
surface the schema-level failure (``INVALID_PARAMS``) rather than
short-circuiting on the ownership pre-check / handler ``store.get`` and
returning ``NOT_FOUND``.

The fix lives in two places:
  * ``server.py`` — the tool wrappers call ``validate_classify_schema`` /
    ``validate_resolve_review_schema`` *before* the ownership pre-check
    (``_own``), so HTTP/OAuth callers get the enum failure on the first
    round-trip.
  * ``tools/classify.py`` — the handlers themselves run the same validators
    first thing so direct handler calls (tests, webhook entrypoints) get
    the same ordering guarantee.

Both layers are exercised below.
"""

from __future__ import annotations

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.tools.classify import (
    _handle_classify,
    _handle_resolve_review,
    validate_classify_schema,
    validate_resolve_review_schema,
)
from distillery.store.duckdb import DuckDBStore
from tests.conftest import parse_mcp_response

pytestmark = pytest.mark.unit


_BOGUS_ID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Pure-schema validators (no store needed)
# ---------------------------------------------------------------------------


class TestValidateClassifySchema:
    """``validate_classify_schema`` is the pure-schema gatekeeper."""

    def test_returns_invalid_params_for_unknown_entry_type(self) -> None:
        """Unknown entry_type surfaces INVALID_PARAMS even when entry_id is also bogus."""
        result = validate_classify_schema(
            {
                "entry_id": _BOGUS_ID,
                "entry_type": "invalid_type_xyz",
                "confidence": 0.5,
            }
        )
        assert result is not None
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert data["details"]["field"] == "entry_type"
        assert data["details"]["provided"] == "invalid_type_xyz"
        assert "session" in data["details"]["allowed"]

    def test_alias_surfaces_suggestion(self) -> None:
        """Aliases like 'note' surface a canonical suggestion in details."""
        result = validate_classify_schema(
            {"entry_id": _BOGUS_ID, "entry_type": "note", "confidence": 0.5}
        )
        assert result is not None
        data = parse_mcp_response(result)
        assert data["details"]["suggestion"] == "inbox"

    def test_returns_invalid_params_for_confidence_out_of_range(self) -> None:
        result = validate_classify_schema(
            {"entry_id": _BOGUS_ID, "entry_type": "session", "confidence": 1.5}
        )
        assert result is not None
        data = parse_mcp_response(result)
        assert data["code"] == "INVALID_PARAMS"
        assert "confidence" in data["message"]

    def test_returns_invalid_params_for_non_numeric_confidence(self) -> None:
        result = validate_classify_schema(
            {"entry_id": _BOGUS_ID, "entry_type": "session", "confidence": "high"}
        )
        assert result is not None
        data = parse_mcp_response(result)
        assert data["code"] == "INVALID_PARAMS"

    def test_rejects_bool_confidence(self) -> None:
        """``bool`` is a subclass of ``int`` in Python; reject it explicitly."""
        result = validate_classify_schema(
            {"entry_id": _BOGUS_ID, "entry_type": "session", "confidence": True}
        )
        assert result is not None
        data = parse_mcp_response(result)
        assert data["code"] == "INVALID_PARAMS"

    def test_returns_none_when_all_valid(self) -> None:
        assert (
            validate_classify_schema(
                {"entry_id": _BOGUS_ID, "entry_type": "session", "confidence": 0.5}
            )
            is None
        )

    def test_missing_required_field(self) -> None:
        result = validate_classify_schema({"entry_id": _BOGUS_ID})
        assert result is not None
        data = parse_mcp_response(result)
        assert data["code"] == "INVALID_PARAMS"
        assert "Missing required" in data["message"]


class TestValidateResolveReviewSchema:
    """``validate_resolve_review_schema`` is the pure-schema gatekeeper."""

    def test_returns_invalid_params_for_unknown_action(self) -> None:
        """Unknown action surfaces INVALID_PARAMS even when entry_id is also bogus."""
        result = validate_resolve_review_schema(
            {"entry_id": _BOGUS_ID, "action": "nuke_from_orbit"}
        )
        assert result is not None
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "nuke_from_orbit" in data["message"]
        assert "approve" in data["message"]

    def test_reclassify_requires_new_entry_type(self) -> None:
        result = validate_resolve_review_schema({"entry_id": _BOGUS_ID, "action": "reclassify"})
        assert result is not None
        data = parse_mcp_response(result)
        assert data["code"] == "INVALID_PARAMS"
        assert "new_entry_type" in data["message"]

    def test_reclassify_with_invalid_new_entry_type(self) -> None:
        result = validate_resolve_review_schema(
            {
                "entry_id": _BOGUS_ID,
                "action": "reclassify",
                "new_entry_type": "bogus_type",
            }
        )
        assert result is not None
        data = parse_mcp_response(result)
        assert data["code"] == "INVALID_PARAMS"
        assert data["details"]["field"] == "new_entry_type"

    def test_returns_none_when_action_valid(self) -> None:
        assert validate_resolve_review_schema({"entry_id": _BOGUS_ID, "action": "approve"}) is None

    def test_missing_required_field(self) -> None:
        result = validate_resolve_review_schema({"entry_id": _BOGUS_ID})
        assert result is not None
        data = parse_mcp_response(result)
        assert data["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# Handler-level checks (verify validation order survives a bogus DB lookup)
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(deterministic_embedding_provider):  # type: ignore[no-untyped-def]
    s = DuckDBStore(db_path=":memory:", embedding_provider=deterministic_embedding_provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def config() -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        classification=ClassificationConfig(confidence_threshold=0.6),
    )


class TestClassifyValidationOrder:
    """Issue #372: bad entry_id + bad entry_type surfaces INVALID_PARAMS, not NOT_FOUND."""

    async def test_bad_id_and_bad_entry_type_returns_invalid_params(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Reproduces the exact case from issue #372."""
        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": _BOGUS_ID,
                "entry_type": "invalid_type_xyz",
                "confidence": 0.5,
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        # The schema check must surface the bad entry_type, not the missing entry.
        assert data["details"]["field"] == "entry_type"
        assert "NOT_FOUND" not in data["code"]

    async def test_bad_id_with_valid_entry_type_still_returns_not_found(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Sanity: if schema is valid, NOT_FOUND still surfaces (no regression)."""
        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": _BOGUS_ID,
                "entry_type": "session",
                "confidence": 0.8,
            },
        )
        data = parse_mcp_response(response)
        assert data["code"] == "NOT_FOUND"


class TestResolveReviewValidationOrder:
    """Issue #372: bad entry_id + bad action surfaces INVALID_PARAMS, not NOT_FOUND."""

    async def test_bad_id_and_bad_action_returns_invalid_params(self, store: DuckDBStore) -> None:
        """Reproduces the exact case from issue #372."""
        response = await _handle_resolve_review(
            store,
            {"entry_id": _BOGUS_ID, "action": "nuke_from_orbit"},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "nuke_from_orbit" in data["message"]

    async def test_bad_id_and_reclassify_with_bad_new_type_returns_invalid_params(
        self, store: DuckDBStore
    ) -> None:
        """Reclassify with a bogus new_entry_type also surfaces INVALID_PARAMS."""
        response = await _handle_resolve_review(
            store,
            {
                "entry_id": _BOGUS_ID,
                "action": "reclassify",
                "new_entry_type": "bogus_type",
            },
        )
        data = parse_mcp_response(response)
        assert data["code"] == "INVALID_PARAMS"
        assert data["details"]["field"] == "new_entry_type"

    async def test_bad_id_with_valid_action_still_returns_not_found(
        self, store: DuckDBStore
    ) -> None:
        """Sanity: if schema is valid, NOT_FOUND still surfaces (no regression)."""
        response = await _handle_resolve_review(
            store,
            {"entry_id": _BOGUS_ID, "action": "approve"},
        )
        data = parse_mcp_response(response)
        assert data["code"] == "NOT_FOUND"
