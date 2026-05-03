"""Tests for the SHA-pinned LongMemEval dataset loader.

Two tiers:

* ``@pytest.mark.unit`` — exercise SHA verification and schema validation
  against a hand-crafted fixture in ``tests/fixtures/longmemeval_mini.json``.
  No network, no HF SDK invocation. Designed for the regular CI unit suite.

* ``@pytest.mark.integration`` — hits the real HuggingFace API on the first
  run, downloads ~265 MB into the user-supplied cache, and verifies the file
  SHA against :data:`DATASET_FILE_SHA256`. The second call exercises the
  warm-cache offline path. Skipped under ``pytest -m unit``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from distillery.eval.longmemeval_dataset import (
    DATASET_FILE_SHA256,
    DATASET_FILENAME,
    DATASET_REVISION_SHA,
    REQUIRED_QUESTION_KEYS,
    DatasetIntegrityError,
    DatasetSchemaError,
    _load_and_verify,
    _validate_schema,
    _verify_sha256,
    load_longmemeval,
)

# ---------------------------------------------------------------------------
# Constants — fixture path + its known-good digest (re-computed on disk).
# ---------------------------------------------------------------------------

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "longmemeval_mini.json"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------------------
# Unit tests — fixture-driven, no network, no HF SDK
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_fixture_exists() -> None:
    """The hand-crafted fixture must ship with the test file."""
    assert FIXTURE_PATH.exists(), f"Missing fixture at {FIXTURE_PATH}"


@pytest.mark.unit
def test_verify_sha256_accepts_matching_digest(tmp_path: Path) -> None:
    """``_verify_sha256`` is a no-op when the digest matches."""
    target = tmp_path / "data.json"
    target.write_bytes(b'{"hello": "world"}')
    expected = _sha256_bytes(target.read_bytes())
    _verify_sha256(target, expected)  # must not raise


@pytest.mark.unit
def test_verify_sha256_rejects_mismatch(tmp_path: Path) -> None:
    """A wrong digest raises :class:`DatasetIntegrityError` with both hashes."""
    target = tmp_path / "data.json"
    target.write_bytes(b'{"hello": "world"}')
    bogus = "0" * 64
    with pytest.raises(DatasetIntegrityError) as excinfo:
        _verify_sha256(target, bogus)
    msg = str(excinfo.value)
    assert "expected" in msg and bogus in msg
    assert "actual" in msg
    assert "data.json" in msg


@pytest.mark.unit
def test_load_and_verify_corrupt_file_raises(tmp_path: Path) -> None:
    """Corrupting the cached fixture must trip SHA verification."""
    cached = tmp_path / DATASET_FILENAME
    shutil.copy(FIXTURE_PATH, cached)
    fixture_sha = _sha256_bytes(cached.read_bytes())

    # Sanity check: fixture matches itself.
    _verify_sha256(cached, fixture_sha)

    # Now corrupt the file — write garbage of identical-ish length.
    cached.write_bytes(b"this is not the dataset you are looking for\n" * 100)

    with pytest.raises(DatasetIntegrityError) as excinfo:
        _verify_sha256(cached, fixture_sha)
    assert "SHA-256 mismatch" in str(excinfo.value)


@pytest.mark.unit
def test_load_and_verify_returns_questions(tmp_path: Path) -> None:
    """End-to-end ``_load_and_verify`` returns the parsed list."""
    cached = tmp_path / DATASET_FILENAME
    shutil.copy(FIXTURE_PATH, cached)
    fixture_sha = _sha256_bytes(cached.read_bytes())

    # Monkey-patch the module-level constant for one call by routing through
    # the lower-level helper directly. ``_load_and_verify`` always uses
    # ``DATASET_FILE_SHA256`` — so we bypass it here by calling _verify + json
    # ourselves with the fixture's own SHA. This keeps the unit test honest
    # about what each helper does.
    _verify_sha256(cached, fixture_sha)
    parsed = json.loads(cached.read_bytes())
    _validate_schema(parsed)

    assert isinstance(parsed, list)
    assert len(parsed) >= 1
    assert REQUIRED_QUESTION_KEYS.issubset(parsed[0].keys())


@pytest.mark.unit
def test_validate_schema_accepts_fixture() -> None:
    """The shipped fixture conforms to the contracted question schema."""
    parsed = json.loads(FIXTURE_PATH.read_bytes())
    _validate_schema(parsed)  # must not raise

    first = parsed[0]
    for key in REQUIRED_QUESTION_KEYS:
        assert key in first, f"Fixture is missing required key: {key}"

    # haystack arrays must be parallel.
    assert len(first["haystack_sessions"]) == len(first["haystack_session_ids"])
    assert len(first["haystack_sessions"]) == len(first["haystack_dates"])


@pytest.mark.unit
def test_validate_schema_rejects_empty() -> None:
    with pytest.raises(DatasetSchemaError, match="empty"):
        _validate_schema([])


@pytest.mark.unit
def test_validate_schema_rejects_non_dict() -> None:
    with pytest.raises(DatasetSchemaError, match="must be dicts"):
        _validate_schema(["not-a-dict"])  # type: ignore[list-item]


@pytest.mark.unit
def test_validate_schema_rejects_missing_keys() -> None:
    bad = [{"question": "only one key"}]
    with pytest.raises(DatasetSchemaError, match="missing required keys"):
        _validate_schema(bad)


@pytest.mark.unit
def test_load_and_verify_full_path_with_fixture_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive ``_load_and_verify`` end-to-end by patching the expected SHA."""
    cached = tmp_path / DATASET_FILENAME
    shutil.copy(FIXTURE_PATH, cached)
    fixture_sha = _sha256_bytes(cached.read_bytes())

    monkeypatch.setattr(
        "distillery.eval.longmemeval_dataset.DATASET_FILE_SHA256",
        fixture_sha,
    )
    result = _load_and_verify(cached)
    assert isinstance(result, list)
    assert len(result) >= 1
    assert REQUIRED_QUESTION_KEYS.issubset(result[0].keys())


@pytest.mark.unit
def test_load_and_verify_corrupt_file_e2e(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Garbage bytes at the fixture path must raise ``DatasetIntegrityError``."""
    cached = tmp_path / DATASET_FILENAME
    cached.write_bytes(b"GARBAGE GARBAGE GARBAGE")

    # Use the fixture's real digest as the "expected" so the corruption is
    # visible (otherwise both garbage and expected would be the same hash).
    monkeypatch.setattr(
        "distillery.eval.longmemeval_dataset.DATASET_FILE_SHA256",
        _sha256_bytes(FIXTURE_PATH.read_bytes()),
    )
    with pytest.raises(DatasetIntegrityError, match="SHA-256 mismatch"):
        _load_and_verify(cached)


@pytest.mark.unit
def test_pinned_constants_are_concrete() -> None:
    """Guard against shipping placeholder SHAs (rule 5)."""
    assert len(DATASET_REVISION_SHA) == 40, "Revision SHA must be a full 40-char hex"
    assert len(DATASET_FILE_SHA256) == 64, "File SHA-256 must be 64 hex chars"
    int(DATASET_REVISION_SHA, 16)  # must parse as hex
    int(DATASET_FILE_SHA256, 16)
    # No "TODO"/"PLACEHOLDER"/"resolved" sentinel strings allowed.
    for sha in (DATASET_REVISION_SHA, DATASET_FILE_SHA256):
        assert sha.lower() == sha, "SHA constants must be lowercase hex"
        assert all(c in "0123456789abcdef" for c in sha)


# ---------------------------------------------------------------------------
# Integration tests — first call hits the network (~265 MB), second is offline.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_load_longmemeval_downloads_and_verifies(tmp_path: Path) -> None:
    """First call: downloads the SHA-pinned dataset and verifies its hash.

    Note: the real ``longmemeval_s_cleaned.json`` is ~265 MB. Plan for a
    ~30-60 s run on a warm pip cache and proportional disk in ``tmp_path``.
    """
    questions = load_longmemeval(cache_dir=tmp_path)
    assert isinstance(questions, list)
    assert len(questions) == 500, "LongMemEval-S contains exactly 500 questions"

    first = questions[0]
    for key in REQUIRED_QUESTION_KEYS:
        assert key in first, f"Live dataset is missing key {key!r}"

    # haystack arrays must be parallel — bench scoring relies on this.
    assert len(first["haystack_sessions"]) == len(first["haystack_session_ids"])
    assert len(first["haystack_sessions"]) == len(first["haystack_dates"])
    assert len(first["answer_session_ids"]) >= 1


@pytest.mark.integration
def test_load_longmemeval_warm_cache_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second call from the same cache must succeed with HF offline mode set."""
    # Warm the cache.
    load_longmemeval(cache_dir=tmp_path)

    # Force HF to refuse network access; the warm cache must satisfy the call.
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    questions = load_longmemeval(cache_dir=tmp_path)
    assert len(questions) == 500


@pytest.mark.integration
def test_load_longmemeval_corrupt_cache_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the cached blob is tampered with, the loader must refuse to return it."""
    load_longmemeval(cache_dir=tmp_path)

    # Locate the cached snapshot entry. snapshot_download uses HF's canonical
    # cache layout: <cache>/datasets--<owner>--<repo>/snapshots/<sha>/<file>.
    # The snapshot path is a symlink into the blobs/ directory; corrupt the
    # underlying blob so verification fails on the next load.
    canonical = (
        tmp_path
        / "datasets--xiaowu0162--longmemeval-cleaned"
        / "snapshots"
        / DATASET_REVISION_SHA
        / DATASET_FILENAME
    )
    assert canonical.exists(), f"Expected cached file at {canonical}"
    blob_target = canonical.resolve()
    blob_target.write_bytes(b"corrupted contents\n")

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pytest.raises(DatasetIntegrityError, match="SHA-256 mismatch"):
        load_longmemeval(cache_dir=tmp_path)
