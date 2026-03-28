# 09-spec-cli-eval-runner

## Introduction/Overview

Rewrite the Distillery skill evaluation framework to use the Claude Code CLI (`claude -p`) instead of the Anthropic Python SDK. This eliminates the need for a separate `ANTHROPIC_API_KEY` secret — the framework authenticates via `CLAUDE_CODE_OAUTH_TOKEN`, which is already configured in CI. Each eval scenario launches a Claude CLI subprocess that talks to a temporary MCP server instance backed by a pre-seeded DuckDB file.

## Goals

1. Remove the `anthropic` Python SDK dependency from the eval framework
2. Authenticate eval runs via `CLAUDE_CODE_OAUTH_TOKEN` (already available in CI)
3. Preserve the existing scenario format, scoring logic, and unit tests
4. Capture tool calls, final response, timing, and token usage from CLI stream-json output
5. Test the real MCP server subprocess path (not an in-process bridge) for higher-fidelity evals

## User Stories

- As a **maintainer**, I want the nightly eval to authenticate with the same `CLAUDE_CODE_OAUTH_TOKEN` used by other CI workflows so I don't need to provision a separate API key.
- As a **contributor**, I want to run `distillery eval` locally using my Claude Code login so I don't need a personal Anthropic API key.
- As a **maintainer**, I want eval scenarios to exercise the real MCP server subprocess so that protocol-level regressions are caught.

## Demoable Units of Work

### Unit 1: Hash-Based Mock Embedding Provider

**Purpose:** Add a functional mock embedding provider to the MCP server so that eval scenarios can perform semantic search against a temporary DuckDB store without requiring a real embedding API key.

**Functional Requirements:**

- The system shall add a `HashEmbeddingProvider` class to `src/distillery/mcp/_stub_embedding.py` that produces deterministic, L2-normalized vectors from a hash of the input text
- `HashEmbeddingProvider` shall implement the `EmbeddingProvider` protocol: `embed(text) -> list[float]`, `embed_batch(texts) -> list[list[float]]`, `dimensions -> int`, `model_name -> str`
- The vector dimensionality shall default to 4 (matching the existing test fixtures)
- The MCP server factory (`_create_embedding_provider`) shall register `HashEmbeddingProvider` under `provider_name == "mock"`
- The existing `StubEmbeddingProvider` (zero vectors, `provider_name == ""`) shall remain unchanged
- `distillery.yaml.example` shall document the `mock` provider option
- All new code shall pass `mypy --strict` and `ruff check`

**Proof Artifacts:**

- Test: `tests/test_embedding.py` updated — covers `HashEmbeddingProvider` embed, embed_batch, dimensions, model_name, and that different inputs produce different vectors
- Test: MCP server with `provider: "mock"` can store an entry and retrieve it via search with a non-zero similarity score
- File: `distillery.yaml.example` contains `mock` provider documentation

### Unit 2: CLI-Based Eval Runner

**Purpose:** Replace the Anthropic SDK-based `ClaudeEvalRunner` with one that shells out to the Claude Code CLI, parsing stream-json output for tool calls, responses, timing, and tokens.

**Functional Requirements:**

- The `ClaudeEvalRunner.__init__` shall no longer accept or require `api_key`; instead it shall accept `claude_cli: str = "claude"` for the CLI binary path
- The constructor shall validate that the CLI binary exists on `PATH` via `shutil.which`; raise `FileNotFoundError` if not found
- For each scenario, the runner shall:
  1. Create a `tempfile.TemporaryDirectory` with a DuckDB file and a `distillery.yaml` config (using `embedding.provider: "mock"`)
  2. Pre-seed the DuckDB file with `scenario.seed_entries` using a new `seed_file_store()` async function
  3. Write an MCP config JSON file: `{"mcpServers": {"distillery": {"command": "python", "args": ["-m", "distillery.mcp"], "env": {"DISTILLERY_CONFIG": "<path>"}}}}`
  4. Invoke `claude -p "<prompt>" --output-format stream-json --verbose --bare --model <model> --mcp-config <path> --dangerously-skip-permissions --system-prompt "<skill prompt>" --allowedTools "mcp__distillery__*"`
  5. Parse stdout stream-json events line-by-line
  6. After CLI exits, reopen the DuckDB file to count entries stored since seeding
  7. Score via existing `score_effectiveness()` and return `ScenarioResult`
- The `_parse_stream_events()` method shall extract:
  - `ToolCallRecord` instances from `tool_use` content blocks in assistant messages
  - Tool responses from subsequent `tool_result` content blocks
  - Final text response from the last assistant message's text blocks
  - `total_latency_ms` from the `result` event's `duration_ms` field
  - `input_tokens` and `output_tokens` from the `result` event's `usage` field
  - `api_call_count` from the `result` event's `num_turns` field
  - `tool_call_count` from counting all `tool_use` blocks
- Per-tool latency (`tool_latencies_ms`) shall be set to `[0.0]` per call (CLI does not expose per-tool timing)
- `PerformanceMetrics` shall add a `total_cost_usd: float = 0.0` field populated from the `result` event's `total_cost_usd` if present
- The `seed_file_store(db_path: str, seed_entries: list[SeedEntry], dimensions: int = 4) -> int` function shall be added to `src/distillery/eval/mcp_bridge.py`
- The existing `MCPBridge` class and `DISTILLERY_TOOL_SCHEMAS` shall remain unchanged (unit tests depend on them)
- The `anthropic` package shall be removed from `pyproject.toml` `[project.optional-dependencies] eval`
- All new code shall pass `mypy --strict` and `ruff check`

**Proof Artifacts:**

- Test: `tests/test_eval_unit.py` updated — `TestParseStreamEvents` class with mock stream-json payloads verifying tool call extraction, final response, and performance metrics
- Test: `seed_file_store()` creates a DuckDB file with seed entries and returns correct count
- Test: `ClaudeEvalRunner.__init__` raises `FileNotFoundError` when CLI binary not found
- Test: `ClaudeEvalRunner.__init__` no longer raises on missing `ANTHROPIC_API_KEY`
- CLI: existing eval scenarios pass when run locally with `claude` CLI installed

### Unit 3: CI Workflow Update

**Purpose:** Update the nightly eval workflow to use the Claude Code CLI with `CLAUDE_CODE_OAUTH_TOKEN` instead of the Anthropic SDK with `ANTHROPIC_API_KEY`.

**Functional Requirements:**

- The workflow shall add a Node.js setup step (`actions/setup-node@v4` with `node-version: "20"`)
- The workflow shall install Claude Code CLI: `npm install -g @anthropic-ai/claude-code`
- The workflow shall set `CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}` in the env
- The workflow shall remove the `ANTHROPIC_API_KEY` env var
- The pip install step shall use `pip install -e ".[dev]"` (no `eval` extra needed)
- The workflow shall set `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"` to suppress telemetry
- The workflow shall continue to run `pytest -m eval -v --tb=short`
- The workflow shall continue to upload eval results as artifacts

**Proof Artifacts:**

- File: `.github/workflows/eval-nightly.yml` contains Node.js setup, Claude CLI install, and `CLAUDE_CODE_OAUTH_TOKEN` env
- File: `.github/workflows/eval-nightly.yml` does not reference `ANTHROPIC_API_KEY`
- File: `pyproject.toml` `eval` extras do not include `anthropic`

## Non-Goals (Out of Scope)

- Per-tool latency measurement (CLI does not expose this; aggregate timing is sufficient)
- Running evals against the hosted MCP server (`able-red-cougar.fastmcp.app`) — evals use a temporary local MCP server per scenario for isolation
- Rewriting the scorer or scenario format — these remain unchanged
- Supporting both SDK and CLI runners simultaneously — the SDK runner is fully replaced
- Real embedding quality in evals — hash-based mock provider is sufficient for testing skill behavior

## Design Considerations

- Each scenario gets its own temp directory, DuckDB file, and MCP server subprocess — full isolation, no shared state
- The CLI subprocess spawns its own MCP server subprocess via the `--mcp-config` file — two levels of subprocess nesting
- Stream-json parsing must handle multi-turn conversations with interleaved text and tool_use blocks
- Temp directory cleanup is handled by `tempfile.TemporaryDirectory` context manager

## Repository Standards

- Conventional Commits: `feat(eval):`, `refactor(eval):`, `ci:`
- Scopes: `eval`, `mcp`, `ci`
- mypy strict for `src/`, relaxed for `tests/`
- ruff with existing rule set
- pytest-asyncio auto mode for async tests

## Technical Considerations

- `claude -p` with `--output-format stream-json` emits one JSON object per line to stdout
- The `result` event contains aggregate `usage`, `duration_ms`, `num_turns`, and `total_cost_usd`
- `--dangerously-skip-permissions` is required for non-interactive CLI use in CI
- `--bare` flag suppresses decorative CLI output
- `--mcp-config` accepts a path to a JSON file with MCP server definitions
- `--allowedTools "mcp__distillery__*"` restricts tool access to Distillery MCP tools only
- The `CLAUDE_CODE_OAUTH_TOKEN` env var is automatically picked up by the CLI — no explicit flag needed
- The `--system-prompt` flag injects the skill's SKILL.md content as the system prompt
- Model names in scenarios (e.g. `claude-haiku-4-5-20251001`) must be valid CLI `--model` values

## Security Considerations

- `CLAUDE_CODE_OAUTH_TOKEN` is organization-scoped and already used in the `claude.yml` workflow
- No new secrets required
- Temp DuckDB files are created in system temp directories with restricted permissions
- `--dangerously-skip-permissions` bypasses CLI permission prompts — acceptable in CI, should be documented for local use

## Success Metrics

- All existing eval unit tests continue to pass
- Nightly workflow runs successfully with `CLAUDE_CODE_OAUTH_TOKEN`
- `ANTHROPIC_API_KEY` is no longer required anywhere in the project
- Eval scenarios produce `ScenarioResult` with tool calls, performance metrics, and effectiveness scores
- Coverage threshold (80%) maintained

## Open Questions

No open questions at this time.
