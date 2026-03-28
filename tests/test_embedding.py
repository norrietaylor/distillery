"""Tests for EmbeddingProvider implementations.

Covers:
- EmbeddingProvider protocol interface compliance for JinaEmbeddingProvider
  and OpenAIEmbeddingProvider
- model_name and dimensions properties
- Error handling (invalid API keys, malformed responses, non-retryable errors)
- Rate limiting and exponential backoff behaviour via mocked HTTP responses

All HTTP calls are intercepted using unittest.mock so no real API requests
are made.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from distillery.embedding.jina import JinaEmbeddingProvider
from distillery.embedding.openai import OpenAIEmbeddingProvider

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jina_response(embeddings: list[list[float]]) -> dict:
    """Build a dict that mimics the Jina API response payload."""
    return {"data": [{"embedding": emb, "index": i} for i, emb in enumerate(embeddings)]}


def _make_openai_response(embeddings: list[list[float]]) -> dict:
    """Build a dict that mimics the OpenAI API response payload."""
    return {
        "data": [{"embedding": emb, "index": i} for i, emb in enumerate(embeddings)],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }


def _mock_httpx_response(status_code: int, json_body: dict) -> MagicMock:
    """Return a mock httpx.Response for the given status code and JSON body."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_body
    mock_resp.text = json.dumps(json_body)
    return mock_resp


# ---------------------------------------------------------------------------
# EmbeddingProvider protocol compliance: JinaEmbeddingProvider
# ---------------------------------------------------------------------------


class TestJinaEmbeddingProviderProtocolCompliance:
    """Verify that JinaEmbeddingProvider satisfies the EmbeddingProvider protocol."""

    def _provider(self) -> JinaEmbeddingProvider:
        return JinaEmbeddingProvider(api_key="test-key", dimensions=4)

    def test_is_protocol_compatible(self) -> None:
        """JinaEmbeddingProvider must satisfy the EmbeddingProvider protocol."""

        provider = self._provider()
        # Check all required protocol members are present
        assert hasattr(provider, "embed")
        assert hasattr(provider, "embed_batch")
        assert hasattr(provider, "dimensions")
        assert hasattr(provider, "model_name")
        assert callable(provider.embed)
        assert callable(provider.embed_batch)

    def test_model_name_property(self) -> None:
        provider = JinaEmbeddingProvider(
            api_key="test-key",
            model="jina-embeddings-v3",
        )
        assert provider.model_name == "jina-embeddings-v3"

    def test_model_name_custom(self) -> None:
        provider = JinaEmbeddingProvider(
            api_key="test-key",
            model="jina-custom-model",
        )
        assert provider.model_name == "jina-custom-model"

    def test_dimensions_property(self) -> None:
        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=512)
        assert provider.dimensions == 512

    def test_dimensions_default(self) -> None:
        provider = JinaEmbeddingProvider(api_key="test-key")
        assert provider.dimensions == 1024

    def test_dimensions_is_int(self) -> None:
        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=256)
        assert isinstance(provider.dimensions, int)

    def test_model_name_is_str(self) -> None:
        provider = self._provider()
        assert isinstance(provider.model_name, str)


# ---------------------------------------------------------------------------
# JinaEmbeddingProvider: error handling
# ---------------------------------------------------------------------------


class TestJinaEmbeddingProviderErrors:
    def test_raises_value_error_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No api_key and no env var must raise ValueError."""
        monkeypatch.delenv("JINA_API_KEY", raising=False)
        with pytest.raises(ValueError, match="JINA_API_KEY"):
            JinaEmbeddingProvider()

    def test_reads_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When api_key_env var is set the provider initialises without error."""
        monkeypatch.setenv("JINA_API_KEY", "env-test-key")
        provider = JinaEmbeddingProvider()
        assert provider is not None

    def test_non_retryable_4xx_raises_runtime_error(self) -> None:
        """HTTP 401 (non-retryable) raises RuntimeError immediately."""
        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 401
        error_response.text = "Unauthorized"

        http_error = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=error_response,
        )

        provider = JinaEmbeddingProvider(api_key="bad-key", dimensions=4)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value.raise_for_status.side_effect = http_error

            with pytest.raises(RuntimeError, match="401"):
                provider.embed("test text")

    def test_malformed_response_missing_data_raises_runtime_error(self) -> None:
        """A response without a 'data' key raises RuntimeError."""
        bad_response = _mock_httpx_response(200, {"unexpected": "structure"})

        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=4)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = bad_response
            bad_response.raise_for_status.return_value = None

            with pytest.raises(RuntimeError, match="'data'"):
                provider.embed("test text")

    def test_malformed_response_wrong_count_raises_runtime_error(self) -> None:
        """Response with wrong embedding count raises RuntimeError."""
        # Request 1 embedding but response returns 2
        bad_payload = _make_jina_response([[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]])
        bad_response = _mock_httpx_response(200, bad_payload)

        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=4)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = bad_response
            bad_response.raise_for_status.return_value = None

            with pytest.raises(RuntimeError, match="2 embeddings"):
                provider.embed("test text")


# ---------------------------------------------------------------------------
# JinaEmbeddingProvider: rate limiting and retry behaviour
# ---------------------------------------------------------------------------


class TestJinaRateLimitRetry:
    def test_retries_on_429_and_succeeds(self) -> None:
        """A 429 response on the first attempt triggers retry; second succeeds."""
        good_payload = _make_jina_response([[0.1, 0.2, 0.3, 0.4]])
        good_response = _mock_httpx_response(200, good_payload)
        good_response.raise_for_status.return_value = None

        rate_limit_response = MagicMock(spec=httpx.Response)
        rate_limit_response.status_code = 429
        rate_limit_response.text = "Rate limit exceeded"
        rate_limit_error = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=rate_limit_response,
        )

        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=4)

        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            mock_resp = MagicMock()
            if call_count["n"] == 1:
                # First attempt: raises rate limit error
                mock_resp.raise_for_status.side_effect = rate_limit_error
            else:
                # Second attempt: success
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = good_payload
                mock_resp.status_code = 200
            return mock_resp

        with patch("httpx.Client") as mock_client_cls, patch("time.sleep") as mock_sleep:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.side_effect = side_effect

            result = provider.embed("test text")

        assert result == [0.1, 0.2, 0.3, 0.4]
        assert call_count["n"] == 2
        assert mock_sleep.call_count >= 1

    def test_retries_on_500_server_error(self) -> None:
        """5xx server errors trigger retries with backoff."""
        good_payload = _make_jina_response([[0.1, 0.2, 0.3, 0.4]])

        server_error_response = MagicMock(spec=httpx.Response)
        server_error_response.status_code = 500
        server_error_response.text = "Internal Server Error"
        server_error = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=server_error_response,
        )

        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=4)
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            mock_resp = MagicMock()
            if call_count["n"] == 1:
                mock_resp.raise_for_status.side_effect = server_error
            else:
                mock_resp.raise_for_status.return_value = None
                mock_resp.json.return_value = good_payload
                mock_resp.status_code = 200
            return mock_resp

        with patch("httpx.Client") as mock_client_cls, patch("time.sleep"):
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.side_effect = side_effect

            result = provider.embed("test text")

        assert result == [0.1, 0.2, 0.3, 0.4]
        assert call_count["n"] == 2

    def test_exhausted_retries_raise_runtime_error(self) -> None:
        """After MAX_RETRIES consecutive 429 responses RuntimeError is raised."""
        rate_limit_response = MagicMock(spec=httpx.Response)
        rate_limit_response.status_code = 429
        rate_limit_response.text = "Rate limit exceeded"
        rate_limit_error = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=rate_limit_response,
        )

        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=4)

        with patch("httpx.Client") as mock_client_cls, patch("time.sleep"):
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = rate_limit_error
            mock_client.post.return_value = mock_resp

            with pytest.raises(RuntimeError, match="3 attempts"):
                provider.embed("test text")

    def test_embed_batch_empty_list_returns_empty(self) -> None:
        """embed_batch([]) must return [] without hitting the API."""
        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=4)

        with patch("httpx.Client") as mock_client_cls:
            result = provider.embed_batch([])

        assert result == []
        mock_client_cls.assert_not_called()

    def test_embed_delegates_to_embed_batch(self) -> None:
        """embed(text) returns the first element from embed_batch."""
        vector = [0.1, 0.2, 0.3, 0.4]
        good_payload = _make_jina_response([vector])
        good_response = _mock_httpx_response(200, good_payload)
        good_response.raise_for_status.return_value = None

        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=4)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = good_response

            result = provider.embed("hello")

        assert result == vector

    def test_embed_batch_returns_multiple_vectors(self) -> None:
        """embed_batch with multiple texts returns one vector per text."""
        vectors = [
            [0.1, 0.2, 0.3, 0.4],
            [0.5, 0.6, 0.7, 0.8],
        ]
        good_payload = _make_jina_response(vectors)
        good_response = _mock_httpx_response(200, good_payload)
        good_response.raise_for_status.return_value = None

        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=4)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = good_response

            result = provider.embed_batch(["first", "second"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3, 0.4]
        assert result[1] == [0.5, 0.6, 0.7, 0.8]


# ---------------------------------------------------------------------------
# EmbeddingProvider protocol compliance: OpenAIEmbeddingProvider
# ---------------------------------------------------------------------------


class TestOpenAIEmbeddingProviderProtocolCompliance:
    """Verify that OpenAIEmbeddingProvider satisfies the EmbeddingProvider protocol."""

    def _provider(self) -> OpenAIEmbeddingProvider:
        return OpenAIEmbeddingProvider(api_key="sk-test", dimensions=4)

    def test_is_protocol_compatible(self) -> None:
        provider = self._provider()
        assert hasattr(provider, "embed")
        assert hasattr(provider, "embed_batch")
        assert hasattr(provider, "dimensions")
        assert hasattr(provider, "model_name")
        assert callable(provider.embed)
        assert callable(provider.embed_batch)

    def test_model_name_default(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="sk-test")
        assert provider.model_name == "text-embedding-3-small"

    def test_model_name_custom(self) -> None:
        provider = OpenAIEmbeddingProvider(
            api_key="sk-test",
            model="text-embedding-3-large",
        )
        assert provider.model_name == "text-embedding-3-large"

    def test_dimensions_property(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="sk-test", dimensions=256)
        assert provider.dimensions == 256

    def test_dimensions_default(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="sk-test")
        assert provider.dimensions == 512

    def test_dimensions_is_int(self) -> None:
        provider = self._provider()
        assert isinstance(provider.dimensions, int)

    def test_model_name_is_str(self) -> None:
        provider = self._provider()
        assert isinstance(provider.model_name, str)


# ---------------------------------------------------------------------------
# OpenAIEmbeddingProvider: error handling
# ---------------------------------------------------------------------------


class TestOpenAIEmbeddingProviderErrors:
    def test_raises_value_error_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No api_key and missing env var raises ValueError."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            OpenAIEmbeddingProvider()

    def test_reads_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When env var is set the provider initialises without error."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
        provider = OpenAIEmbeddingProvider()
        assert provider is not None

    def test_non_retryable_4xx_raises_runtime_error(self) -> None:
        """HTTP 403 raises RuntimeError without retry."""
        provider = OpenAIEmbeddingProvider(api_key="sk-test", dimensions=4)

        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 403
        error_response.text = "Forbidden"

        with patch.object(provider, "_client") as mock_client:
            mock_client.post.return_value = error_response

            with pytest.raises(RuntimeError, match="403"):
                provider.embed("test text")

    def test_network_error_raises_runtime_error(self) -> None:
        """Network connectivity issues raise RuntimeError."""
        provider = OpenAIEmbeddingProvider(api_key="sk-test", dimensions=4)

        with patch.object(provider, "_client") as mock_client:
            mock_client.post.side_effect = httpx.RequestError("Connection refused")

            with pytest.raises(RuntimeError, match="Connection refused"):
                provider.embed("test text")

    def test_embed_returns_vector(self) -> None:
        """embed() calls the API and returns a float list."""
        vector = [0.1, 0.2, 0.3, 0.4]
        good_payload = _make_openai_response([vector])
        good_response = _mock_httpx_response(200, good_payload)

        provider = OpenAIEmbeddingProvider(api_key="sk-test", dimensions=4)

        with patch.object(provider, "_client") as mock_client:
            mock_client.post.return_value = good_response
            result = provider.embed("hello")

        assert result == vector

    def test_embed_batch_returns_multiple_vectors(self) -> None:
        """embed_batch returns one vector per input text, in order."""
        vectors = [
            [0.1, 0.2, 0.3, 0.4],
            [0.5, 0.6, 0.7, 0.8],
        ]
        good_payload = _make_openai_response(vectors)
        good_response = _mock_httpx_response(200, good_payload)

        provider = OpenAIEmbeddingProvider(api_key="sk-test", dimensions=4)

        with patch.object(provider, "_client") as mock_client:
            mock_client.post.return_value = good_response
            result = provider.embed_batch(["first", "second"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3, 0.4]
        assert result[1] == [0.5, 0.6, 0.7, 0.8]


# ---------------------------------------------------------------------------
# OpenAIEmbeddingProvider: rate limiting and retry behaviour
# ---------------------------------------------------------------------------


class TestOpenAIRateLimitRetry:
    def test_retries_on_429_and_succeeds(self) -> None:
        """HTTP 429 on first attempt triggers retry; second attempt succeeds.

        Note: retry logic lives in embed_batch(), so we call that directly.
        embed() delegates to _request() without retry; embed_batch() wraps
        _request() with backoff retry logic.
        """
        vector = [0.1, 0.2, 0.3, 0.4]
        good_payload = _make_openai_response([vector])
        good_response = _mock_httpx_response(200, good_payload)

        rate_limit_response = _mock_httpx_response(429, {"error": "rate limit"})

        call_count = {"n": 0}

        provider = OpenAIEmbeddingProvider(api_key="sk-test", dimensions=4)

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return rate_limit_response
            return good_response

        with patch.object(provider, "_client") as mock_client, patch("time.sleep"):
            mock_client.post.side_effect = side_effect
            result = provider.embed_batch(["test text"])

        assert result == [vector]
        assert call_count["n"] == 2

    def test_retries_on_503_server_error(self) -> None:
        """HTTP 503 on first attempt triggers retry."""
        vector = [0.5, 0.6, 0.7, 0.8]
        good_payload = _make_openai_response([vector])
        good_response = _mock_httpx_response(200, good_payload)
        server_error_response = _mock_httpx_response(503, {"error": "service unavailable"})

        call_count = {"n": 0}

        provider = OpenAIEmbeddingProvider(api_key="sk-test", dimensions=4)

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return server_error_response
            return good_response

        with patch.object(provider, "_client") as mock_client, patch("time.sleep"):
            mock_client.post.side_effect = side_effect
            result = provider.embed_batch(["test"])

        assert result == [vector]
        assert call_count["n"] == 2

    def test_exhausted_retries_raise_runtime_error(self) -> None:
        """After MAX_RETRIES consecutive 429 responses RuntimeError is raised."""
        rate_limit_response = _mock_httpx_response(429, {"error": "rate limit"})
        provider = OpenAIEmbeddingProvider(api_key="sk-test", dimensions=4)

        with patch.object(provider, "_client") as mock_client, patch("time.sleep"):
            mock_client.post.return_value = rate_limit_response
            with pytest.raises(RuntimeError, match="retries"):
                provider.embed_batch(["test"])

    def test_exponential_backoff_called(self) -> None:
        """Sleep is called with exponential backoff values on retry."""
        vector = [0.1, 0.2, 0.3, 0.4]
        good_payload = _make_openai_response([vector])
        good_response = _mock_httpx_response(200, good_payload)
        rate_limit_response = _mock_httpx_response(429, {"error": "rate limit"})

        call_count = {"n": 0}
        sleep_calls = []

        provider = OpenAIEmbeddingProvider(api_key="sk-test", dimensions=4)

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return rate_limit_response
            return good_response

        def mock_sleep(seconds):
            sleep_calls.append(seconds)

        with (
            patch.object(provider, "_client") as mock_client,
            patch("time.sleep", side_effect=mock_sleep),
        ):
            mock_client.post.side_effect = side_effect
            provider.embed_batch(["test"])

        # sleep must be called at least once with a positive backoff
        assert len(sleep_calls) >= 1
        assert all(s >= 0 for s in sleep_calls)


# ---------------------------------------------------------------------------
# Cross-provider: protocol structural validation
# ---------------------------------------------------------------------------


class TestEmbeddingProviderProtocolStructure:
    """Both providers must satisfy the EmbeddingProvider protocol via duck typing."""

    def test_jina_satisfies_protocol(self) -> None:
        """JinaEmbeddingProvider passes structural runtime check."""
        import inspect

        provider = JinaEmbeddingProvider(api_key="test-key")
        # Verify embed and embed_batch are regular (not async) callables
        assert callable(provider.embed)
        assert callable(provider.embed_batch)
        assert not inspect.iscoroutinefunction(provider.embed)
        assert not inspect.iscoroutinefunction(provider.embed_batch)

    def test_openai_satisfies_protocol(self) -> None:
        """OpenAIEmbeddingProvider passes structural runtime check."""
        import inspect

        provider = OpenAIEmbeddingProvider(api_key="sk-test")
        assert callable(provider.embed)
        assert callable(provider.embed_batch)
        assert not inspect.iscoroutinefunction(provider.embed)
        assert not inspect.iscoroutinefunction(provider.embed_batch)

    def test_jina_dimensions_positive(self) -> None:
        provider = JinaEmbeddingProvider(api_key="test-key", dimensions=128)
        assert provider.dimensions > 0

    def test_openai_dimensions_positive(self) -> None:
        provider = OpenAIEmbeddingProvider(api_key="sk-test", dimensions=256)
        assert provider.dimensions > 0


# ---------------------------------------------------------------------------
# HashEmbeddingProvider tests
# ---------------------------------------------------------------------------


class TestHashEmbeddingProvider:
    """Tests for the hash-based mock embedding provider."""

    def test_embed_returns_correct_dimensions(self) -> None:
        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        provider = HashEmbeddingProvider(dimensions=4)
        vec = provider.embed("hello world")
        assert len(vec) == 4

    def test_embed_returns_l2_normalized(self) -> None:
        import math

        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        provider = HashEmbeddingProvider(dimensions=4)
        vec = provider.embed("test input")
        magnitude = math.sqrt(sum(x * x for x in vec))
        assert abs(magnitude - 1.0) < 1e-6

    def test_embed_deterministic(self) -> None:
        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        provider = HashEmbeddingProvider(dimensions=4)
        v1 = provider.embed("same text")
        v2 = provider.embed("same text")
        assert v1 == v2

    def test_embed_different_inputs_produce_different_vectors(self) -> None:
        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        provider = HashEmbeddingProvider(dimensions=4)
        v1 = provider.embed("input A")
        v2 = provider.embed("input B")
        assert v1 != v2

    def test_embed_batch(self) -> None:
        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        provider = HashEmbeddingProvider(dimensions=4)
        results = provider.embed_batch(["aaa", "bbb", "ccc"])
        assert len(results) == 3
        assert all(len(v) == 4 for v in results)

    def test_dimensions_property(self) -> None:
        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        provider = HashEmbeddingProvider(dimensions=8)
        assert provider.dimensions == 8

    def test_default_dimensions(self) -> None:
        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        provider = HashEmbeddingProvider()
        assert provider.dimensions == 4

    def test_model_name(self) -> None:
        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        provider = HashEmbeddingProvider()
        assert provider.model_name == "mock-hash"

    def test_protocol_compliance(self) -> None:
        import inspect

        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        provider = HashEmbeddingProvider()
        assert callable(provider.embed)
        assert callable(provider.embed_batch)
        assert not inspect.iscoroutinefunction(provider.embed)
        assert not inspect.iscoroutinefunction(provider.embed_batch)
        assert isinstance(provider.dimensions, int)
        assert isinstance(provider.model_name, str)
