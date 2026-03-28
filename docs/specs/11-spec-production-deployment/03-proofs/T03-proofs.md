# T03 Proof Summary: Docker Container & Lambda Handler

**Task**: T03: Docker Container & Lambda Handler
**Status**: COMPLETED
**Date**: 2026-03-28

## Deliverables Implemented

| Deliverable | Status | Notes |
|---|---|---|
| `Dockerfile` | DONE | Based on `public.ecr.aws/lambda/python:3.12`, installs distillery, sets Lambda CMD |
| `.dockerignore` | DONE | Excludes .env, credentials, tests, .git, .worktrees, __pycache__ |
| `src/distillery/mcp/lambda_handler.py` | DONE | Lambda handler with lazy Mangum init wrapping FastMCP ASGI app |
| `distillery.lambda.yaml` | DONE | S3-compatible DuckDB storage, GitHub OAuth env var references |
| `mangum>=0.17.0` in `pyproject.toml` | DONE | Added to main dependencies |
| `tests/test_lambda_handler.py` | DONE | 6 unit tests, all pass |

## Proof Artifacts

| File | Type | Status |
|---|---|---|
| T03-01-test.txt | pytest test run | PASS — 6/6 tests passed |
| T03-02-file.txt | file existence check | PASS — all required files exist |
| T03-03-test.txt | handler function verification | PASS — handler() found and tested |
| T03-04-docker.txt | docker build | BLOCKED — Docker not available in env |

## Key Design Decisions

1. **Lazy initialisation**: `_build_mangum_handler()` is called on first `handler()` invocation
   rather than at module import time. This allows unit tests to patch the builder without
   requiring real DB/OAuth credentials, and is also better Lambda practice (avoids import
   errors masking init errors).

2. **ASGI via `server.http_app()`**: FastMCP's `http_app(path="/mcp", stateless_http=True)`
   returns a Starlette ASGI app that Mangum can wrap for Lambda event translation.

3. **Auth provider from config**: The handler reads `config.server.auth.provider` to decide
   whether to configure GitHub OAuth, mirroring `__main__.py` HTTP path.

4. **Config file**: `distillery.lambda.yaml` is copied into `/var/task/distillery.yaml` inside
   the container. All secrets are env var references — no credentials embedded.

## Test Coverage

```
tests/test_lambda_handler.py::TestLambdaHandlerModule::test_handler_is_callable PASSED
tests/test_lambda_handler.py::TestLambdaHandlerModule::test_handler_returns_response PASSED
tests/test_lambda_handler.py::TestLambdaHandlerModule::test_handler_delegates_to_mangum PASSED
tests/test_lambda_handler.py::TestLambdaHandlerModule::test_handler_returns_200_for_health PASSED
tests/test_lambda_handler.py::TestLambdaHandlerModule::test_handler_response_body_is_valid_json_with_status PASSED
tests/test_lambda_handler.py::TestLambdaHandlerModule::test_handler_caches_mangum_instance PASSED
```
