"""Tests for the orthogonal verification field on entries."""

from __future__ import annotations

import pytest

from distillery.models import EntryStatus, VerificationStatus

# Re-use fixtures from conftest (store, make_entry, parse_mcp_response).
from tests.conftest import make_entry, parse_mcp_response

pytestmark = pytest.mark.unit


class TestVerificationDefault:
    """Entries stored without an explicit verification get UNVERIFIED."""

    @pytest.mark.asyncio
    async def test_store_default_verification(self, store):
        entry = make_entry(content="default verification entry")
        entry_id = await store.store(entry)
        fetched = await store.get(entry_id)
        assert fetched is not None
        assert fetched.verification == VerificationStatus.UNVERIFIED
        assert fetched.verification.value == "unverified"


class TestVerificationExplicit:
    """Entries can be stored with an explicit verification value."""

    @pytest.mark.asyncio
    async def test_store_with_testing(self, store):
        entry = make_entry(
            content="testing verification entry",
            verification=VerificationStatus.TESTING,
        )
        entry_id = await store.store(entry)
        fetched = await store.get(entry_id)
        assert fetched is not None
        assert fetched.verification == VerificationStatus.TESTING

    @pytest.mark.asyncio
    async def test_store_with_verified(self, store):
        entry = make_entry(
            content="verified entry",
            verification=VerificationStatus.VERIFIED,
        )
        entry_id = await store.store(entry)
        fetched = await store.get(entry_id)
        assert fetched is not None
        assert fetched.verification == VerificationStatus.VERIFIED


class TestVerificationUpdate:
    """Verification can be updated independently of status."""

    @pytest.mark.asyncio
    async def test_update_verification(self, store):
        entry = make_entry(content="entry to verify later")
        entry_id = await store.store(entry)

        updated = await store.update(entry_id, {"verification": VerificationStatus.VERIFIED})
        assert updated.verification == VerificationStatus.VERIFIED

        # Status should be unchanged.
        assert updated.status == EntryStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_update_status_preserves_verification(self, store):
        entry = make_entry(
            content="verified then archived",
            verification=VerificationStatus.VERIFIED,
        )
        entry_id = await store.store(entry)

        updated = await store.update(entry_id, {"status": EntryStatus.ARCHIVED})
        assert updated.status == EntryStatus.ARCHIVED
        assert updated.verification == VerificationStatus.VERIFIED


class TestVerificationFilter:
    """Entries can be filtered by verification status via list_entries."""

    @pytest.mark.asyncio
    async def test_filter_by_verification(self, store):
        e1 = make_entry(content="unverified one")
        e2 = make_entry(content="verified one", verification=VerificationStatus.VERIFIED)
        e3 = make_entry(content="testing one", verification=VerificationStatus.TESTING)
        await store.store(e1)
        await store.store(e2)
        await store.store(e3)

        results = await store.list_entries(
            filters={"verification": "verified"},
            limit=10,
            offset=0,
        )
        assert len(results) == 1
        assert results[0].verification == VerificationStatus.VERIFIED

        results_testing = await store.list_entries(
            filters={"verification": "testing"},
            limit=10,
            offset=0,
        )
        assert len(results_testing) == 1
        assert results_testing[0].verification == VerificationStatus.TESTING


class TestVerificationRoundtrip:
    """Entry roundtrip through to_dict/from_dict preserves verification."""

    def test_roundtrip(self):
        entry = make_entry(
            content="roundtrip test",
            verification=VerificationStatus.TESTING,
        )
        d = entry.to_dict()
        assert d["verification"] == "testing"

        restored = type(entry).from_dict(d)
        assert restored.verification == VerificationStatus.TESTING
        assert restored == entry

    def test_from_dict_defaults_to_unverified(self):
        """Old data without a verification key should default to unverified."""
        entry = make_entry(content="legacy entry")
        d = entry.to_dict()
        del d["verification"]

        restored = type(entry).from_dict(d)
        assert restored.verification == VerificationStatus.UNVERIFIED


class TestVerificationValidation:
    """Invalid verification values are rejected."""

    def test_invalid_enum_value(self):
        with pytest.raises(ValueError, match="'bogus' is not a valid VerificationStatus"):
            VerificationStatus("bogus")

    @pytest.mark.asyncio
    async def test_crud_rejects_invalid_verification(self, store):
        from distillery.mcp.tools.crud import _handle_store

        result = await _handle_store(
            store,
            {
                "content": "bad verification",
                "entry_type": "inbox",
                "author": "tester",
                "verification": "bogus",
            },
        )
        parsed = parse_mcp_response(result)
        assert parsed.get("code") == "INVALID_PARAMS"
        assert "verification" in parsed.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_crud_update_rejects_invalid_verification(self, store):
        from distillery.mcp.tools.crud import _handle_update

        entry = make_entry(content="update me")
        entry_id = await store.store(entry)

        result = await _handle_update(
            store,
            {"entry_id": entry_id, "verification": "bogus"},
        )
        parsed = parse_mcp_response(result)
        assert parsed.get("code") == "INVALID_PARAMS"
        assert "verification" in parsed.get("message", "").lower()
