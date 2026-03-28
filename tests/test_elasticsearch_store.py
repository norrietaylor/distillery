"""Tests for the Elasticsearch storage backend.

Unit tests use a mock AsyncElasticsearch client to verify CRUD operations,
index creation, and config validation without requiring a live ES instance.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from distillery.models import Entry, EntrySource, EntryType
from distillery.store.elasticsearch import ElasticsearchStore, _doc_to_entry, _entry_to_doc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(**kwargs: Any) -> Entry:
    """Return a minimal valid Entry, optionally overriding any field."""
    defaults: dict[str, Any] = {
        "content": "Default content",
        "entry_type": EntryType.INBOX,
        "source": EntrySource.MANUAL,
        "author": "tester",
    }
    defaults.update(kwargs)
    return Entry(**defaults)


class MockEmbeddingProvider:
    """Minimal embedding provider for ES store tests."""

    _DIMS = 768

    def embed(self, text: str) -> list[float]:
        return [0.1] * self._DIMS

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self._DIMS for _ in texts]

    @property
    def dimensions(self) -> int:
        return self._DIMS

    @property
    def model_name(self) -> str:
        return "mock-768d"


def _mock_es_client() -> AsyncMock:
    """Create a mock AsyncElasticsearch client."""
    client = AsyncMock()
    client.indices = AsyncMock()
    client.indices.exists = AsyncMock(return_value=False)
    client.indices.create = AsyncMock()
    client.index = AsyncMock()
    client.get = AsyncMock()
    client.update = AsyncMock()
    client.delete = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def embedding_provider() -> MockEmbeddingProvider:
    return MockEmbeddingProvider()


@pytest.fixture
def es_client() -> AsyncMock:
    return _mock_es_client()


@pytest.fixture
async def es_store(
    es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
) -> ElasticsearchStore:
    """Return an initialized ElasticsearchStore with mock client."""
    store = ElasticsearchStore(
        client=es_client,
        embedding_provider=embedding_provider,
        index_prefix="distillery",
        embedding_mode="client",
    )
    await store.initialize()
    return store


# ---------------------------------------------------------------------------
# Index creation / initialization tests
# ---------------------------------------------------------------------------


class TestInitialize:
    """Tests for ElasticsearchStore.initialize()."""

    @pytest.mark.unit
    async def test_initialize_creates_versioned_indices_with_aliases(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """initialize() creates versioned indices with aliases when they don't exist."""
        es_client.indices.exists.return_value = False

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            index_prefix="distillery",
        )
        await store.initialize()

        # Should check existence and create all three indices.
        assert es_client.indices.exists.call_count == 3
        assert es_client.indices.create.call_count == 3

        created_indices = [
            call.kwargs["index"] for call in es_client.indices.create.call_args_list
        ]
        assert "distillery_entries_v1" in created_indices
        assert "distillery_search_log_v1" in created_indices
        assert "distillery_feedback_log_v1" in created_indices

        # Verify aliases are set.
        for call in es_client.indices.create.call_args_list:
            body = call.kwargs["body"]
            assert "aliases" in body

    @pytest.mark.unit
    async def test_initialize_sets_bbq_hnsw_mapping(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """initialize() configures BBQ HNSW on the entries index embedding field."""
        es_client.indices.exists.return_value = False

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            index_prefix="distillery",
        )
        await store.initialize()

        # Find the entries index creation call.
        entries_call = None
        for call in es_client.indices.create.call_args_list:
            if call.kwargs["index"] == "distillery_entries_v1":
                entries_call = call
                break

        assert entries_call is not None
        mappings = entries_call.kwargs["body"]["mappings"]
        embedding_field = mappings["properties"]["embedding"]

        assert embedding_field["type"] == "dense_vector"
        assert embedding_field["dims"] == 768
        assert embedding_field["similarity"] == "cosine"
        assert embedding_field["index_options"]["type"] == "bbq_hnsw"
        assert embedding_field["index_options"]["m"] == 16
        assert embedding_field["index_options"]["ef_construction"] == 100

    @pytest.mark.unit
    async def test_initialize_skips_existing_indices(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """initialize() does not create indices that already exist."""
        es_client.indices.exists.return_value = True

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
        )
        await store.initialize()

        assert es_client.indices.create.call_count == 0

    @pytest.mark.unit
    async def test_initialize_is_idempotent(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """Calling initialize() multiple times is safe."""
        es_client.indices.exists.return_value = False

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
        )
        await store.initialize()
        await store.initialize()  # second call should be no-op

        # Only 3 creates from the first call.
        assert es_client.indices.create.call_count == 3

    @pytest.mark.unit
    async def test_initialize_custom_prefix(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """initialize() uses a custom index prefix."""
        es_client.indices.exists.return_value = False

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            index_prefix="myteam",
        )
        await store.initialize()

        created_indices = [
            call.kwargs["index"] for call in es_client.indices.create.call_args_list
        ]
        assert "myteam_entries_v1" in created_indices
        assert "myteam_search_log_v1" in created_indices
        assert "myteam_feedback_log_v1" in created_indices


# ---------------------------------------------------------------------------
# CRUD operation tests
# ---------------------------------------------------------------------------


class TestCrudOperations:
    """Tests for store/get/update/delete operations."""

    @pytest.mark.unit
    async def test_store_and_get_roundtrip(self, es_store: ElasticsearchStore) -> None:
        """store() indexes an entry, get() retrieves it."""
        entry = _make_entry(content="Python asyncio patterns")
        entry_id = entry.id

        # Configure mock to return stored document on get.
        now = datetime.now(tz=UTC)
        es_store.client.get.return_value = {
            "_id": entry_id,
            "_source": {
                "content": "Python asyncio patterns",
                "entry_type": "inbox",
                "source": "manual",
                "author": "tester",
                "project": None,
                "tags": [],
                "status": "active",
                "metadata": "{}",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "version": 1,
                "embedding": [0.1] * 768,
                "accessed_at": None,
            },
        }

        result_id = await es_store.store(entry)
        assert result_id == entry_id

        # Verify index was called.
        es_store.client.index.assert_called_once()
        call_kwargs = es_store.client.index.call_args.kwargs
        assert call_kwargs["index"] == "distillery_entries"
        assert call_kwargs["id"] == entry_id

        # Verify get returns the entry.
        retrieved = await es_store.get(entry_id)
        assert retrieved is not None
        assert retrieved.content == "Python asyncio patterns"
        assert retrieved.id == entry_id

    @pytest.mark.unit
    async def test_get_returns_none_for_missing_entry(
        self, es_store: ElasticsearchStore
    ) -> None:
        """get() returns None when the entry does not exist."""
        es_store.client.get.side_effect = Exception("NotFoundError")

        result = await es_store.get("missing-id")
        assert result is None

    @pytest.mark.unit
    async def test_get_returns_none_for_archived_entry(
        self, es_store: ElasticsearchStore
    ) -> None:
        """get() returns None for entries with status 'archived'."""
        es_store.client.get.return_value = {
            "_id": "archived-1",
            "_source": {
                "content": "Archived content",
                "entry_type": "inbox",
                "source": "manual",
                "author": "tester",
                "project": None,
                "tags": [],
                "status": "archived",
                "metadata": "{}",
                "created_at": datetime.now(tz=UTC).isoformat(),
                "updated_at": datetime.now(tz=UTC).isoformat(),
                "version": 1,
                "embedding": [0.1] * 768,
                "accessed_at": None,
            },
        }

        result = await es_store.get("archived-1")
        assert result is None

    @pytest.mark.unit
    async def test_store_generates_embedding(self, es_store: ElasticsearchStore) -> None:
        """store() calls the embedding provider to generate an embedding."""
        entry = _make_entry(content="Test content for embedding")

        await es_store.store(entry)

        # The document sent to ES should include the embedding.
        call_kwargs = es_store.client.index.call_args.kwargs
        doc = call_kwargs["document"]
        assert "embedding" in doc
        assert len(doc["embedding"]) == 768

    @pytest.mark.unit
    async def test_update_modifies_fields_and_increments_version(
        self, es_store: ElasticsearchStore
    ) -> None:
        """update() modifies allowed fields and increments version."""
        now = datetime.now(tz=UTC)

        # Mock existing document.
        es_store.client.get.return_value = {
            "_id": "entry-1",
            "_source": {
                "content": "Original content",
                "entry_type": "inbox",
                "source": "manual",
                "author": "tester",
                "project": None,
                "tags": [],
                "status": "active",
                "metadata": "{}",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "version": 1,
                "embedding": [0.1] * 768,
                "accessed_at": None,
            },
        }

        await es_store.update(
            "entry-1", {"tags": ["updated"], "entry_type": "reference"}
        )

        # update() should call client.update and then client.get.
        assert es_store.client.update.call_count == 1
        update_kwargs = es_store.client.update.call_args.kwargs
        doc = update_kwargs["doc"]
        assert doc["tags"] == ["updated"]
        assert doc["entry_type"] == "reference"
        assert doc["version"] == 2

    @pytest.mark.unit
    async def test_update_reembeds_on_content_change(
        self, es_store: ElasticsearchStore
    ) -> None:
        """update() re-embeds when content changes."""
        now = datetime.now(tz=UTC)

        es_store.client.get.return_value = {
            "_id": "entry-1",
            "_source": {
                "content": "old content",
                "entry_type": "inbox",
                "source": "manual",
                "author": "tester",
                "project": None,
                "tags": [],
                "status": "active",
                "metadata": "{}",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "version": 1,
                "embedding": [0.1] * 768,
                "accessed_at": None,
            },
        }

        await es_store.update("entry-1", {"content": "new content"})

        update_kwargs = es_store.client.update.call_args.kwargs
        doc = update_kwargs["doc"]
        assert "embedding" in doc
        assert len(doc["embedding"]) == 768

    @pytest.mark.unit
    async def test_update_rejects_immutable_fields(
        self, es_store: ElasticsearchStore
    ) -> None:
        """update() raises ValueError for immutable fields."""
        with pytest.raises(ValueError, match="immutable"):
            await es_store.update("entry-1", {"id": "new-id"})

        with pytest.raises(ValueError, match="immutable"):
            await es_store.update("entry-1", {"created_at": datetime.now(tz=UTC)})

        with pytest.raises(ValueError, match="immutable"):
            await es_store.update("entry-1", {"source": "new-source"})

    @pytest.mark.unit
    async def test_update_raises_keyerror_for_missing_entry(
        self, es_store: ElasticsearchStore
    ) -> None:
        """update() raises KeyError when the entry does not exist."""
        es_store.client.get.side_effect = Exception("NotFoundError")

        with pytest.raises(KeyError, match="No entry found"):
            await es_store.update("missing-id", {"content": "new"})

    @pytest.mark.unit
    async def test_delete_soft_deletes(self, es_store: ElasticsearchStore) -> None:
        """delete() sets status to archived."""
        result = await es_store.delete("entry-1")
        assert result is True

        es_store.client.update.assert_called_once()
        update_kwargs = es_store.client.update.call_args.kwargs
        assert update_kwargs["doc"]["status"] == "archived"

    @pytest.mark.unit
    async def test_delete_returns_false_for_missing(
        self, es_store: ElasticsearchStore
    ) -> None:
        """delete() returns False when the entry does not exist."""
        es_store.client.update.side_effect = Exception("NotFoundError")

        result = await es_store.delete("missing-id")
        assert result is False


# ---------------------------------------------------------------------------
# Serialization helper tests
# ---------------------------------------------------------------------------


class TestSerializationHelpers:
    """Tests for _entry_to_doc and _doc_to_entry helpers."""

    @pytest.mark.unit
    def test_entry_to_doc_roundtrip(self) -> None:
        """_entry_to_doc produces a valid document that _doc_to_entry can restore."""
        entry = _make_entry(
            content="Test roundtrip",
            tags=["test/roundtrip"],
            metadata={"key": "value"},
        )
        embedding = [0.5] * 10

        doc = _entry_to_doc(entry, embedding)

        assert doc["content"] == "Test roundtrip"
        assert doc["tags"] == ["test/roundtrip"]
        assert doc["embedding"] == embedding
        assert doc["metadata"] == '{"key": "value"}'

        restored = _doc_to_entry(entry.id, doc)
        assert restored.id == entry.id
        assert restored.content == entry.content
        assert restored.tags == entry.tags
        assert restored.metadata == {"key": "value"}

    @pytest.mark.unit
    def test_doc_to_entry_handles_dict_metadata(self) -> None:
        """_doc_to_entry handles metadata as a dict (not JSON string)."""
        now = datetime.now(tz=UTC)
        doc: dict[str, Any] = {
            "content": "Test",
            "entry_type": "inbox",
            "source": "manual",
            "author": "tester",
            "project": None,
            "tags": [],
            "status": "active",
            "metadata": {"nested": True},
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "version": 1,
            "accessed_at": None,
        }

        entry = _doc_to_entry("test-id", doc)
        assert entry.metadata == {"nested": True}


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------


class TestElasticsearchConfigValidation:
    """Tests for Elasticsearch config parsing and validation."""

    @pytest.mark.unit
    def test_valid_config_with_url(self, tmp_path: Any) -> None:
        """Valid ES config with url is accepted."""
        from distillery.config import load_config

        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(
            """
storage:
  backend: elasticsearch
  url: https://my-project.es.us-east-1.aws.elastic.cloud
  api_key_env: ELASTICSEARCH_API_KEY
"""
        )

        with patch.dict(os.environ, {"ELASTICSEARCH_API_KEY": "test-key-123"}):
            config = load_config(str(config_file))

        assert config.storage.backend == "elasticsearch"
        assert config.storage.url == "https://my-project.es.us-east-1.aws.elastic.cloud"
        assert config.storage.api_key_env == "ELASTICSEARCH_API_KEY"
        assert config.storage.index_prefix == "distillery"
        assert config.storage.embedding_mode == "client"

    @pytest.mark.unit
    def test_valid_config_with_cloud_id_env(self, tmp_path: Any) -> None:
        """Valid ES config with cloud_id_env is accepted."""
        from distillery.config import load_config

        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(
            """
storage:
  backend: elasticsearch
  cloud_id_env: ELASTICSEARCH_CLOUD_ID
  api_key_env: ELASTICSEARCH_API_KEY
"""
        )

        with patch.dict(
            os.environ,
            {
                "ELASTICSEARCH_CLOUD_ID": "my-cloud-id",
                "ELASTICSEARCH_API_KEY": "test-key-123",
            },
        ):
            config = load_config(str(config_file))

        assert config.storage.backend == "elasticsearch"
        assert config.storage.cloud_id_env == "ELASTICSEARCH_CLOUD_ID"

    @pytest.mark.unit
    def test_custom_prefix_and_embedding_mode(self, tmp_path: Any) -> None:
        """Custom index_prefix and embedding_mode are parsed."""
        from distillery.config import load_config

        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(
            """
storage:
  backend: elasticsearch
  url: https://es.example.com
  api_key_env: ES_KEY
  index_prefix: myteam
  embedding_mode: server
"""
        )

        with patch.dict(os.environ, {"ES_KEY": "key-val"}):
            config = load_config(str(config_file))

        assert config.storage.index_prefix == "myteam"
        assert config.storage.embedding_mode == "server"

    @pytest.mark.unit
    def test_config_without_url_or_cloud_id_fails(self, tmp_path: Any) -> None:
        """Config without url or cloud_id_env fails validation."""
        from distillery.config import load_config

        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(
            """
storage:
  backend: elasticsearch
  api_key_env: ES_KEY
"""
        )

        with patch.dict(os.environ, {"ES_KEY": "key-val"}), pytest.raises(
            ValueError, match="url.*cloud_id_env"
        ):
            load_config(str(config_file))

    @pytest.mark.unit
    def test_config_without_api_key_env_fails(self, tmp_path: Any) -> None:
        """Config without api_key_env fails validation."""
        from distillery.config import load_config

        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(
            """
storage:
  backend: elasticsearch
  url: https://es.example.com
"""
        )

        with pytest.raises(ValueError, match="api_key_env"):
            load_config(str(config_file))

    @pytest.mark.unit
    def test_config_with_empty_api_key_env_fails(self, tmp_path: Any) -> None:
        """Config with empty api_key_env value fails validation."""
        from distillery.config import load_config

        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(
            """
storage:
  backend: elasticsearch
  url: https://es.example.com
  api_key_env: ELASTICSEARCH_API_KEY
"""
        )

        # Remove the key to simulate unset.
        env = os.environ.copy()
        env.pop("ELASTICSEARCH_API_KEY", None)
        with patch.dict(os.environ, env, clear=True), pytest.raises(
            ValueError, match="not set"
        ):
            load_config(str(config_file))

    @pytest.mark.unit
    def test_invalid_embedding_mode_fails(self, tmp_path: Any) -> None:
        """Config with invalid embedding_mode fails validation."""
        from distillery.config import load_config

        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(
            """
storage:
  backend: elasticsearch
  url: https://es.example.com
  api_key_env: ES_KEY
  embedding_mode: invalid
"""
        )

        with patch.dict(os.environ, {"ES_KEY": "key-val"}), pytest.raises(
            ValueError, match="embedding_mode"
        ):
            load_config(str(config_file))

    @pytest.mark.unit
    def test_elasticsearch_in_valid_backends(self, tmp_path: Any) -> None:
        """'elasticsearch' is accepted as a valid backend value."""
        from distillery.config import load_config

        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(
            """
storage:
  backend: elasticsearch
  url: https://es.example.com
  api_key_env: ES_KEY
"""
        )

        with patch.dict(os.environ, {"ES_KEY": "key-val"}):
            config = load_config(str(config_file))
            assert config.storage.backend == "elasticsearch"


# ---------------------------------------------------------------------------
# Close / lifecycle tests
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Tests for store lifecycle management."""

    @pytest.mark.unit
    async def test_close_calls_client_close(self, es_store: ElasticsearchStore) -> None:
        """close() closes the underlying ES client."""
        await es_store.close()
        es_store.client.close.assert_called_once()


# ---------------------------------------------------------------------------
# Helper: build mock ES search response
# ---------------------------------------------------------------------------


def _es_search_response(hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a mock ES search response from a list of hit dicts.

    Each dict in *hits* must contain ``_id``, ``_score``, and ``_source``.
    """
    return {"hits": {"hits": hits, "total": {"value": len(hits)}}}


def _make_hit(
    entry_id: str,
    es_score: float,
    content: str = "content",
    entry_type: str = "inbox",
    author: str = "tester",
    project: str | None = None,
    tags: list[str] | None = None,
    status: str = "active",
) -> dict[str, Any]:
    """Build a single ES hit dict."""
    now = datetime.now(tz=UTC)
    return {
        "_id": entry_id,
        "_score": es_score,
        "_source": {
            "content": content,
            "entry_type": entry_type,
            "source": "manual",
            "author": author,
            "project": project,
            "tags": tags or [],
            "status": status,
            "metadata": "{}",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "version": 1,
            "embedding": [0.1] * 768,
            "accessed_at": None,
        },
    }


# ---------------------------------------------------------------------------
# Search operation tests (T02)
# ---------------------------------------------------------------------------


class TestSearch:
    """Tests for ElasticsearchStore.search()."""

    @pytest.mark.unit
    async def test_search_returns_results_ranked_by_score(
        self, es_store: ElasticsearchStore
    ) -> None:
        """search() returns SearchResult objects ordered by descending score."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.95, content="best match"),
                _make_hit("id-2", 0.80, content="second match"),
                _make_hit("id-3", 0.65, content="third match"),
            ])
        )

        results = await es_store.search("test query", None, 10)

        assert len(results) == 3
        assert results[0].entry.id == "id-1"
        assert results[1].entry.id == "id-2"
        assert results[2].entry.id == "id-3"
        # Scores should be converted: 2 * es_score - 1
        assert results[0].score == pytest.approx(0.90, abs=0.01)
        assert results[1].score == pytest.approx(0.60, abs=0.01)
        assert results[2].score == pytest.approx(0.30, abs=0.01)

    @pytest.mark.unit
    async def test_search_calls_embedding_provider(
        self, es_store: ElasticsearchStore
    ) -> None:
        """search() in client mode calls EmbeddingProvider.embed()."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([])
        )

        await es_store.search("test query", None, 5)

        # The kNN search should use the embedding vector.
        call_kwargs = es_store.client.search.call_args.kwargs
        assert "knn" in call_kwargs
        assert call_kwargs["knn"]["field"] == "embedding"
        assert len(call_kwargs["knn"]["query_vector"]) == 768

    @pytest.mark.unit
    async def test_search_applies_entry_type_filter(
        self, es_store: ElasticsearchStore
    ) -> None:
        """search() includes a term filter for entry_type."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.9, entry_type="session"),
            ])
        )

        await es_store.search("auth", {"entry_type": "session"}, 10)

        call_kwargs = es_store.client.search.call_args.kwargs
        knn_filter = call_kwargs["knn"]["filter"]
        filter_clauses = knn_filter["bool"]["filter"]
        assert {"term": {"entry_type": "session"}} in filter_clauses

    @pytest.mark.unit
    async def test_search_applies_author_filter(
        self, es_store: ElasticsearchStore
    ) -> None:
        """search() includes a term filter for author."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.85, author="alice"),
            ])
        )

        await es_store.search("deploy", {"author": "alice"}, 10)

        call_kwargs = es_store.client.search.call_args.kwargs
        filter_clauses = call_kwargs["knn"]["filter"]["bool"]["filter"]
        assert {"term": {"author": "alice"}} in filter_clauses

    @pytest.mark.unit
    async def test_search_applies_project_filter(
        self, es_store: ElasticsearchStore
    ) -> None:
        """search() includes a term filter for project."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.85, project="billing-v2"),
            ])
        )

        await es_store.search("API", {"project": "billing-v2"}, 10)

        call_kwargs = es_store.client.search.call_args.kwargs
        filter_clauses = call_kwargs["knn"]["filter"]["bool"]["filter"]
        assert {"term": {"project": "billing-v2"}} in filter_clauses

    @pytest.mark.unit
    async def test_search_applies_tags_filter_any_match(
        self, es_store: ElasticsearchStore
    ) -> None:
        """search() includes a terms filter for tags (any-match semantics)."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.85, tags=["python", "ci"]),
            ])
        )

        await es_store.search("testing", {"tags": ["python", "ci"]}, 10)

        call_kwargs = es_store.client.search.call_args.kwargs
        filter_clauses = call_kwargs["knn"]["filter"]["bool"]["filter"]
        assert {"terms": {"tags": ["python", "ci"]}} in filter_clauses

    @pytest.mark.unit
    async def test_search_applies_status_filter(
        self, es_store: ElasticsearchStore
    ) -> None:
        """search() includes a term filter for status."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.85, status="active"),
            ])
        )

        await es_store.search("patterns", {"status": "active"}, 10)

        call_kwargs = es_store.client.search.call_args.kwargs
        filter_clauses = call_kwargs["knn"]["filter"]["bool"]["filter"]
        assert {"term": {"status": "active"}} in filter_clauses

    @pytest.mark.unit
    async def test_search_applies_date_range_filter(
        self, es_store: ElasticsearchStore
    ) -> None:
        """search() includes a range filter for date_from and date_to."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.85),
            ])
        )

        await es_store.search(
            "release notes",
            {"date_from": "2026-01-01", "date_to": "2026-03-01"},
            10,
        )

        call_kwargs = es_store.client.search.call_args.kwargs
        filter_clauses = call_kwargs["knn"]["filter"]["bool"]["filter"]
        assert {
            "range": {"created_at": {"gte": "2026-01-01", "lte": "2026-03-01"}}
        } in filter_clauses

    @pytest.mark.unit
    async def test_search_applies_multiple_filters(
        self, es_store: ElasticsearchStore
    ) -> None:
        """search() applies all filters simultaneously."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.85, entry_type="session", author="bob", status="active"),
            ])
        )

        await es_store.search(
            "refactoring",
            {"entry_type": "session", "author": "bob", "status": "active"},
            10,
        )

        call_kwargs = es_store.client.search.call_args.kwargs
        filter_clauses = call_kwargs["knn"]["filter"]["bool"]["filter"]
        assert {"term": {"entry_type": "session"}} in filter_clauses
        assert {"term": {"author": "bob"}} in filter_clauses
        assert {"term": {"status": "active"}} in filter_clauses

    @pytest.mark.unit
    async def test_search_no_filters_omits_filter_clause(
        self, es_store: ElasticsearchStore
    ) -> None:
        """search() without filters does not include a filter clause in kNN."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([])
        )

        await es_store.search("test", None, 5)

        call_kwargs = es_store.client.search.call_args.kwargs
        assert "filter" not in call_kwargs["knn"]


# ---------------------------------------------------------------------------
# Score conversion tests (T02)
# ---------------------------------------------------------------------------


class TestScoreConversion:
    """Tests for ES cosine score conversion to [0, 1] range."""

    @pytest.mark.unit
    def test_score_085_converts_to_070(self) -> None:
        """ES score 0.85 -> cosine 0.70."""
        assert ElasticsearchStore._convert_es_score(0.85) == pytest.approx(0.70)

    @pytest.mark.unit
    def test_perfect_score_converts_to_1(self) -> None:
        """ES score 1.0 -> cosine 1.0."""
        assert ElasticsearchStore._convert_es_score(1.0) == pytest.approx(1.0)

    @pytest.mark.unit
    def test_orthogonal_score_converts_to_0(self) -> None:
        """ES score 0.5 -> cosine 0.0."""
        assert ElasticsearchStore._convert_es_score(0.5) == pytest.approx(0.0)

    @pytest.mark.unit
    def test_score_clamps_below_zero(self) -> None:
        """ES scores below 0.5 clamp to 0.0."""
        assert ElasticsearchStore._convert_es_score(0.3) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# find_similar tests (T02)
# ---------------------------------------------------------------------------


class TestFindSimilar:
    """Tests for ElasticsearchStore.find_similar()."""

    @pytest.mark.unit
    async def test_find_similar_returns_entries_above_threshold(
        self, es_store: ElasticsearchStore
    ) -> None:
        """find_similar() returns only entries above the threshold."""
        # ES scores for cosine similarities 0.97, 0.88, 0.72, 0.45
        # ES score = (1 + cosine) / 2 -> 0.985, 0.94, 0.86, 0.725
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.985, content="near duplicate"),
                _make_hit("id-2", 0.94, content="similar"),
            ])
        )

        results = await es_store.find_similar("test content", threshold=0.80, limit=10)

        assert len(results) == 2
        assert results[0].score >= 0.80
        assert results[1].score >= 0.80

    @pytest.mark.unit
    async def test_find_similar_skip_threshold(
        self, es_store: ElasticsearchStore
    ) -> None:
        """find_similar() with 0.95 threshold identifies exact duplicates."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.985, content="near duplicate"),  # cosine = 0.97
            ])
        )

        results = await es_store.find_similar("test content", threshold=0.95, limit=10)

        assert len(results) == 1
        assert results[0].score >= 0.95

    @pytest.mark.unit
    async def test_find_similar_link_threshold(
        self, es_store: ElasticsearchStore
    ) -> None:
        """find_similar() with 0.60 threshold identifies related content."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 0.86, content="related a"),  # cosine = 0.72
                _make_hit("id-2", 0.825, content="related b"),  # cosine = 0.65
            ])
        )

        results = await es_store.find_similar("test content", threshold=0.60, limit=10)

        assert len(results) == 2
        assert all(r.score >= 0.60 for r in results)

    @pytest.mark.unit
    async def test_find_similar_empty_when_below_threshold(
        self, es_store: ElasticsearchStore
    ) -> None:
        """find_similar() returns empty when no entries meet the threshold."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([])
        )

        results = await es_store.find_similar("test content", threshold=0.80, limit=10)

        assert results == []

    @pytest.mark.unit
    async def test_find_similar_passes_similarity_to_knn(
        self, es_store: ElasticsearchStore
    ) -> None:
        """find_similar() passes the min ES score as similarity to kNN."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([])
        )

        await es_store.find_similar("test", threshold=0.80, limit=5)

        call_kwargs = es_store.client.search.call_args.kwargs
        knn = call_kwargs["knn"]
        # threshold 0.80 -> ES score = (1 + 0.80) / 2 = 0.90
        assert knn["similarity"] == pytest.approx(0.90)


# ---------------------------------------------------------------------------
# list_entries tests (T02)
# ---------------------------------------------------------------------------


class TestListEntries:
    """Tests for ElasticsearchStore.list_entries()."""

    @pytest.mark.unit
    async def test_list_entries_returns_sorted_by_created_at(
        self, es_store: ElasticsearchStore
    ) -> None:
        """list_entries() sorts by created_at descending."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 1.0, content="newest"),
                _make_hit("id-2", 1.0, content="oldest"),
            ])
        )

        results = await es_store.list_entries(None, 10, 0)

        assert len(results) == 2
        call_kwargs = es_store.client.search.call_args.kwargs
        body = call_kwargs["body"]
        assert body["sort"] == [{"created_at": {"order": "desc"}}]

    @pytest.mark.unit
    async def test_list_entries_pagination(
        self, es_store: ElasticsearchStore
    ) -> None:
        """list_entries() uses from/size for pagination."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([])
        )

        await es_store.list_entries(None, 10, 5)

        call_kwargs = es_store.client.search.call_args.kwargs
        body = call_kwargs["body"]
        assert body["from"] == 5
        assert body["size"] == 10

    @pytest.mark.unit
    async def test_list_entries_applies_filters(
        self, es_store: ElasticsearchStore
    ) -> None:
        """list_entries() applies metadata filters as bool query clauses."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([
                _make_hit("id-1", 1.0, entry_type="bookmark", status="active"),
            ])
        )

        await es_store.list_entries(
            {"entry_type": "bookmark", "status": "active"}, 10, 0
        )

        call_kwargs = es_store.client.search.call_args.kwargs
        body = call_kwargs["body"]
        filter_clauses = body["query"]["bool"]["filter"]
        assert {"term": {"entry_type": "bookmark"}} in filter_clauses
        assert {"term": {"status": "active"}} in filter_clauses

    @pytest.mark.unit
    async def test_list_entries_no_filters_uses_match_all(
        self, es_store: ElasticsearchStore
    ) -> None:
        """list_entries() without filters uses match_all query."""
        es_store.client.search = AsyncMock(
            return_value=_es_search_response([])
        )

        await es_store.list_entries(None, 10, 0)

        call_kwargs = es_store.client.search.call_args.kwargs
        body = call_kwargs["body"]
        assert "match_all" in body["query"]


# ---------------------------------------------------------------------------
# Dual embedding mode tests (T02)
# ---------------------------------------------------------------------------


class TestEmbeddingModeSelection:
    """Tests for client/server/auto embedding mode switching."""

    @pytest.mark.unit
    async def test_client_mode_calls_embedding_provider_on_store(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """Client mode calls EmbeddingProvider.embed() during store()."""
        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            embedding_mode="client",
        )
        await store.initialize()

        entry = _make_entry(content="test client mode")
        await store.store(entry)

        # Embedding should be in the document.
        doc = es_client.index.call_args.kwargs["document"]
        assert len(doc["embedding"]) == 768
        assert "content_semantic" not in doc

    @pytest.mark.unit
    async def test_client_mode_calls_embedding_provider_on_search(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """Client mode calls EmbeddingProvider.embed() during search()."""
        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            embedding_mode="client",
        )
        await store.initialize()
        es_client.search = AsyncMock(return_value=_es_search_response([]))

        await store.search("test query", None, 5)

        call_kwargs = es_client.search.call_args.kwargs
        assert "knn" in call_kwargs
        assert len(call_kwargs["knn"]["query_vector"]) == 768

    @pytest.mark.unit
    async def test_server_mode_skips_embedding_on_store(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """Server mode does NOT call EmbeddingProvider.embed() during store()."""
        # Mock inference detection.
        es_client.inference = AsyncMock()
        es_client.inference.get = AsyncMock(
            return_value={"endpoints": [{"inference_id": "my-model"}]}
        )

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            embedding_mode="server",
        )
        await store.initialize()

        entry = _make_entry(content="test server mode")
        await store.store(entry)

        doc = es_client.index.call_args.kwargs["document"]
        # Embedding should be empty in server mode.
        assert doc["embedding"] == []
        # content_semantic field should be populated.
        assert doc["content_semantic"] == "test server mode"

    @pytest.mark.unit
    async def test_server_mode_uses_semantic_query_on_search(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """Server mode uses semantic query instead of kNN on search()."""
        es_client.inference = AsyncMock()
        es_client.inference.get = AsyncMock(
            return_value={"endpoints": [{"inference_id": "my-model"}]}
        )

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            embedding_mode="server",
        )
        await store.initialize()
        es_client.search = AsyncMock(return_value=_es_search_response([]))

        await store.search("test query", None, 5)

        call_kwargs = es_client.search.call_args.kwargs
        # Should NOT have knn.
        assert "knn" not in call_kwargs
        # Should have semantic query in body.
        body = call_kwargs["body"]
        assert "semantic" in body["query"]["bool"]["must"][0]

    @pytest.mark.unit
    async def test_auto_mode_selects_server_when_inference_available(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """Auto mode selects server when inference endpoint is available."""
        es_client.inference = AsyncMock()
        es_client.inference.get = AsyncMock(
            return_value={"endpoints": [{"inference_id": "my-model"}]}
        )

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            embedding_mode="auto",
        )
        await store.initialize()

        assert store.effective_embedding_mode == "server"

    @pytest.mark.unit
    async def test_auto_mode_selects_client_when_no_inference(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """Auto mode selects client when no inference endpoint exists."""
        es_client.inference = AsyncMock()
        es_client.inference.get = AsyncMock(side_effect=Exception("not found"))

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            embedding_mode="auto",
        )
        await store.initialize()

        assert store.effective_embedding_mode == "client"

    @pytest.mark.unit
    async def test_auto_mode_selects_client_when_empty_endpoints(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """Auto mode selects client when endpoint list is empty."""
        es_client.inference = AsyncMock()
        es_client.inference.get = AsyncMock(return_value={"endpoints": []})

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            embedding_mode="auto",
        )
        await store.initialize()

        assert store.effective_embedding_mode == "client"

    @pytest.mark.unit
    async def test_server_mode_adds_semantic_text_mapping(
        self, es_client: AsyncMock, embedding_provider: MockEmbeddingProvider
    ) -> None:
        """Server mode adds content_semantic field to index mappings."""
        es_client.indices.exists.return_value = False
        es_client.inference = AsyncMock()
        es_client.inference.get = AsyncMock(
            return_value={"endpoints": [{"inference_id": "my-model"}]}
        )

        store = ElasticsearchStore(
            client=es_client,
            embedding_provider=embedding_provider,
            embedding_mode="server",
        )
        await store.initialize()

        # Find entries index creation call.
        entries_call = None
        for call in es_client.indices.create.call_args_list:
            if call.kwargs["index"].endswith("entries_v1"):
                entries_call = call
                break

        assert entries_call is not None
        mappings = entries_call.kwargs["body"]["mappings"]
        assert "content_semantic" in mappings["properties"]
        assert mappings["properties"]["content_semantic"]["type"] == "semantic_text"
        assert mappings["properties"]["content_semantic"]["inference_id"] == "my-model"


# ---------------------------------------------------------------------------
# Filter builder tests (T02)
# ---------------------------------------------------------------------------


class TestBuildFilterClauses:
    """Tests for the static _build_filter_clauses helper."""

    @pytest.mark.unit
    def test_none_filters_returns_empty(self) -> None:
        """None filters returns empty list."""
        assert ElasticsearchStore._build_filter_clauses(None) == []

    @pytest.mark.unit
    def test_empty_dict_returns_empty(self) -> None:
        """Empty dict returns empty list."""
        assert ElasticsearchStore._build_filter_clauses({}) == []

    @pytest.mark.unit
    def test_entry_type_filter(self) -> None:
        """entry_type becomes a term clause."""
        clauses = ElasticsearchStore._build_filter_clauses({"entry_type": "session"})
        assert {"term": {"entry_type": "session"}} in clauses

    @pytest.mark.unit
    def test_tags_filter(self) -> None:
        """tags becomes a terms clause."""
        clauses = ElasticsearchStore._build_filter_clauses({"tags": ["a", "b"]})
        assert {"terms": {"tags": ["a", "b"]}} in clauses

    @pytest.mark.unit
    def test_date_range_filter(self) -> None:
        """date_from and date_to become a range clause."""
        clauses = ElasticsearchStore._build_filter_clauses(
            {"date_from": "2026-01-01", "date_to": "2026-03-01"}
        )
        assert {
            "range": {"created_at": {"gte": "2026-01-01", "lte": "2026-03-01"}}
        } in clauses

    @pytest.mark.unit
    def test_date_from_only(self) -> None:
        """date_from alone creates a range with gte only."""
        clauses = ElasticsearchStore._build_filter_clauses({"date_from": "2026-01-01"})
        assert {"range": {"created_at": {"gte": "2026-01-01"}}} in clauses

    @pytest.mark.unit
    def test_multiple_filters_combined(self) -> None:
        """Multiple filter keys produce multiple clauses."""
        clauses = ElasticsearchStore._build_filter_clauses(
            {"entry_type": "session", "author": "alice", "status": "active"}
        )
        assert len(clauses) == 3
