"""Smoke test — verify the `fastembed` provider integrates cleanly with the
embedding factory and the DuckDB store, without requiring any external API
key (``JINA_API_KEY`` / ``OPENAI_API_KEY``).

Marked ``integration`` so it does not run on a plain ``pytest -m unit``
invocation; it can pull ~67 MB of ONNX weights from HuggingFace on first run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _have_fastembed() -> bool:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(not _have_fastembed(), reason="fastembed extra not installed")
def test_create_provider_fastembed_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """`create_provider` returns a FastembedProvider when configured, with no
    external API key set in the environment."""
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from distillery.config import EmbeddingConfig
    from distillery.embedding import FastembedProvider, create_provider

    class _Cfg:
        embedding = EmbeddingConfig(
            provider="fastembed",
            model="BAAI/bge-small-en-v1.5",
            dimensions=384,
            api_key_env="",
        )

    provider = create_provider(_Cfg())
    assert isinstance(provider, FastembedProvider)
    assert provider.model_name == "BAAI/bge-small-en-v1.5"
    assert provider.dimensions == 384


@pytest.mark.skipif(not _have_fastembed(), reason="fastembed extra not installed")
async def test_store_with_fastembed_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Storing five entries and recalling the closest one against a fresh
    DuckDB file works with a real fastembed provider — no API keys.
    """
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    from distillery.embedding.fastembed import FastembedProvider
    from distillery.models import Entry, EntrySource, EntryStatus, EntryType
    from distillery.store.duckdb import DuckDBStore

    provider = FastembedProvider(model="BAAI/bge-small-en-v1.5")
    db_path = str(tmp_path / "smoke.db")
    store = DuckDBStore(db_path=db_path, embedding_provider=provider)
    try:
        await store.initialize()

        seeds = [
            "DuckDB is a fast in-process analytical database.",
            "Cosine similarity measures the angle between two vectors.",
            "The Vancouver waterfront has a seaplane terminal.",
            "Sourdough bread relies on wild yeast and lactic bacteria.",
            "ONNX runtime executes neural network graphs across hardware.",
        ]
        for s in seeds:
            await store.store(
                Entry(
                    content=s,
                    entry_type=EntryType.REFERENCE,
                    source=EntrySource.MANUAL,
                    author="smoke-test",
                    status=EntryStatus.ACTIVE,
                )
            )

        hits = await store.search("vector database query speed", filters=None, limit=3)
        assert len(hits) >= 1
        top_text = hits[0].entry.content.lower()
        assert "duckdb" in top_text or "vector" in top_text or "cosine" in top_text
    finally:
        await store.close()
