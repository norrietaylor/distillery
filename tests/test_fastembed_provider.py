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
