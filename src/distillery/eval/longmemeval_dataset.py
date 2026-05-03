"""SHA-pinned LongMemEval dataset loader.

Downloads the cleaned LongMemEval-S split from HuggingFace (repo
``xiaowu0162/longmemeval-cleaned``) at a frozen commit revision, verifies the
SHA-256 digest of the JSON file, and returns the parsed list of question dicts.

The pinning + verification pipeline is the dataset half of publication
discipline rule (5) in the LongMemEval bench plan: code, dataset, embed model,
and Python version SHAs accompany every JSONL receipt. No SHAs ⇒ no claim.

Workaround for the upstream ``FeaturesError``
---------------------------------------------

The HuggingFace ``datasets`` config in this repo trips ``FeaturesError`` when
the loader tries to infer a schema for the ``answer`` column (it is a free-form
string but feature inference treats it as a list of dicts in some rows of the
sibling oracle split). We sidestep the loader entirely: ``snapshot_download``
fetches the raw JSON, which we parse directly. See the dataset viewer error
banner on https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned for
the upstream symptom.

Resolution provenance
---------------------

The constants below were resolved on **2026-05-02** by the bench-author agent:

* ``DATASET_REVISION_SHA`` — current ``main`` HEAD of
  ``xiaowu0162/longmemeval-cleaned`` queried via ``HfApi.list_repo_refs``.
* ``DATASET_FILE_SHA256`` — SHA-256 of the downloaded
  ``longmemeval_s_cleaned.json`` blob (264 MB, 500 questions).

Bumping either constant is an intentional bench-result-invalidating change and
must ship under its own ADR.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

# Resolved 2026-05-02. Do not edit without an ADR — bumping these constants
# invalidates every published bench number.
DATASET_REPO_ID = "xiaowu0162/longmemeval-cleaned"
DATASET_REVISION_SHA = "98d7416c24c778c2fee6e6f3006e7a073259d48f"
DATASET_FILE_SHA256 = "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442"
DATASET_FILENAME = "longmemeval_s_cleaned.json"

# Question-dict keys we contract on. Validated by the loader on every call so a
# silent upstream schema drift (within the same revision) is caught loudly.
REQUIRED_QUESTION_KEYS: frozenset[str] = frozenset(
    {
        "question",
        "question_date",
        "haystack_sessions",
        "haystack_session_ids",
        "haystack_dates",
        "answer_session_ids",
    }
)


class DatasetIntegrityError(RuntimeError):
    """Raised when the cached dataset file fails SHA-256 verification.

    The downloaded blob does not match :data:`DATASET_FILE_SHA256`. Either the
    cache was tampered with, the upstream revision was force-pushed (it
    shouldn't be — HF revisions are immutable), or the constant in this module
    is stale.
    """


class DatasetSchemaError(RuntimeError):
    """Raised when a parsed question dict is missing one of the required keys.

    Indicates upstream schema drift within the pinned revision, which is
    unexpected; report and investigate before trusting bench numbers from this
    run.
    """


def _default_cache_dir() -> Path:
    """Return ``$XDG_CACHE_HOME/distillery/longmemeval`` (or HOME fallback)."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "distillery" / "longmemeval"
    return Path.home() / ".cache" / "distillery" / "longmemeval"


def _sha256_file(path: Path) -> str:
    """Stream the file through SHA-256 in 1 MB chunks (264 MB JSON = 264 reads)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_sha256(path: Path, expected: str) -> None:
    """Raise :class:`DatasetIntegrityError` unless ``path``'s SHA-256 matches."""
    actual = _sha256_file(path)
    if actual != expected:
        raise DatasetIntegrityError(
            f"SHA-256 mismatch for {path.name}.\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}\n"
            f"Refusing to load — re-download by removing the cache directory "
            f"({path.parent}) and re-running, or update DATASET_FILE_SHA256 "
            f"under an ADR if this is an intentional revision bump."
        )


def _validate_schema(questions: list[dict[str, Any]]) -> None:
    """Spot-check the first question for the contracted key set."""
    if not questions:
        raise DatasetSchemaError("Dataset is empty — expected 500 questions.")
    first = questions[0]
    if not isinstance(first, dict):
        raise DatasetSchemaError(f"Top-level entries must be dicts, got {type(first).__name__}.")
    missing = REQUIRED_QUESTION_KEYS - set(first.keys())
    if missing:
        raise DatasetSchemaError(
            f"Dataset schema drift: question 0 missing required keys "
            f"{sorted(missing)}. Pinned revision {DATASET_REVISION_SHA} should "
            f"contain {sorted(REQUIRED_QUESTION_KEYS)}."
        )


def _load_and_verify(json_path: Path) -> list[dict[str, Any]]:
    """Verify SHA-256, parse, validate schema; return parsed question list."""
    _verify_sha256(json_path, DATASET_FILE_SHA256)
    with json_path.open("rb") as f:
        parsed = json.load(f)
    if not isinstance(parsed, list):
        raise DatasetSchemaError(f"Top-level JSON must be a list, got {type(parsed).__name__}.")
    _validate_schema(parsed)
    return parsed


def load_longmemeval(cache_dir: Path | None = None) -> list[dict[str, Any]]:
    """Download (if needed), verify, and return the LongMemEval-S question list.

    Parameters
    ----------
    cache_dir:
        Directory used for the HuggingFace blob cache. Defaults to
        ``$XDG_CACHE_HOME/distillery/longmemeval`` (or
        ``~/.cache/distillery/longmemeval`` if XDG is unset). After the first
        successful run, subsequent calls are offline.

    Returns
    -------
    list[dict]
        Parsed question dicts. Each dict has at least ``question``,
        ``question_date``, ``haystack_sessions``, ``haystack_session_ids``,
        ``haystack_dates``, and ``answer_session_ids``.

    Raises
    ------
    DatasetIntegrityError
        If the downloaded JSON's SHA-256 does not match
        :data:`DATASET_FILE_SHA256`.
    DatasetSchemaError
        If the parsed JSON is empty, not a list, or the first question is
        missing one of :data:`REQUIRED_QUESTION_KEYS`.
    ImportError
        If ``huggingface_hub`` is not installed (it lives in the ``[dev]``
        optional group).
    """
    target_cache = cache_dir if cache_dir is not None else _default_cache_dir()
    target_cache.mkdir(parents=True, exist_ok=True)

    # huggingface_hub is a dev-only dep; surface a clear error if missing.
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover - import guard
        raise ImportError(
            "load_longmemeval requires huggingface_hub. Install the dev extras: "
            "pip install -e '.[dev]'"
        ) from exc

    snapshot_dir_str = snapshot_download(
        repo_id=DATASET_REPO_ID,
        revision=DATASET_REVISION_SHA,
        repo_type="dataset",
        cache_dir=str(target_cache),
        allow_patterns=[DATASET_FILENAME],
    )
    snapshot_dir = Path(snapshot_dir_str)
    json_path = snapshot_dir / DATASET_FILENAME
    if not json_path.exists():
        raise DatasetIntegrityError(
            f"snapshot_download succeeded but {DATASET_FILENAME} is missing "
            f"from {snapshot_dir}. The pinned revision may not contain this "
            f"file (revision={DATASET_REVISION_SHA})."
        )
    return _load_and_verify(json_path)


__all__ = [
    "DATASET_FILE_SHA256",
    "DATASET_FILENAME",
    "DATASET_REPO_ID",
    "DATASET_REVISION_SHA",
    "REQUIRED_QUESTION_KEYS",
    "DatasetIntegrityError",
    "DatasetSchemaError",
    "load_longmemeval",
]
