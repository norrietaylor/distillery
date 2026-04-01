# 02-spec-eval-supplement

## Introduction/Overview

Supplement the existing Distillery eval framework with four improvements: a fast promptfoo-based PR CI gate, RAGAS retrieval quality metrics for `/recall` and `/pour`, adversarial and edge-case scenario coverage, and per-run cost tracking with regression detection. The existing 56-scenario custom framework remains the primary eval system; these additions fill specific gaps in pre-merge gating, retrieval quality measurement, failure-mode coverage, and cost observability.

## Goals

1. Catch skill regressions before merge via a sub-2-minute PR CI gate using promptfoo
2. Measure retrieval relevance (precision, recall, MRR) for search-dependent skills using RAGAS
3. Cover failure modes — malformed input, empty stores, boundary conditions, concurrency, dependency failures — with ≥10 adversarial scenarios
4. Track token usage and estimated cost per eval run with baseline comparison and per-skill breakdown

## User Stories

- As a **contributor**, I want a fast eval check on my PR so that I know if my changes break skill behavior before merging.
- As a **maintainer**, I want retrieval quality metrics so that I can detect degradation in search relevance beyond "correct tools were called."
- As a **developer**, I want adversarial test scenarios so that edge cases and failure modes are covered by the eval suite.
- As an **operator**, I want cost tracking per eval run so that I can detect prompt bloat or unnecessary tool calls driving up spend.

## Demoable Units of Work

### Unit 1: promptfoo PR CI Gate

**Purpose:** Add a fast, pre-merge eval gate that validates critical skill paths on every PR using promptfoo's tool-call assertion model.

**Functional Requirements:**
- The system shall include a `promptfooconfig.yaml` at the repository root that defines 5–10 smoke-test scenarios covering the most critical skill paths (at minimum: `/distill` store, `/recall` search, `/bookmark` store, `/pour` synthesis, `/watch` list).
- Each promptfoo scenario shall assert: (a) expected MCP tool calls are made, (b) tool arguments contain required fields, and (c) response content includes expected substrings.
- The system shall include a new GitHub Actions workflow `eval-pr.yml` triggered on `pull_request` events targeting `main`, separate from the existing `eval-nightly.yml`.
- The `eval-pr.yml` workflow shall install promptfoo via npm (`npx promptfoo@latest`), run the eval suite, and fail the workflow if any assertion fails.
- The full PR eval run shall complete in under 2 minutes (wall clock) on GitHub Actions ubuntu-latest runners.
- The system shall add promptfoo to `.gitignore` for any local output directories it creates (e.g., `.promptfoo/`).

**Proof Artifacts:**
- File: `promptfooconfig.yaml` exists at repository root with ≥5 test scenarios
- File: `.github/workflows/eval-pr.yml` exists with `on: pull_request` trigger
- CLI: `npx promptfoo@latest eval --config promptfooconfig.yaml` completes with exit code 0 in <2 minutes
- Test: Opening a PR triggers the `eval-pr.yml` workflow and it passes

### Unit 2: RAGAS Retrieval Quality Metrics

**Purpose:** Add retrieval quality measurement (precision, recall, MRR, faithfulness) for `/recall` and `/pour` scenarios, surfacing relevance scores alongside existing tool-call assertions.

**Functional Requirements:**
- The system shall add a `ragas` optional dependency group in `pyproject.toml` (e.g., `pip install -e ".[ragas]"`), including the `ragas` package and its required dependencies.
- The system shall create a golden dataset of retrieval scenarios in `tests/eval/golden/retrieval.yaml` with: query, seed entries, and per-entry relevance judgments (binary: relevant/not-relevant).
- The system shall implement a `retrieval_scorer.py` module in `src/distillery/eval/` that accepts `ToolCallRecord` search results and golden relevance labels, and computes: precision@k, recall@k, MRR (mean reciprocal rank), and optionally faithfulness (if LLM judge is available).
- The `ScenarioResult` model shall be extended with an optional `retrieval_metrics` field (dataclass with precision, recall, mrr, faithfulness fields — all `float | None`).
- The `distillery eval` CLI shall display retrieval metrics alongside existing pass/fail output when metrics are available.
- The system shall set minimum thresholds: MRR ≥ 0.7, precision@5 ≥ 0.6. Scenarios falling below thresholds shall be marked as failed with the specific metric in `failure_reasons`.
- The nightly eval workflow shall install the `[ragas]` extras and include retrieval quality scenarios in its run.

**Proof Artifacts:**
- File: `tests/eval/golden/retrieval.yaml` contains ≥5 retrieval scenarios with relevance judgments
- File: `src/distillery/eval/retrieval_scorer.py` exists with `score_retrieval()` function
- CLI: `distillery eval --skill recall` shows retrieval metrics (MRR, precision) in output
- Test: `pytest -m unit tests/eval/test_retrieval_scorer.py` passes with deterministic inputs

### Unit 3: Adversarial and Edge-Case Scenarios

**Purpose:** Add ≥10 eval scenarios covering failure modes, boundary conditions, and edge cases that the current happy-path suite does not exercise.

**Functional Requirements:**
- The system shall add a new scenario file `tests/eval/scenarios/adversarial.yaml` containing ≥10 scenarios across the following categories:
  - **Malformed input** (≥2): empty string prompts, extremely long content (>10k chars), unicode edge cases (RTL text, zero-width chars, emoji sequences)
  - **Empty store** (≥2): `/recall` search against empty knowledge base, `/pour` synthesis with no matching entries — both shall produce graceful responses (no crashes, helpful messages)
  - **Boundary conditions** (≥2): similarity scores at exact dedup thresholds (0.60 link, 0.80 merge, 0.95 skip) — verify correct classification behavior
  - **Concurrent operations** (≥2): rapid sequential store+search calls, multiple stores in single prompt — verify no data loss or corruption
  - **Missing dependencies** (≥2): MCP tool returning error responses, simulated timeout/failure — verify skills degrade gracefully with user-facing error messages
- Each adversarial scenario shall use `response_must_not_contain` to assert absence of stack traces, raw exceptions, or "internal error" strings in responses.
- Each adversarial scenario shall use `response_must_contain` to assert presence of user-friendly messaging.
- Adversarial scenarios shall be tagged in their YAML with a `category` metadata field for filtering.
- The existing nightly CI workflow shall automatically pick up the new scenario file (no workflow changes needed — it loads all YAML from the scenarios directory).

**Proof Artifacts:**
- File: `tests/eval/scenarios/adversarial.yaml` contains ≥10 scenarios
- CLI: `distillery eval --skill adversarial` or `distillery eval` (all) includes adversarial scenarios and they pass
- Test: Adversarial scenarios run in nightly CI without requiring workflow changes

### Unit 4: Cost Tracking and Trend Detection

**Purpose:** Record per-run and per-skill token usage and estimated cost in baseline JSON, with a CLI flag for cost regression detection.

**Functional Requirements:**
- The existing `--save-baseline` JSON output shall be extended to include per-scenario fields: `input_tokens`, `output_tokens`, `total_tokens`, `total_cost_usd`.
- The baseline JSON shall include a top-level `cost_summary` object with: `total_cost_usd`, `total_tokens`, and a `per_skill` breakdown (dict of skill name → `{cost_usd, tokens, scenario_count}`).
- The `distillery eval` CLI shall accept a `--compare-cost` flag that, when used with `--baseline`, compares the current run's cost against the baseline and reports: (a) total cost delta (absolute and percentage), (b) per-skill cost deltas, (c) any skill with >20% cost increase flagged as a warning.
- Cost comparison output shall be appended after the existing pass/fail summary in text format, or included as a `cost_comparison` key in JSON format.
- The `PerformanceMetrics` dataclass already tracks `total_cost_usd` — no model changes needed for per-scenario cost. The baseline serialization and comparison are the new work.
- The nightly CI workflow shall use `--save-baseline` to persist cost data in the uploaded artifact for historical tracking.

**Proof Artifacts:**
- CLI: `distillery eval --save-baseline baseline.json` produces JSON with `cost_summary` field
- CLI: `distillery eval --baseline baseline.json --compare-cost` shows cost delta and per-skill breakdown
- File: `baseline.json` contains `cost_summary.per_skill` with token and cost data per skill
- Test: `pytest -m unit tests/eval/test_cost_tracking.py` passes with mock data

## Non-Goals (Out of Scope)

- Replacing the existing custom eval framework with promptfoo or any other tool
- Real-time cost alerting or budget enforcement during eval runs
- Automated prompt optimization based on cost data
- RAGAS metrics for non-retrieval skills (e.g., `/distill`, `/watch`)
- Visual dashboards or UI for eval results (CI artifacts and CLI output are sufficient)
- Integration with external observability platforms (Grafana, Datadog)
- Eval scenarios for authentication or OAuth flows

## Design Considerations

No specific design requirements identified. CLI output follows existing patterns (text summary with `[PASS]`/`[FAIL]` prefixes, JSON structured output).

## Repository Standards

- **Python 3.11+**, **mypy --strict** on `src/`, **ruff** formatting
- **Conventional Commits**: `feat(eval):`, `test(eval):`, `chore(eval):`
- **pytest-asyncio** auto mode, markers: `@pytest.mark.unit`, `@pytest.mark.eval`
- **Eval scenarios**: YAML files in `tests/eval/scenarios/`, loaded by `load_scenarios_from_dir()`
- **CI**: GitHub Actions, ubuntu-latest, Python 3.12, Node.js 20

## Technical Considerations

- **promptfoo**: Installed via `npx promptfoo@latest` in CI — no Python dependency needed. Requires MCP server access; may need a lightweight MCP config for promptfoo's provider.
- **RAGAS**: Python package with heavy dependencies (numpy, etc.). Isolated in optional `[ragas]` dep group to avoid bloating base install. Retrieval scorer should be importable without RAGAS installed (graceful import with fallback).
- **Adversarial scenarios**: Use the existing `EvalScenario` model. The `category` metadata field is informational only — no code changes to the scenario loader.
- **Cost tracking**: Extends existing baseline JSON format. Must maintain backward compatibility — old baselines without `cost_summary` should not break `--compare-cost` (treat missing data as "no baseline available").
- **Backward compatibility**: All changes are additive. Existing scenarios, CLI flags, and CI workflows remain unchanged.

## Security Considerations

- promptfoo CI runs require `CLAUDE_CODE_OAUTH_TOKEN` secret — already configured for nightly eval
- RAGAS may require an API key if using LLM-judge faithfulness metric — document as optional, skip faithfulness scoring if no key available
- Adversarial scenarios with extremely long content should not cause OOM in CI runners — set reasonable upper bounds (10k chars, not 1M)
- Cost data in baseline JSON may reveal API pricing details — acceptable for private repo, note in docs if repo goes public

## Success Metrics

| Metric | Target |
|--------|--------|
| PR CI eval wall-clock time | < 2 minutes |
| PR CI eval scenario count | 5–10 smoke tests |
| Retrieval MRR on `/recall` scenarios | ≥ 0.7 |
| Retrieval precision@5 on `/recall` scenarios | ≥ 0.6 |
| Adversarial scenario count | ≥ 10 |
| Adversarial scenario pass rate | 100% (graceful handling) |
| Cost tracking coverage | All scenarios in baseline JSON |
| Cost regression detection threshold | >20% per-skill increase flagged |

## Open Questions

1. **promptfoo MCP provider**: Does promptfoo natively support MCP tool-call providers, or will a custom provider wrapper be needed to bridge promptfoo → Distillery MCP? This affects Unit 1 implementation complexity.
2. **RAGAS faithfulness**: Should faithfulness scoring (LLM-judge) be included in the initial implementation, or deferred until a dedicated API key management story is in place?
3. **Adversarial concurrency**: The current eval runner (`ClaudeEvalRunner`) runs scenarios sequentially. True concurrency testing may require a new runner mode or manual async orchestration within a single scenario. Clarify: is "concurrent" in the issue about rapid sequential calls within one prompt, or actual parallel execution?
