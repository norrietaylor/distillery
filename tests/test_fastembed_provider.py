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

# NOTE: Markers are applied per-test below rather than via a module-level
# ``pytestmark`` because the file mixes pure-Python checks (unit) with tests
# that load the real ONNX model (integration — slow + downloads weights on
# first run).  Per CLAUDE.md test-marker conventions.


# ---------------------------------------------------------------------------
# Pure-Python helpers (do not need the model to be loaded)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_model_aliases_resolve() -> None:
    """``bge-small`` and friends map to their full HuggingFace identifiers."""
    assert _resolve_model_name("bge-small") == "BAAI/bge-small-en-v1.5"
    assert _resolve_model_name("bge-base") == "BAAI/bge-base-en-v1.5"
    assert _resolve_model_name("bge-large") == "BAAI/bge-large-en-v1.5"
    assert _resolve_model_name("nomic") == "nomic-ai/nomic-embed-text-v1.5"
    assert _resolve_model_name("mxbai") == "mixedbread-ai/mxbai-embed-large-v1"


@pytest.mark.unit
def test_unknown_model_passes_through() -> None:
    """Non-aliased identifiers are returned as-is for fastembed to validate."""
    assert _resolve_model_name("BAAI/bge-small-en-v1.5") == "BAAI/bge-small-en-v1.5"
    assert _resolve_model_name("custom/model-x") == "custom/model-x"


@pytest.mark.unit
def test_default_model_is_bge_small() -> None:
    """Default stays pinned to the small bge model documented in the bench."""
    assert DEFAULT_MODEL == "BAAI/bge-small-en-v1.5"
    assert "bge-small" in MODEL_ALIASES


@pytest.mark.unit
def test_construction_does_not_load_model() -> None:
    """Constructor is cheap — no ONNX session is created until first embed."""
    provider = FastembedProvider()
    assert provider._embedder is None  # noqa: SLF001
    # Dimensions for known aliases is answerable without loading the model.
    assert provider.dimensions == 384
    assert provider._embedder is None  # noqa: SLF001


@pytest.mark.unit
def test_model_name_resolves_alias_in_constructor() -> None:
    """Passing ``"bge-small"`` resolves to the full identifier on the property."""
    provider = FastembedProvider(model="bge-small")
    assert provider.model_name == "BAAI/bge-small-en-v1.5"


@pytest.mark.unit
def test_concurrent_load_constructs_single_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Threaded first-callers must share a single ``TextEmbedding`` instance.

    Regression test for the lazy-load race condition — without the
    ``_load_lock`` guard, four concurrent ``embed`` calls could each race
    past the ``self._embedder is None`` check and construct their own
    ONNX session, leaking memory and file handles.
    """
    import threading

    import fastembed as fastembed_mod

    call_count = 0
    construct_lock = threading.Lock()
    # Block constructor until all worker threads are inside it, so the test
    # forces the race condition to manifest if the lock is missing.
    inside_constructor = threading.Event()
    proceed = threading.Event()

    class _StubEmbedder:
        embedding_size = 384

        def __init__(self, *args: object, **kwargs: object) -> None:
            nonlocal call_count
            with construct_lock:
                call_count += 1
            inside_constructor.set()
            # Hold here briefly so other threads have a chance to enter
            # (or, without the lock, race past) the check-then-set.
            proceed.wait(timeout=2.0)

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * 384 for _ in texts]

    monkeypatch.setattr(fastembed_mod, "TextEmbedding", _StubEmbedder)

    provider = FastembedProvider()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            provider.embed("x")
        except BaseException as exc:  # pragma: no cover - surfaced via assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    # Once one thread is inside the constructor, release it so all workers
    # complete; with the lock, the other three will block then short-circuit
    # on the double-check.
    inside_constructor.wait(timeout=2.0)
    proceed.set()
    for t in threads:
        t.join(timeout=5.0)
    assert all(not t.is_alive() for t in threads), "Worker thread hung during lazy-load race test"

    assert errors == []
    assert call_count == 1, f"Expected single TextEmbedding construction, got {call_count}"


# ---------------------------------------------------------------------------
# Integration with the actual model — downloads weights on first run
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def provider() -> FastembedProvider:
    """Module-scoped provider so the ONNX model is loaded only once."""
    return FastembedProvider()


@pytest.mark.integration
def test_embed_returns_correct_dimensions(provider: FastembedProvider) -> None:
    """``embed`` produces a 384-dimensional vector for bge-small."""
    vector = provider.embed("hello world")
    assert isinstance(vector, list)
    assert len(vector) == 384
    assert all(isinstance(v, float) for v in vector)


@pytest.mark.integration
def test_embed_batch_returns_correct_shape(provider: FastembedProvider) -> None:
    """``embed_batch`` returns one 384-dim vector per input, in order."""
    texts = ["alpha", "beta", "gamma"]
    vectors = provider.embed_batch(texts)
    assert len(vectors) == len(texts)
    for v in vectors:
        assert len(v) == 384


@pytest.mark.integration
def test_empty_batch_returns_empty_list(provider: FastembedProvider) -> None:
    """An empty input list is a no-op and does not load the model."""
    fresh = FastembedProvider()
    assert fresh.embed_batch([]) == []
    # Empty-batch fast path must not have triggered model loading.
    assert fresh._embedder is None  # noqa: SLF001


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
def test_model_name_property(provider: FastembedProvider) -> None:
    """``model_name`` exposes the resolved HuggingFace identifier."""
    assert provider.model_name == DEFAULT_MODEL
