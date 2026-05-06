"""Tests for :mod:`distillery.feeds.radar_selection`.

Exercises the namespace-aware tag picker the ``/radar`` skill uses to seed
its interest-driven feed search.  Issue #460: the previous top-N-by-count
rule always crowded out lower-ranked but conceptually-distinct tag clusters.
"""

from __future__ import annotations

import pytest

from distillery.feeds.radar_selection import (
    select_namespace_diverse_tags,
    tag_namespace,
)

pytestmark = pytest.mark.unit


class TestTagNamespace:
    def test_two_segment_tag_uses_first_segment(self) -> None:
        # ``tech/duckdb`` is prefix + leaf; the namespace is just ``tech``.
        assert tag_namespace("tech/duckdb") == "tech"

    def test_three_segment_tag_truncates_to_first_two_segments(self) -> None:
        assert tag_namespace("domain/build/hermeticity") == "domain/build"

    def test_four_segment_tag_caps_at_two_segments(self) -> None:
        assert tag_namespace("a/b/c/d") == "a/b"

    def test_single_segment_tag_namespaces_to_itself(self) -> None:
        assert tag_namespace("release") == "release"

    def test_empty_tag_returns_empty(self) -> None:
        assert tag_namespace("") == ""


class TestSelectNamespaceDiverseTags:
    def test_returns_empty_for_empty_counts(self) -> None:
        assert select_namespace_diverse_tags({}, top_n=3) == []

    def test_returns_empty_for_zero_top_n(self) -> None:
        assert select_namespace_diverse_tags({"foo/bar": 5}, top_n=0) == []

    def test_picks_highest_count_within_namespace(self) -> None:
        counts = {
            "domain/build/hermeticity": 4,
            "domain/build/cache": 7,
            "domain/build/wheels": 2,
        }
        # Only one namespace, so we get exactly one leader.
        assert select_namespace_diverse_tags(counts, top_n=3) == ["domain/build/cache"]

    def test_diversifies_across_namespaces(self) -> None:
        counts = {
            # domain/agents namespace dominates by total count, but other
            # namespaces still earn a slot under the new rule.
            "domain/agents/eval": 30,
            "domain/agents/orchestration": 25,
            "domain/agents/memory": 20,
            "tech/duckdb": 12,
            "tech/jina": 8,
            "domain/build/hermeticity": 6,
        }
        result = select_namespace_diverse_tags(counts, top_n=3)
        assert result == [
            "domain/agents/eval",
            "tech/duckdb",
            "domain/build/hermeticity",
        ]
        # Sanity: each chosen tag belongs to a distinct namespace.
        assert len({tag_namespace(t) for t in result}) == 3

    def test_acceptance_low_rank_namespace_still_wins_slot(self) -> None:
        """Issue #460 acceptance: a rank-<=5 tag in domain/build/* must
        appear in the default selection even though several higher-count
        tags share another namespace.
        """
        counts = {
            # Top-3 by raw count are all domain/agents/* — under the old
            # rule, domain/build/* tags (rank 4-5 by raw count) never got a
            # query slot.
            "domain/agents/eval": 30,
            "domain/agents/orchestration": 25,
            "domain/agents/memory": 20,
            "domain/build/hermeticity": 8,  # rank 4 by raw count
            "tech/duckdb": 6,  # rank 5 by raw count
            "domain/agents/tools": 5,
        }
        result = select_namespace_diverse_tags(counts, top_n=3)
        # At least one selected tag must come from domain/build/*.
        assert any(tag_namespace(t) == "domain/build" for t in result), result
        # And the namespaces must be distinct.
        assert len({tag_namespace(t) for t in result}) == 3

    def test_top_n_caps_returned_count(self) -> None:
        counts = {
            "domain/agents/eval": 10,
            "domain/build/hermeticity": 9,
            "tech/duckdb": 8,
            "source/github": 7,
        }
        result = select_namespace_diverse_tags(counts, top_n=2)
        assert len(result) == 2
        assert result[0] == "domain/agents/eval"

    def test_alphabetical_tiebreak_within_namespace(self) -> None:
        counts = {
            "domain/build/cache": 5,
            "domain/build/wheels": 5,
        }
        # Same count → alphabetical tag name wins.
        assert select_namespace_diverse_tags(counts, top_n=1) == ["domain/build/cache"]

    def test_alphabetical_tiebreak_across_namespaces(self) -> None:
        counts = {
            "tech/duckdb": 10,
            "domain/agents/eval": 10,
        }
        result = select_namespace_diverse_tags(counts, top_n=2)
        # Both leaders have the same count.  Namespace-name alphabetical
        # tie-break: "domain/agents" < "tech".
        assert result == ["domain/agents/eval", "tech/duckdb"]

    def test_single_segment_tags_namespace_independently(self) -> None:
        counts = {
            "release": 6,
            "feed": 4,
            "domain/agents/eval": 5,
        }
        result = select_namespace_diverse_tags(counts, top_n=3)
        # Three distinct namespaces: "release", "domain/agents", "feed".
        assert set(result) == {"release", "domain/agents/eval", "feed"}

    def test_float_counts_supported(self) -> None:
        counts: dict[str, int | float] = {
            "domain/agents/eval": 0.92,
            "domain/build/hermeticity": 0.87,
            "tech/duckdb": 0.81,
        }
        result = select_namespace_diverse_tags(counts, top_n=3)
        assert result == [
            "domain/agents/eval",
            "domain/build/hermeticity",
            "tech/duckdb",
        ]

    def test_namespace_aggregate_outranks_spiky_leader(self) -> None:
        """A broadly-populated namespace must outrank a namespace whose
        single spiky tag has a higher individual count.  This is the
        spec interpretation of "most-populated namespaces" from #460
        and prevents thin namespaces from monopolizing query slots.
        """
        counts = {
            # tech namespace: one spiky tag.
            "tech/rust": 20,
            # domain/build namespace: many smaller tags, aggregate dominates.
            "domain/build/hermeticity": 9,
            "domain/build/cache": 8,
            "domain/build/wheels": 7,
            "domain/build/reproducibility": 6,
            # domain/agents namespace: medium aggregate.
            "domain/agents/eval": 12,
            "domain/agents/orchestration": 5,
        }
        result = select_namespace_diverse_tags(counts, top_n=3)
        # Aggregate ranking: domain/build (30) > domain/agents (17) > tech (20).
        # Wait: tech is 20, domain/agents is 17 — so order is
        # domain/build (30), tech (20), domain/agents (17).
        assert result == [
            "domain/build/hermeticity",
            "tech/rust",
            "domain/agents/eval",
        ]

    def test_skips_empty_tag_strings(self) -> None:
        counts = {"": 100, "domain/agents/eval": 5}
        result = select_namespace_diverse_tags(counts, top_n=3)
        assert result == ["domain/agents/eval"]
