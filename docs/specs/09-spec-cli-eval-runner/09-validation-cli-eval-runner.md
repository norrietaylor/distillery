# Validation Report: CLI Eval Runner

**Validated**: 2026-03-27T20:45:00Z
**Spec**: docs/specs/09-spec-cli-eval-runner/09-spec-cli-eval-runner.md
**Overall**: PASS
**Gates**: A[P] B[P] C[P] D[P] E[P] F[P]

## Executive Summary

- **Implementation Ready**: Yes - All 3 demoable units fully implemented with passing proofs; no issues found.
- **Requirements Verified**: 22/22 (100%)
- **Proof Artifacts Working**: 10/10 (100%)
- **Files Changed vs Expected**: 16 changed (including proofs), all in scope

## Coverage Matrix: Functional Requirements

### Unit 1: Hash-Based Mock Embedding Provider

| Requirement | Status | Evidence |
|-------------|--------|----------|
| R01.1: HashEmbeddingProvider in _stub_embedding.py | Verified | File exists; class present |
| R01.2: Implements EmbeddingProvider protocol (embed, embed_batch, dimensions, model_name) | Verified | T01-01-test.txt: test_protocol_compliance passes |
| R01.3: Vector dimensionality defaults to 4 | Verified | T01-01-test.txt: test_default_dimensions passes |
| R01.4: MCP server factory registers under provider_name=="mock" | Verified | server.py updated; integration confirmed |
| R01.5: Existing StubEmbeddingProvider unchanged | Verified | No breaking changes; existing tests pass |
| R01.6: distillery.yaml.example documents mock provider | Verified | T01-02-file.txt: 2 references found |
| R01.7: Passes mypy --strict and ruff check | Verified | Re-executed: mypy 0 errors, ruff all passed |

### Unit 2: CLI-Based Eval Runner

| Requirement | Status | Evidence |
|-------------|--------|----------|
| R02.1: ClaudeEvalRunner.__init__ accepts claude_cli instead of api_key | Verified | T02-01-test.txt: test_no_anthropic_api_key_required passes |
| R02.2: Constructor validates CLI binary via shutil.which; raises FileNotFoundError | Verified | T02-01-test.txt: test_raises_file_not_found_when_cli_missing passes |
| R02.3: Runner creates temp dir with DuckDB + config per scenario | Verified | Code review; runner.py updated |
| R02.4: seed_file_store() added to mcp_bridge.py | Verified | T02-01-test.txt: 3 TestSeedFileStore tests pass |
| R02.5: _parse_stream_events() extracts tool calls, response, timing, tokens | Verified | T02-01-test.txt: 8 TestParseStreamEvents tests pass |
| R02.6: PerformanceMetrics adds total_cost_usd field | Verified | T02-01-test.txt: TestPerformanceMetrics tests pass |
| R02.7: anthropic removed from pyproject.toml eval extras | Verified | T02-03-file.txt + re-verified: eval = [] |
| R02.8: MCPBridge and DISTILLERY_TOOL_SCHEMAS unchanged | Verified | T02-02-test.txt: all 81 existing tests still pass |
| R02.9: Passes mypy --strict and ruff check | Verified | Re-executed: mypy 0 errors, ruff all passed |

### Unit 3: CI Workflow Update

| Requirement | Status | Evidence |
|-------------|--------|----------|
| R03.1: Node.js setup step (actions/setup-node@v4, node 20) | Verified | T03-01-file.txt + re-verified in workflow |
| R03.2: Claude CLI install (npm install -g @anthropic-ai/claude-code) | Verified | T03-01-file.txt + re-verified in workflow |
| R03.3: CLAUDE_CODE_OAUTH_TOKEN set in env | Verified | T03-02-file.txt + re-verified in workflow |
| R03.4: ANTHROPIC_API_KEY removed | Verified | T03-03-file.txt + re-verified: grep exit code 1 |
| R03.5: pip install uses .[dev] (no eval extra) | Verified | T03-05-file.txt + re-verified in workflow |
| R03.6: CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC set | Verified | T03-02-file.txt + re-verified in workflow |

## Coverage Matrix: Repository Standards

| Standard | Status | Evidence |
|----------|--------|----------|
| mypy --strict on src/ | Verified | 0 issues on all changed src files |
| ruff check | Verified | All checks passed on changed files |
| pytest passes | Verified | 842 passed, 36 skipped |
| Coverage >= 80% | Verified | 80.97% total coverage |
| Conventional Commits | Verified | feat(mcp), feat(eval), ci(eval) scopes correct |
| pytest-asyncio auto mode | Verified | Async tests detected automatically |

## Coverage Matrix: Proof Artifacts

| Task | Artifact | Type | Status | Current Result |
|------|----------|------|--------|----------------|
| T01 | T01-01-test.txt | test | Verified | 9/9 HashEmbeddingProvider tests pass |
| T01 | T01-02-file.txt | file | Verified | distillery.yaml.example has mock docs |
| T02 | T02-01-test.txt | test | Verified | 15/15 new eval unit tests pass |
| T02 | T02-02-test.txt | test | Verified | 96/96 full eval unit suite passes |
| T02 | T02-03-file.txt | file | Verified | eval extras = [] in pyproject.toml |
| T03 | T03-01-file.txt | file | Verified | Node.js + CLI install in workflow |
| T03 | T03-02-file.txt | file | Verified | OAuth token + telemetry flag present |
| T03 | T03-03-file.txt | file | Verified | ANTHROPIC_API_KEY absent from workflow |
| T03 | T03-04-file.txt | file | Verified | eval extras clean in pyproject.toml |
| T03 | T03-05-file.txt | file | Verified | pip install uses [dev] only |

## Validation Issues

No issues found.

## Evidence Appendix

### Git Commits

| Commit | Message | Key Files |
|--------|---------|-----------|
| 8b82ec5 | feat(mcp): add HashEmbeddingProvider for mock embedding in eval and dev (T01) | _stub_embedding.py, server.py, config.py, test_embedding.py, distillery.yaml.example |
| 1a07a66 | feat(eval): rewrite ClaudeEvalRunner to use CLI instead of anthropic SDK (T02) | runner.py, mcp_bridge.py, models.py, __init__.py, pyproject.toml, test_eval_unit.py, test_eval_claude.py |
| f19e4a7 | ci(eval): update nightly workflow to use Claude Code CLI with OAuth token | eval-nightly.yml, uv.lock |

### Re-Executed Proofs

- **T01 tests**: `uv run pytest tests/test_embedding.py -k HashEmbedding -v` -- 9 passed in 0.05s
- **T02 tests**: `uv run pytest tests/test_eval_unit.py -v` -- 96 passed in 0.83s
- **Full suite**: `uv run pytest --cov=src/distillery --cov-fail-under=80 -q` -- 842 passed, 36 skipped, 80.97% coverage
- **mypy --strict**: 4 source files, 0 issues
- **ruff check**: 7 source files, all passed
- **T03 file checks**: All workflow assertions re-verified against .github/workflows/eval-nightly.yml

### File Scope Check

All 16 changed files are within the declared scope of the spec (eval, mcp, config, CI, tests, docs). No out-of-scope changes detected.

| File | In Scope |
|------|----------|
| .github/workflows/eval-nightly.yml | Yes (Unit 3) |
| distillery.yaml.example | Yes (Unit 1) |
| pyproject.toml | Yes (Unit 2) |
| src/distillery/config.py | Yes (Unit 1) |
| src/distillery/eval/__init__.py | Yes (Unit 2) |
| src/distillery/eval/mcp_bridge.py | Yes (Unit 2) |
| src/distillery/eval/models.py | Yes (Unit 2) |
| src/distillery/eval/runner.py | Yes (Unit 2) |
| src/distillery/mcp/_stub_embedding.py | Yes (Unit 1) |
| src/distillery/mcp/server.py | Yes (Unit 1) |
| tests/test_embedding.py | Yes (Unit 1) |
| tests/test_eval_claude.py | Yes (Unit 2) |
| tests/test_eval_unit.py | Yes (Unit 2) |
| uv.lock | Yes (dependency change) |

### Credential Scan

Scanned all 15 proof files in `docs/specs/09-spec-cli-eval-runner/01-proofs/`. Found references to `ANTHROPIC_API_KEY` only in the context of verifying its removal. No actual secrets, tokens, or credential values present.

---
Validation performed by: Claude Opus 4.6 (1M context)
