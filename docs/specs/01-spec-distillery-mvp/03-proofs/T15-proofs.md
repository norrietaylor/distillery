# T15 (T03.2): Implement JinaEmbeddingProvider - Proof Summary

## Task Description
Implement JinaEmbeddingProvider in `src/distillery/embedding/jina.py` using the Jina AI API via httpx.
- Default model: jina-embeddings-v3, default dimensions: 1024 (configurable via Matryoshka truncation)
- API key sourced from environment variable specified in config (embedding.api_key_env)
- Use task type 'retrieval.passage' for storage and 'retrieval.query' for search (accept task_type param)
- Rate limiting with exponential backoff on embed_batch (max 3 retries)
- Clear error messages on API errors

## Files Modified
- `src/distillery/embedding/jina.py` - Full JinaEmbeddingProvider implementation
- `src/distillery/embedding/__init__.py` - Already updated by worker-12 to export JinaEmbeddingProvider

## Proof Artifacts

### T15-01-structure-test.txt
**Status**: PASS
**Type**: Test - Protocol Interface & Structure Verification
Tests that:
- All EmbeddingProvider protocol methods are present: embed, embed_batch
- All protocol properties are present: dimensions, model_name
- Default model is jina-embeddings-v3
- Default dimensions is 1024
- embed and embed_batch accept task_type parameter
- ValueError raised when API key not available
- Empty batch handled (returns [])
- Custom model and dimensions configurable

### T15-02-retry-logic-test.txt
**Status**: PASS
**Type**: Test - Rate Limiting and Exponential Backoff Verification
Tests that:
- HTTP 429 triggers retry (up to 3 total attempts)
- Sleep called between retries (2 times for 3 attempts)
- Exponential backoff: 1.0s, 2.0s
- Non-retryable 4xx errors (e.g., 401) are NOT retried (single attempt)
- 5xx server errors trigger retry with backoff

### T15-03-api-request-test.txt
**Status**: PASS
**Type**: Test - API Request/Response Format Verification
Tests that:
- Payload contains correct model, task, dimensions, and input fields
- task_type is forwarded correctly to the Jina API 'task' field
- Default task type is 'retrieval.passage' (for storage embeddings)
- 'retrieval.query' used when explicitly passed
- Response parsing extracts embeddings in order
- Single embed() delegates to embed_batch() correctly
- ruff linting passes with no issues

## Implementation Details

### Key Design Decisions
1. **Matryoshka Truncation**: The `dimensions` parameter is passed to the Jina API as the `dimensions` field, enabling Matryoshka truncation for variable-size outputs.

2. **Task Types**: The Jina API requires a `task` field per embedding request:
   - `retrieval.passage` - used when storing/indexing documents (default)
   - `retrieval.query` - used when embedding search queries
   - Both `embed()` and `embed_batch()` accept `task_type` as a parameter.

3. **Retry Strategy**: Only HTTP 429 (rate limit) and 5xx server errors trigger retries. Non-retryable 4xx errors (401, 403, 400, etc.) immediately raise RuntimeError with the status code and response body.

4. **Error Messages**: All errors include the HTTP status code and response text for debugging.

5. **Context Manager Pattern**: `httpx.Client` is used as a context manager within each retry attempt to ensure connection cleanup.

### API Endpoint
`https://api.jina.ai/v1/embeddings` via POST with JSON body.

### Authentication
Bearer token in `Authorization` header, sourced from `os.environ[api_key_env]`.

## Blocks
This implementation unblocks:
- T03.4: Integrate embedding into DuckDBStore and add _meta table (#17)
- T03: Configurable Embedding Provider epic (#3)

## Verification
All proof artifacts confirm:
1. EmbeddingProvider protocol fully satisfied (all methods/properties present)
2. task_type parameter works correctly for both passage and query embeddings
3. Exponential backoff retry logic behaves correctly (3 attempts, 2 sleeps, doubling)
4. API request payload format is correct
5. Response parsing is robust
6. Code passes ruff linting with no issues
