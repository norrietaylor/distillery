"""Tests for ``distillery_store`` dedup response contract (issues #314, #332).

Verifies that the ``_handle_store`` tool handler always surfaces:

* ``persisted`` (bool)
* ``dedup_action`` — one of ``stored`` or ``skipped``

When a near-duplicate is auto-skipped the returned ``entry_id`` is the
*existing* entry's id (never a ghost id that was never inserted), and
``existing_entry_id`` plus ``similarity`` are supplied so the caller can
pivot.

Per issue #332, when a new row IS persisted independently, ``dedup_action``
is always ``"stored"`` regardless of similarity to existing entries.  The
similarity signal is surfaced via the informational ``existing_entry_id`` /
``similarity`` fields when the top match crosses the merge or link
threshold, but ``dedup_action`` stays ``"stored"`` to honestly reflect that
a separate row was created.  ``"merged"`` / ``"linked"`` are reserved for
future behaviour where content is actually folded into an existing row.
"""

from __future__ import annotations

import math

import pytest

from distillery.config import (
    ClassificationConfig,
    DefaultsConfig,
    DistilleryConfig,
    EmbeddingConfig,
    RateLimitConfig,
    StorageConfig,
)
from distillery.mcp.tools.crud import _handle_store, _handle_store_batch
from distillery.store.duckdb import DuckDBStore
from tests.conftest import ControlledEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider(controlled_embedding_provider):
    """Alias for the 8-dim controlled embedding provider."""
    return controlled_embedding_provider


@pytest.fixture
async def store(embedding_provider) -> DuckDBStore:  # type: ignore[return]
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


def _make_config(
    *,
    skip: float = 0.95,
    merge: float = 0.80,
    link: float = 0.60,
    dedup_threshold: float = 0.60,
    dedup_limit: int = 5,
) -> DistilleryConfig:
    """Build a DistilleryConfig with controllable dedup thresholds.

    The ``dedup_threshold`` (on DefaultsConfig) drives which similar entries
    ``_handle_store`` collects as warnings; the classification thresholds
    drive the auto-skip decision and (per issue #332) whether the response
    carries an informational ``existing_entry_id`` / ``similarity`` hint.
    ``dedup_action`` is only ever ``"stored"`` or ``"skipped"``.
    """
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="controlled-8d", dimensions=8),
        classification=ClassificationConfig(
            confidence_threshold=0.6,
            dedup_skip_threshold=skip,
            dedup_merge_threshold=merge,
            dedup_link_threshold=link,
            dedup_limit=dedup_limit,
        ),
        defaults=DefaultsConfig(
            dedup_threshold=dedup_threshold,
            dedup_limit=dedup_limit,
        ),
        rate_limit=RateLimitConfig(),
    )


# ---------------------------------------------------------------------------
# Helper vectors
# ---------------------------------------------------------------------------

_UNIT_A = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
_UNIT_B = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _interpolated_vector(a: list[float], b: list[float], t: float) -> list[float]:
    """Return an L2-normalised vector between *a* and *b* (t=0 -> a, t=1 -> b)."""
    vec = [a[i] * (1.0 - t) + b[i] * t for i in range(len(a))]
    magnitude = math.sqrt(sum(x * x for x in vec))
    return [x / magnitude for x in vec]


def _cosine(u: list[float], v: list[float]) -> float:
    return sum(a * b for a, b in zip(u, v, strict=True))


# ---------------------------------------------------------------------------
# Test: fresh entry -> persisted=True, dedup_action="stored"
# ---------------------------------------------------------------------------


class TestStoreFreshEntry:
    async def test_fresh_entry_is_persisted_and_stored(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        embedding_provider.register("A brand new thought", _UNIT_A)
        cfg = _make_config()

        result = await _handle_store(
            store,
            {
                "content": "A brand new thought",
                "entry_type": "idea",
                "author": "alice",
            },
            cfg=cfg,
        )
        data = parse_mcp_response(result)

        assert data.get("error") is not True, data
        assert "entry_id" in data
        assert data["persisted"] is True
        assert data["dedup_action"] == "stored"
        assert "existing_entry_id" not in data
        assert "similarity" not in data

        # The returned entry_id must resolve via store.get
        fetched = await store.get(data["entry_id"])
        assert fetched is not None
        assert fetched.content == "A brand new thought"


# ---------------------------------------------------------------------------
# Test: near-dup (sim >= 0.95) -> persisted=False, dedup_action="skipped"
# ---------------------------------------------------------------------------


class TestStoreNearDuplicateSkipped:
    async def test_near_duplicate_is_auto_skipped(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        # Seed an existing entry
        existing_text = "Existing near-duplicate source"
        new_text = "Near-duplicate new arrival"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(new_text, _UNIT_A)  # identical cos sim = 1.0

        existing_entry = make_entry(content=existing_text, author="bob")
        existing_id = await store.store(existing_entry)

        cfg = _make_config(skip=0.95, dedup_threshold=0.60)
        result = await _handle_store(
            store,
            {
                "content": new_text,
                "entry_type": "idea",
                "author": "alice",
            },
            cfg=cfg,
        )
        data = parse_mcp_response(result)

        assert data.get("error") is not True, data
        assert data["persisted"] is False
        assert data["dedup_action"] == "skipped"
        assert data["existing_entry_id"] == existing_id
        # entry_id must be the existing one (not a ghost)
        assert data["entry_id"] == existing_id
        assert "similarity" in data
        assert data["similarity"] >= 0.95

        # Only one entry should exist in the store: the pre-existing one.
        fetched = await store.get(existing_id)
        assert fetched is not None
        # ``count_entries`` reports the total — it must still be 1.
        total = await store.count_entries(filters=None)
        assert total == 1

    async def test_skipped_entry_id_is_retrievable(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """The id returned on skip must be retrievable via store.get — no ghost ids."""
        existing_text = "Prior note"
        new_text = "Prior note duplicate"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(new_text, _UNIT_A)

        existing_id = await store.store(make_entry(content=existing_text))

        cfg = _make_config(skip=0.95, dedup_threshold=0.60)
        result = await _handle_store(
            store,
            {
                "content": new_text,
                "entry_type": "idea",
                "author": "alice",
            },
            cfg=cfg,
        )
        data = parse_mcp_response(result)
        assert data["persisted"] is False
        entry = await store.get(data["entry_id"])
        assert entry is not None
        assert entry.id == existing_id


# ---------------------------------------------------------------------------
# Test: similar (merge band) -> persisted=True, dedup_action="stored" +
#       informational existing_entry_id / similarity hint (issue #332)
# ---------------------------------------------------------------------------


class TestStoreDuplicateMergeBand:
    async def test_merge_band_is_persisted_as_stored_with_similarity_hint(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """A new row above the merge threshold is still reported as ``stored``.

        Per issue #332, ``dedup_action`` must honestly reflect that a new
        separate row was created.  The similarity to the existing entry is
        still available via ``existing_entry_id`` + ``similarity`` as an
        informational hint, but ``dedup_action`` stays ``"stored"``.
        """
        existing_vec = _UNIT_A
        # Interpolate so cosine sim falls between merge (0.80) and skip (0.95)
        # normalized.  Raw cos from interp with t=0.3 ~ 0.89, normalised to
        # (0.89 + 1) / 2 = ~0.945.  We widen bands around norm_sim to avoid
        # flakiness.
        interp = _interpolated_vector(_UNIT_A, _UNIT_B, 0.3)
        cos_sim = _cosine(interp, existing_vec)
        norm_sim = (cos_sim + 1.0) / 2.0

        existing_text = "Merge band existing content"
        new_text = "Merge band arriving content"
        embedding_provider.register(existing_text, existing_vec)
        embedding_provider.register(new_text, interp)

        existing_id = await store.store(make_entry(content=existing_text))

        # Thresholds: skip above norm_sim (no skip), merge below norm_sim
        # (so score lands in merge band), link very low.
        cfg = _make_config(
            skip=norm_sim + 0.01,
            merge=norm_sim - 0.01,
            link=0.0,
            dedup_threshold=0.0,
        )
        result = await _handle_store(
            store,
            {
                "content": new_text,
                "entry_type": "idea",
                "author": "alice",
            },
            cfg=cfg,
        )
        data = parse_mcp_response(result)

        assert data.get("error") is not True, data
        assert data["persisted"] is True
        # Per issue #332, a new independent row is always ``stored``.
        assert data["dedup_action"] == "stored"
        # The similarity signal remains as an informational hint.
        assert data["existing_entry_id"] == existing_id
        assert data["entry_id"] != existing_id  # new row was written
        assert data["similarity"] >= cfg.classification.dedup_merge_threshold

        # The newly written id must be retrievable.
        new_entry = await store.get(data["entry_id"])
        assert new_entry is not None
        assert new_entry.content == new_text


# ---------------------------------------------------------------------------
# Test: related (link band) -> persisted=True, dedup_action="stored" +
#       informational existing_entry_id / similarity hint (issue #332)
# ---------------------------------------------------------------------------


class TestStoreRelatedLinkBand:
    async def test_link_band_is_persisted_as_stored_with_similarity_hint(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """A new row above the link threshold is still reported as ``stored``.

        As with the merge band (issue #332), a new independent row must
        report ``dedup_action="stored"`` — the link-band similarity is
        surfaced informationally only.
        """
        existing_vec = _UNIT_A
        interp = _interpolated_vector(_UNIT_A, _UNIT_B, 0.7)  # lower similarity
        cos_sim = _cosine(interp, existing_vec)
        norm_sim = (cos_sim + 1.0) / 2.0

        existing_text = "Link band existing content"
        new_text = "Link band arriving content"
        embedding_provider.register(existing_text, existing_vec)
        embedding_provider.register(new_text, interp)

        existing_id = await store.store(make_entry(content=existing_text))

        cfg = _make_config(
            skip=0.99,
            merge=norm_sim + 0.01,
            link=norm_sim - 0.01,
            dedup_threshold=0.0,
        )
        result = await _handle_store(
            store,
            {
                "content": new_text,
                "entry_type": "idea",
                "author": "alice",
            },
            cfg=cfg,
        )
        data = parse_mcp_response(result)

        assert data.get("error") is not True, data
        assert data["persisted"] is True
        # Per issue #332, a new independent row is always ``stored``.
        assert data["dedup_action"] == "stored"
        # The similarity signal remains as an informational hint.
        assert data["existing_entry_id"] == existing_id
        assert data["entry_id"] != existing_id
        assert data["similarity"] >= cfg.classification.dedup_link_threshold
        assert data["similarity"] < cfg.classification.dedup_merge_threshold


# ---------------------------------------------------------------------------
# Test: summary output_mode returns the new response contract too
# ---------------------------------------------------------------------------


class TestStoreSummaryMode:
    async def test_summary_mode_includes_persisted_and_action(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        embedding_provider.register("summary mode content", _UNIT_A)
        cfg = _make_config()

        result = await _handle_store(
            store,
            {
                "content": "summary mode content",
                "entry_type": "idea",
                "author": "alice",
                "output_mode": "summary",
            },
            cfg=cfg,
        )
        data = parse_mcp_response(result)
        assert data.get("error") is not True, data
        assert "entry_id" in data
        assert data["persisted"] is True
        assert data["dedup_action"] == "stored"


# ---------------------------------------------------------------------------
# Test: store_batch results include per-item persisted / dedup_action
# ---------------------------------------------------------------------------


class TestStoreBatchResponseShape:
    async def test_batch_results_include_persisted_and_action(
        self,
        store: DuckDBStore,
    ) -> None:
        result = await _handle_store_batch(
            store=store,
            arguments={
                "entries": [
                    {"content": "Batch first", "author": "alice", "entry_type": "inbox"},
                    {"content": "Batch second", "author": "bob", "entry_type": "idea"},
                ],
            },
        )
        data = parse_mcp_response(result)
        assert data.get("error") is not True, data
        assert data["count"] == 2
        assert len(data["entry_ids"]) == 2
        assert "results" in data
        assert len(data["results"]) == 2
        for item in data["results"]:
            assert item["persisted"] is True
            assert item["dedup_action"] == "stored"
            assert "entry_id" in item
        # Sanity: results and entry_ids align in order
        assert [r["entry_id"] for r in data["results"]] == data["entry_ids"]

    async def test_batch_empty_list_has_results_key(
        self,
        store: DuckDBStore,
    ) -> None:
        result = await _handle_store_batch(
            store=store,
            arguments={"entries": []},
        )
        data = parse_mcp_response(result)
        assert data["entry_ids"] == []
        assert data["results"] == []
        assert data["count"] == 0
