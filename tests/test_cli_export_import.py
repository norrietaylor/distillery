"""Comprehensive export/import tests and round-trip verification.

T03.3: tests for _cmd_export, _cmd_import, and the full export → import → export cycle.

Covers:
  1. test_export_creates_valid_json        — export from a seeded store
  2. test_export_excludes_embeddings       — no "embedding" key in entries
  3. test_import_merge_skips_existing      — merge mode skips duplicate IDs
  4. test_import_merge_adds_new            — merge mode inserts new IDs
  5. test_import_replace_drops_existing    — replace mode deletes all entries first
  6. test_import_recomputes_embeddings     — entries have embeddings after import
  7. test_import_malformed_json            — garbage input returns exit code 1
  8. test_roundtrip_fidelity               — export → replace import → re-export matches
  9. test_import_feed_sources_merge        — feed sources imported; duplicates skipped
  10. test_import_replace_requires_confirmation — replace without --yes prompts/errors

Note: _cmd_export and _cmd_import use asyncio.run() internally, so tests that call them
must NOT be running in an async event loop.  Tests that also need async setup (e.g. to
seed the DuckDB store) therefore run the setup inside asyncio.run() *before* the CLI
call, keeping everything synchronous from pytest's perspective.
"""

from __future__ import annotations

import asyncio
import json
import textwrap
import unittest.mock as mock
from pathlib import Path
from typing import Any

import pytest

from distillery.cli import _cmd_export, _cmd_import
from distillery.store.duckdb import DuckDBStore

# Individual tests use @pytest.mark.unit; no module-level marker to avoid dual-marking.

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EMBED_DIMS = 1024  # Matches the default dimensions from DistilleryConfig.


def write_config(tmp_path: Path, db_path: str, name: str = "distillery.yaml") -> Path:
    """Write a distillery config pointing at *db_path* using the mock hash provider.

    Uses ``provider: "mock"`` so the CLI opens the database with
    ``HashEmbeddingProvider`` (model_name='mock-hash'), which is consistent
    with the provider used when seeding via :func:`_seed_store`.
    """
    cfg = tmp_path / name
    cfg.write_text(
        textwrap.dedent(
            f"""\
            storage:
              backend: duckdb
              database_path: "{db_path}"
            embedding:
              provider: "mock"
            """
        )
    )
    return cfg


def _make_entry_dict(
    entry_id: str,
    content: str = "Default test content",
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a minimal entry dict suitable for an export payload."""
    defaults: dict[str, Any] = {
        "id": entry_id,
        "content": content,
        "entry_type": "inbox",
        "source": "manual",
        "author": "tester",
        "project": None,
        "tags": [],
        "status": "active",
        "metadata": {},
        "version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "created_by": "tester",
        "last_modified_by": "tester",
    }
    defaults.update(kwargs)
    return defaults


def _make_payload(
    entries: list[dict[str, Any]] | None = None,
    feed_sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Wrap entries + feed_sources in a valid export payload."""
    return {
        "version": 1,
        "exported_at": "2026-01-01T00:00:00+00:00",
        "meta": {},
        "entries": entries or [],
        "feed_sources": feed_sources or [],
    }


async def _async_seed_store(db_path: str, entries: list[dict[str, Any]]) -> None:
    """Initialize a DuckDBStore and insert raw entries via SQL.

    Uses ``HashEmbeddingProvider`` (model_name='mock-hash') so the seeded
    database is consistent with the ``provider: "mock"`` config written by
    :func:`write_config`.
    """
    from datetime import UTC, datetime

    from distillery.mcp._stub_embedding import HashEmbeddingProvider

    provider = HashEmbeddingProvider(dimensions=_EMBED_DIMS)
    store = DuckDBStore(db_path=db_path, embedding_provider=provider)
    await store.initialize()
    conn = store._conn  # type: ignore[attr-defined]
    assert conn is not None

    for raw in entries:
        def _parse_dt(val: Any) -> datetime:
            if isinstance(val, datetime):
                return val if val.tzinfo is not None else val.replace(tzinfo=UTC)
            dt = datetime.fromisoformat(str(val))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

        embedding = provider.embed(raw.get("content", ""))
        conn.execute(
            "INSERT INTO entries "
            "(id, content, entry_type, source, author, project, tags, status, "
            " metadata, created_at, updated_at, version, embedding, "
            " created_by, last_modified_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                raw["id"],
                raw["content"],
                raw.get("entry_type", "inbox"),
                raw.get("source", "manual"),
                raw.get("author", ""),
                raw.get("project"),
                list(raw.get("tags") or []),
                raw.get("status", "active"),
                json.dumps(raw.get("metadata") or {}),
                _parse_dt(raw["created_at"]),
                _parse_dt(raw["updated_at"]),
                int(raw.get("version", 1)),
                embedding,
                raw.get("created_by", ""),
                raw.get("last_modified_by", ""),
            ],
        )
    await store.close()


def _seed_store(db_path: str, entries: list[dict[str, Any]]) -> None:
    """Synchronous wrapper around _async_seed_store for use in sync test functions."""
    asyncio.run(_async_seed_store(db_path, entries))


async def _async_count_entries(db_path: str) -> int:
    """Return the number of entries in the store at *db_path*."""
    from distillery.mcp._stub_embedding import HashEmbeddingProvider

    provider = HashEmbeddingProvider(dimensions=_EMBED_DIMS)
    store = DuckDBStore(db_path=db_path, embedding_provider=provider)
    await store.initialize()
    conn = store._conn  # type: ignore[attr-defined]
    assert conn is not None
    row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
    await store.close()
    assert row is not None
    return int(row[0])


async def _async_count_null_embeddings(db_path: str) -> int:
    """Return the number of entries whose embedding is NULL."""
    from distillery.mcp._stub_embedding import HashEmbeddingProvider

    provider = HashEmbeddingProvider(dimensions=_EMBED_DIMS)
    store = DuckDBStore(db_path=db_path, embedding_provider=provider)
    await store.initialize()
    conn = store._conn  # type: ignore[attr-defined]
    assert conn is not None
    row = conn.execute("SELECT COUNT(*) FROM entries WHERE embedding IS NULL").fetchone()
    await store.close()
    assert row is not None
    return int(row[0])


# ---------------------------------------------------------------------------
# 1. test_export_creates_valid_json
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_export_creates_valid_json(tmp_path: Path) -> None:
    """Export from a seeded store produces a valid JSON file with all required keys."""
    db_path = str(tmp_path / "test.db")
    cfg_path = write_config(tmp_path, db_path)
    out_path = str(tmp_path / "export.json")

    # Seed two entries (synchronous setup before CLI call).
    entries = [
        _make_entry_dict("aaaaaaaa-0000-0000-0000-000000000001", "First entry content"),
        _make_entry_dict("aaaaaaaa-0000-0000-0000-000000000002", "Second entry content"),
    ]
    _seed_store(db_path, entries)

    rc = _cmd_export(str(cfg_path), "text", out_path)
    assert rc == 0, "export should return exit code 0"
    assert Path(out_path).exists(), "export file must be created"

    data = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert "exported_at" in data
    assert "meta" in data
    assert "entries" in data
    assert "feed_sources" in data
    assert isinstance(data["entries"], list)
    assert len(data["entries"]) == 2

    # Verify required fields present in each entry row.
    required_fields = {
        "id", "content", "entry_type", "source", "status",
        "tags", "metadata", "version",
    }
    for entry in data["entries"]:
        for field in required_fields:
            assert field in entry, f"Entry missing field: {field!r}"


# ---------------------------------------------------------------------------
# 2. test_export_excludes_embeddings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_export_excludes_embeddings(tmp_path: Path) -> None:
    """Exported entry dicts must not contain an 'embedding' key."""
    db_path = str(tmp_path / "test.db")
    cfg_path = write_config(tmp_path, db_path)
    out_path = str(tmp_path / "export.json")

    _seed_store(
        db_path,
        [_make_entry_dict("bbbbbbbb-0000-0000-0000-000000000001", "Content with embedding")],
    )

    rc = _cmd_export(str(cfg_path), "text", out_path)
    assert rc == 0

    data = json.loads(Path(out_path).read_text(encoding="utf-8"))
    for entry in data["entries"]:
        assert "embedding" not in entry, (
            f"Entry {entry.get('id')} must not expose 'embedding' key"
        )


# ---------------------------------------------------------------------------
# 3. test_import_merge_skips_existing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_import_merge_skips_existing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Importing the same entry twice in merge mode skips it on the second pass."""
    db_path = str(tmp_path / "test.db")
    cfg_path = write_config(tmp_path, db_path)
    input_file = tmp_path / "payload.json"

    entries = [_make_entry_dict("cccccccc-0000-0000-0000-000000000001", "Unique content")]
    input_file.write_text(json.dumps(_make_payload(entries)), encoding="utf-8")

    # First import — should insert 1 entry.
    rc1 = _cmd_import(str(cfg_path), "text", str(input_file), "merge", True)
    assert rc1 == 0
    out1 = capsys.readouterr().out
    assert "Imported 1 entries" in out1, f"Expected '1 entries' in: {out1!r}"

    # Second import in merge mode — entry already exists, skip count = 1.
    rc2 = _cmd_import(str(cfg_path), "text", str(input_file), "merge", True)
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "0 entries" in out2 or "Imported 0" in out2, f"Expected skip in: {out2!r}"
    assert "1 skipped" in out2, f"Expected '1 skipped' in: {out2!r}"


# ---------------------------------------------------------------------------
# 4. test_import_merge_adds_new
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_import_merge_adds_new(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Merging a payload with a new ID adds that entry to the store."""
    db_path = str(tmp_path / "test.db")
    cfg_path = write_config(tmp_path, db_path)
    input_file1 = tmp_path / "first.json"
    input_file2 = tmp_path / "second.json"

    entry_a = _make_entry_dict("dddddddd-0000-0000-0000-000000000001", "First unique entry")
    entry_b = _make_entry_dict("dddddddd-0000-0000-0000-000000000002", "Second new entry")

    # Import entry A.
    input_file1.write_text(json.dumps(_make_payload([entry_a])), encoding="utf-8")
    rc1 = _cmd_import(str(cfg_path), "text", str(input_file1), "merge", True)
    assert rc1 == 0
    capsys.readouterr()  # consume

    # Import a payload with both A (existing) and B (new) in merge mode.
    input_file2.write_text(json.dumps(_make_payload([entry_a, entry_b])), encoding="utf-8")
    rc2 = _cmd_import(str(cfg_path), "text", str(input_file2), "merge", True)
    assert rc2 == 0
    out2 = capsys.readouterr().out
    # Entry B is new — imported = 1; entry A already exists — skipped = 1.
    assert "Imported 1 entries" in out2, f"Expected 1 imported in: {out2!r}"
    assert "1 skipped" in out2, f"Expected 1 skipped in: {out2!r}"


# ---------------------------------------------------------------------------
# 5. test_import_replace_drops_existing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_import_replace_drops_existing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Replace mode deletes existing entries; only the imported set remains."""
    db_path = str(tmp_path / "test.db")
    cfg_path = write_config(tmp_path, db_path)

    # Seed three original entries into the store.
    originals = [
        _make_entry_dict(f"eeeeeeee-0000-0000-0000-00000000000{i}", f"Original entry {i}")
        for i in range(1, 4)
    ]
    _seed_store(db_path, originals)

    # Payload with only two new entries (different IDs).
    new_entries = [
        _make_entry_dict("ffffffff-0000-0000-0000-000000000001", "Replacement entry 1"),
        _make_entry_dict("ffffffff-0000-0000-0000-000000000002", "Replacement entry 2"),
    ]
    input_file = tmp_path / "replace.json"
    input_file.write_text(json.dumps(_make_payload(new_entries)), encoding="utf-8")

    rc = _cmd_import(str(cfg_path), "text", str(input_file), "replace", True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Imported 2 entries" in out, f"Expected 2 imported in: {out!r}"

    # Verify only 2 entries remain in the database.
    count = asyncio.run(_async_count_entries(db_path))
    assert count == 2, f"Expected 2 entries after replace, got {count}"


# ---------------------------------------------------------------------------
# 6. test_import_recomputes_embeddings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_import_recomputes_embeddings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """After import, entries in the store must have non-null embeddings."""
    db_path = str(tmp_path / "test.db")
    cfg_path = write_config(tmp_path, db_path)

    entries = [
        _make_entry_dict("11111111-0000-0000-0000-000000000001", "The quick brown fox"),
        _make_entry_dict("11111111-0000-0000-0000-000000000002", "Jumps over the lazy dog"),
    ]
    input_file = tmp_path / "import.json"
    input_file.write_text(json.dumps(_make_payload(entries)), encoding="utf-8")

    rc = _cmd_import(str(cfg_path), "text", str(input_file), "merge", True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Imported 2" in out, f"Expected 2 imported in: {out!r}"

    # Confirm embedding column is not NULL for imported entries.
    null_count = asyncio.run(_async_count_null_embeddings(db_path))
    assert null_count == 0, (
        f"Expected 0 NULL embeddings after import, got {null_count}"
    )


# ---------------------------------------------------------------------------
# 7. test_import_malformed_json
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_import_malformed_json(tmp_path: Path) -> None:
    """Importing a file with invalid JSON returns exit code 1."""
    db_path = str(tmp_path / "test.db")
    cfg_path = write_config(tmp_path, db_path)
    bad_file = tmp_path / "garbage.json"
    bad_file.write_text("{this is not valid json!!!", encoding="utf-8")

    rc = _cmd_import(str(cfg_path), "text", str(bad_file), "merge", True)
    assert rc == 1, f"Expected exit code 1 for malformed JSON, got {rc}"


# ---------------------------------------------------------------------------
# 8. test_roundtrip_fidelity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_roundtrip_fidelity(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Export → import --mode replace → re-export yields same entries (minus timestamps)."""
    db_path1 = str(tmp_path / "source.db")
    db_path2 = str(tmp_path / "dest.db")
    cfg1 = write_config(tmp_path, db_path1, "cfg1.yaml")
    cfg2 = write_config(tmp_path, db_path2, "cfg2.yaml")

    # Seed source database with known entries.
    entries = [
        _make_entry_dict(
            "22222222-0000-0000-0000-000000000001",
            "Round-trip entry alpha",
            tags=["alpha", "test"],
            metadata={"key": "value"},
        ),
        _make_entry_dict(
            "22222222-0000-0000-0000-000000000002",
            "Round-trip entry beta",
            project="my-project",
        ),
    ]
    _seed_store(db_path1, entries)

    # Export from source.
    export1_path = str(tmp_path / "export1.json")
    rc_export1 = _cmd_export(str(cfg1), "text", export1_path)
    assert rc_export1 == 0
    capsys.readouterr()

    # Import into destination with replace mode.
    rc_import = _cmd_import(str(cfg2), "text", export1_path, "replace", True)
    assert rc_import == 0
    capsys.readouterr()

    # Re-export from destination.
    export2_path = str(tmp_path / "export2.json")
    rc_export2 = _cmd_export(str(cfg2), "text", export2_path)
    assert rc_export2 == 0
    capsys.readouterr()

    data1 = json.loads(Path(export1_path).read_text(encoding="utf-8"))
    data2 = json.loads(Path(export2_path).read_text(encoding="utf-8"))

    # Compare entries, excluding timing fields that may differ.
    volatile_fields = {"exported_at", "created_at", "updated_at"}

    def _strip_volatile(entry_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {k: v for k, v in e.items() if k not in volatile_fields}
            for e in sorted(entry_list, key=lambda x: x.get("id", ""))
        ]

    entries1 = _strip_volatile(data1["entries"])
    entries2 = _strip_volatile(data2["entries"])

    assert len(entries1) == len(entries2), (
        f"Entry count mismatch: export1={len(entries1)}, export2={len(entries2)}"
    )
    for e1, e2 in zip(entries1, entries2, strict=True):
        assert e1 == e2, f"Entry mismatch:\n  export1: {e1}\n  export2: {e2}"


# ---------------------------------------------------------------------------
# 9. test_import_feed_sources_merge
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_import_feed_sources_merge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Feed sources in the import payload are added; duplicate URLs are silently skipped."""
    db_path = str(tmp_path / "test.db")
    cfg_path = write_config(tmp_path, db_path)
    input_file = tmp_path / "feeds.json"

    feed_sources = [
        {
            "url": "https://example.com/feed.rss",
            "source_type": "rss",
            "label": "Example RSS",
            "poll_interval_minutes": 60,
            "trust_weight": 1.0,
        },
        {
            "url": "https://github.com/example/repo",
            "source_type": "github",
            "label": "Example GitHub",
            "poll_interval_minutes": 120,
            "trust_weight": 0.8,
        },
    ]
    payload = _make_payload(feed_sources=feed_sources)
    input_file.write_text(json.dumps(payload), encoding="utf-8")

    # First import: both feed sources should be added.
    rc1 = _cmd_import(str(cfg_path), "text", str(input_file), "merge", True)
    assert rc1 == 0
    out1 = capsys.readouterr().out
    assert "2 feed sources" in out1, f"Expected 2 feed sources in: {out1!r}"

    # Second import in merge mode: duplicate URLs should be silently skipped.
    rc2 = _cmd_import(str(cfg_path), "text", str(input_file), "merge", True)
    assert rc2 == 0
    out2 = capsys.readouterr().out
    # Import should succeed with 0 feed sources added (duplicates suppressed).
    assert "0 feed sources" in out2, f"Expected 0 feed sources on re-import in: {out2!r}"


# ---------------------------------------------------------------------------
# 10. test_import_replace_requires_confirmation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_import_replace_requires_confirmation(tmp_path: Path) -> None:
    """Replace mode without --yes prompts; in non-interactive mode it cancels gracefully."""
    db_path = str(tmp_path / "test.db")
    cfg_path = write_config(tmp_path, db_path)
    input_file = tmp_path / "payload.json"
    input_file.write_text(
        json.dumps(_make_payload([_make_entry_dict("33333333-0000-0000-0000-000000000001")])),
        encoding="utf-8",
    )

    # Simulate a non-interactive environment where stdin raises EOFError.
    # The CLI handles this by treating it as a "no" confirmation and cancelling.
    with mock.patch("builtins.input", side_effect=EOFError):
        rc = _cmd_import(str(cfg_path), "text", str(input_file), "replace", False)

    # On EOF (non-interactive), the import is cancelled — should return non-zero
    # so automation can distinguish a no-op from a successful restore.
    assert rc == 1, (
        f"Replace-mode cancellation should return 1 (cancelled), got {rc}"
    )
