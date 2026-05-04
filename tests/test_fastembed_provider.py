"""Unit tests for the local fastembed embedding provider.

Skipped automatically when the optional ``fastembed`` dep is not installed
(installable via ``pip install distillery-mcp[fastembed]``).  The first
test downloads / caches the BAAI/bge-small-en-v1.5 ONNX model on the
machine running the suite — subsequent runs are warm and fast.
"""

from __future__ import annotations

import pytest

# Skip the entire module unless the optional dep is installed.  Done with
# importorskip so the standard dev install (`pip install -e ".[dev]"`)
# still passes `pytest -m unit` with no fastembed extras.
pytest.importorskip("fastembed")

from distillery.embedding.fastembed import (  # noqa: E402  (import after skip)
    DEFAULT_MODEL,
    MODEL_ALIASES,
    FastembedProvider,
    _resolve_model_name,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Pure-Python helpers (do not need the model to be loaded)
# ---------------------------------------------------------------------------


def test_model_aliases_resolve() -> None:
    """``bge-small`` and friends map to their full HuggingFace identifiers."""
    assert _resolve_model_name("bge-small") == "BAAI/bge-small-en-v1.5"
    assert _resolve_model_name("bge-base") == "BAAI/bge-base-en-v1.5"
    assert _resolve_model_name("bge-large") == "BAAI/bge-large-en-v1.5"
    assert _resolve_model_name("nomic") == "nomic-ai/nomic-embed-text-v1.5"
    assert _resolve_model_name("mxbai") == "mixedbread-ai/mxbai-embed-large-v1"


def test_unknown_model_passes_through() -> None:
    """Non-aliased identifiers are returned as-is for fastembed to validate."""
    assert _resolve_model_name("BAAI/bge-small-en-v1.5") == "BAAI/bge-small-en-v1.5"
    assert _resolve_model_name("custom/model-x") == "custom/model-x"


def test_default_model_is_bge_small() -> None:
    """Default stays pinned to the small bge model documented in the bench."""
    assert DEFAULT_MODEL == "BAAI/bge-small-en-v1.5"
    assert "bge-small" in MODEL_ALIASES


def test_construction_does_not_load_model() -> None:
    """Constructor is cheap — no ONNX session is created until first embed."""
    provider = FastembedProvider()
    assert provider._embedder is None  # noqa: SLF001
    # Dimensions for known aliases is answerable without loading the model.
    assert provider.dimensions == 384
    assert provider._embedder is None  # noqa: SLF001


def test_model_name_resolves_alias_in_constructor() -> None:
    """Passing ``"bge-small"`` resolves to the full identifier on the property."""
    provider = FastembedProvider(model="bge-small")
    assert provider.model_name == "BAAI/bge-small-en-v1.5"


# ---------------------------------------------------------------------------
# Integration with the actual model — downloads weights on first run
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def provider() -> FastembedProvider:
    """Module-scoped provider so the ONNX model is loaded only once."""
    return FastembedProvider()


def test_embed_returns_correct_dimensions(provider: FastembedProvider) -> None:
    """``embed`` produces a 384-dimensional vector for bge-small."""
    vector = provider.embed("hello world")
    assert isinstance(vector, list)
    assert len(vector) == 384
    assert all(isinstance(v, float) for v in vector)


def test_embed_batch_returns_correct_shape(provider: FastembedProvider) -> None:
    """``embed_batch`` returns one 384-dim vector per input, in order."""
    texts = ["alpha", "beta", "gamma"]
    vectors = provider.embed_batch(texts)
    assert len(vectors) == len(texts)
    for v in vectors:
        assert len(v) == 384


def test_empty_batch_returns_empty_list(provider: FastembedProvider) -> None:
    """An empty input list is a no-op and does not load the model."""
    fresh = FastembedProvider()
    assert fresh.embed_batch([]) == []
    # Empty-batch fast path must not have triggered model loading.
    assert fresh._embedder is None  # noqa: SLF001


def test_embed_is_deterministic(provider: FastembedProvider) -> None:
    """Two calls with the same input produce identical vectors.

    Without this, the bench cannot characterise variance — embedding noise
    would dwarf any retrieval-quality signal.  fastembed's ONNX runtime is
    deterministic on CPU; this test pins that contract.
    """
    text = "The quokka is a small marsupial native to Western Australia."
    v1 = provider.embed(text)
    v2 = provider.embed(text)
    assert v1 == v2


def test_batch_matches_singletons(provider: FastembedProvider) -> None:
    """Batching does not change the output: embed_batch == [embed, embed, ...].

    Distillery's bench ingests sessions in batches; if batched outputs
    diverged from per-document outputs, the recall numbers would not
    reproduce when run document-by-document for debugging.
    """
    texts = ["first sentence", "second sentence", "third sentence"]
    batched = provider.embed_batch(texts)
    singletons = [provider.embed(t) for t in texts]
    assert batched == singletons


def test_model_name_property(provider: FastembedProvider) -> None:
    """``model_name`` exposes the resolved HuggingFace identifier."""
    assert provider.model_name == DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Additional unit tests (no model loading)
# ---------------------------------------------------------------------------


def test_known_dimensions_bge_base_without_loading() -> None:
    """bge-base has 768 dimensions, answerable from _KNOWN_DIMENSIONS before load."""
    p = FastembedProvider(model="bge-base")
    assert p.model_name == "BAAI/bge-base-en-v1.5"
    assert p.dimensions == 768
    # Must not have triggered lazy loading just to answer the dimensions question.
    assert p._embedder is None  # noqa: SLF001


def test_known_dimensions_bge_large_without_loading() -> None:
    """bge-large has 1024 dimensions, answerable before load."""
    p = FastembedProvider(model="bge-large")
    assert p.model_name == "BAAI/bge-large-en-v1.5"
    assert p.dimensions == 1024
    assert p._embedder is None  # noqa: SLF001


def test_known_dimensions_nomic_without_loading() -> None:
    """nomic alias resolves to 768-dimensional model without loading."""
    p = FastembedProvider(model="nomic")
    assert p.model_name == "nomic-ai/nomic-embed-text-v1.5"
    assert p.dimensions == 768
    assert p._embedder is None  # noqa: SLF001


def test_known_dimensions_mxbai_without_loading() -> None:
    """mxbai alias resolves to 1024-dimensional model without loading."""
    p = FastembedProvider(model="mxbai")
    assert p.model_name == "mixedbread-ai/mxbai-embed-large-v1"
    assert p.dimensions == 1024
    assert p._embedder is None  # noqa: SLF001


def test_construction_with_cache_dir_param() -> None:
    """cache_dir parameter is stored but does not trigger loading."""
    p = FastembedProvider(model="bge-small", cache_dir="/tmp/fastembed-test-cache")
    assert p._cache_dir == "/tmp/fastembed-test-cache"  # noqa: SLF001
    assert p._embedder is None  # noqa: SLF001


def test_construction_with_threads_param() -> None:
    """threads parameter is stored but does not trigger loading."""
    p = FastembedProvider(model="bge-small", threads=4)
    assert p._threads == 4  # noqa: SLF001
    assert p._embedder is None  # noqa: SLF001


def test_all_aliases_resolve_to_different_models() -> None:
    """All aliases in MODEL_ALIASES map to distinct HuggingFace identifiers."""
    resolved = {_resolve_model_name(alias) for alias in MODEL_ALIASES}
    # No two aliases should produce the same full identifier.
    assert len(resolved) == len(MODEL_ALIASES)


def test_full_identifier_passes_through_unchanged() -> None:
    """Passing a full HuggingFace id that is already an alias value is a pass-through."""
    full_id = "BAAI/bge-small-en-v1.5"
    assert _resolve_model_name(full_id) == full_id


def test_default_model_is_384_dimensional_without_loading() -> None:
    """Default provider answers dimensions=384 without triggering lazy loading."""
    p = FastembedProvider()
    assert p.dimensions == 384
    assert p._embedder is None  # noqa: SLF001


def test_unknown_model_dimensions_is_none_before_load() -> None:
    """For a model not in _KNOWN_DIMENSIONS, _dimensions is None until first load."""
    from distillery.embedding.fastembed import _KNOWN_DIMENSIONS

    unknown_model = "some/unknown-model-not-in-registry"
    assert unknown_model not in _KNOWN_DIMENSIONS
    p = FastembedProvider(model=unknown_model)
    # _dimensions should be None because the model is not pre-registered.
    assert p._dimensions is None  # noqa: SLF001
