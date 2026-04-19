# Changelog

All notable changes to this project will be documented in this file.
## [0.4.0] - 2026-04-19

### Bug Fixes

- address CodeRabbit review for PR #365 *(store,mcp)*
- roll back aborted transactions; surface query failures in status *(store)*
- address additional CodeRabbit findings *(pr250)*
- consolidate feeds.py error codes onto ToolErrorCode enum *(mcp)*
- address CodeRabbit review comments *(pr250)*
- include exc.endpoint in provider warning logs; pin non-finite Retry-After *(mcp,tests)*
- propagate provider errors in store dedup precheck; merge duplicate 429 tests *(mcp,tests)*
- route OpenAI.embed() through embed_batch() for structured errors *(embedding)*
- address second CodeRabbit round — finite Retry-After, label 5xx retries, propagate provider errors in store_batch *(embedding)*
- address CodeRabbit review — HTTP-date Retry-After, extra sleep, stale retry_after, leaked exc text *(embedding)*
- flush WAL after writes and preserve it on recovery *(store)*
- use distillery_list with stale_days (distillery_stale removed) *(scripts)*
- replace brittle /health probe in session-start-briefing hook *(scripts)*
- handle UNC hosts and Windows drive letters in file:// URIs *(store)*
- tighten WAL recovery — signature match, path resolution, no unlink fallback *(store)*
- eliminate FTS WAL replay failure on cold start *(store)*
- suggest canonical entry_type on INVALID_PARAMS *(classification)*
- correct staging-deploy PR comment URL rendering and /mcp method note *(ci)*
- avoid pytz dependency in sync_jobs persistence *(feeds)*
- remove unused import and narrow Optional in lambda capture *(ci)*
- reserve dedup_action=merged for true fold cases (#332) *(mcp)*
- populate liveness fields across poll and sync paths (#334) *(feeds,store)*
- make resolve_review idempotent for no-op transitions (#333) *(mcp)*
- alias source=<url> to feed_url filter in distillery_list (#335) *(mcp)*
- address CodeRabbit full-review round 2 feedback *(mcp,feeds,config,test,docs)*
- address CodeRabbit full-review feedback *(mcp,feeds,test,docs)*
- exclude feed entries from radar interest profile *(skills)*
- restore ResourceContent.content accessor in test_mcp_server *(test)*
- address CodeRabbit iter8 feedback on api hardening *(mcp,store,test,docs)*
- add type annotations and fix stale comment in heuristic and http transport tests *(test)*
- scope storage_bytes to filtered entries when filters are active *(store)*
- address CodeRabbit iter7 feedback on api hardening *(mcp,store,cli,docs)*
- address CodeRabbit iter6 feedback on api hardening *(mcp,scripts,store)*
- parse distillery_list response shape in session-start briefing *(scripts)*
- harden inputs against negative retention and bad YAML *(store,feeds,config)*
- tighten feed source validation and expose sync_status lookup params *(mcp)*
- address fourth CodeRabbit pass on api hardening PR *(mcp)*
- address third CodeRabbit pass on api hardening PR *(mcp)*
- address second CodeRabbit pass on api hardening PR *(mcp)*
- address CodeRabbit review feedback on api hardening PR *(mcp)*
- align tests and helpers after main merge *(mcp)*
- validate rate-limit numeric fields are > 0 *(config)*
- address CodeRabbit review — strict bool validation, loopback spoof guard, mypy fixes *(mcp)*
- use _parse_strict_int for HTTP rate-limit numeric fields and fix test docstring *(config)*
- strict bool parsing for webhooks.enabled too (#236) *(config)*
- strict bool parsing and spoof-resistant loopback exemption (#236) *(mcp)*
- exempt loopback clients from rate limiting by default (#236) *(mcp)*
- restore user_config interpolation for MCP URL override *(plugin)*
- use env var for MCP URL override instead of unsupported user_config interpolation (#235) *(plugin)*
- update version to 0.3.3 and fix plugin manifest tests *(plugin)*
- make MCP server URL configurable for self-hosters (#235) *(plugin)*
- explicit bool parse, HEAD→GET on 405/501, generic probe errors (#308) *(feeds)*
- surface probe_error on force=T and centralise probe stub (#308) *(feeds)*
- validate URL syntax and probe reachability in distillery_watch (#308) *(feeds)*
- persist user_login metadata and clarify tag-sanitiser docstring (#312) *(feeds)*
- add merged_at metadata and backfill project on batch update (#312) *(feeds)*
- auto-populate project/tags/author/metadata on gh-sync (#312) *(feeds)*
- exclude archived entries from list/search by default (#317) *(mcp)*
- validate item_count and relocate sanitiser tests (#310) *(feeds)*
- attach UTC tzinfo and sanitise fake store error (#310) *(feeds)*
- surface poll liveness on distillery_watch list (#310) *(feeds)*
- route stale briefing section to distillery_list (#307) *(skills)*
- remove stale delegation keys on non-delegated actions *(mcp)*
- clear stale on_behalf_of keys and add transition regression test *(mcp)*
- honor reviewer param in resolve_review with actor tracking (#315) *(mcp)*
- address CodeRabbit review — title constant, migration recovery *(mcp)*
- add review mode to output_mode schema, fix docstring, tighten summary keyset test *(mcp)*
- switch distillery_list default output_mode to summary (#311) *(mcp)*
- guard reclassify status flip to only act on pending_review entries *(mcp)*
- flip status to active on resolve_review reclassify (#316) *(mcp)*
- add feed_url filter to distillery_list for feed ingest alignment (#309) *(mcp)*
- add server-side bare --batch guard and regression test *(classify)*
- apply real author on updates and harden null handling *(feeds)*
- normalize MCP URL, pass transport headers, pick deepest project *(cli)*
- shlex.split for env command, JSON-safe build_briefing, safe limit parsing *(cli)*
- probe each transport candidate, fix stdio stdin/communicate, dual-probe health check, clarify README *(cli)*
- address CodeRabbit review on dynamic transport resolution *(cli)*
- address CodeRabbit review — API hardening consolidation fixes *(mcp)*
- add loopback exemption to RateLimitMiddleware with spoof-safe peer check *(mcp)*
- address all CodeRabbit review comments — spec/skill/source/test fixes *(mcp)*
- surface persisted flag and auto-skip near-duplicate stores (#314) *(mcp)*
- parallelise poll sources and skip redundant semantic dedup (#221) *(feeds)*
- add defensive CHECKPOINT after schema init and clean stale atexit references (#230) *(store)*
- handle BrokenPipeError during stream flush *(cli)*
- flush stdout before sys.exit in retag and other subcommands (#169) *(cli)*
- pre-register Claude Code OAuth client to bypass CIMD fetch (#250) *(auth)*
- suppress CPython CVEs and add negative URL regression tests *(security)*
- handle api.github.com URLs and add trailing newline *(feeds)*
- apply CodeRabbit auto-fixes
- resolve 6 CodeQL code scanning alerts *(security)*
- prevent ghost sync jobs and sanitize startup error *(feeds)*
- clarify concurrency docstring and clean up dead test mock *(feeds)*
- resolve merge conflicts with staging/api-hardening
- sanitize purge error and archive all non-archived entries *(feeds)*
- apply ruff formatting and resolve mypy no-redef error *(mcp)*
- add /gh-sync to forked context inventory and sandbox rules *(skills)*
- enforce allowed-tools sandbox in forked skill contexts *(skills)*
- remove stale distillery_tag_tree permission from settings.local.json *(config)*
- add read-only mode to distillery_configure and fix /tune skill *(mcp)*
- use SyncResult attrs, sanitize errors, add on_page callback, batch store writes *(feeds)*
- resolve merge conflicts with staging/api-hardening
- ensure truncate_content respects max_chars contract *(feeds)*
- apply ruff format to 14 files *(lint)*
- handle Jina 8194-token embedding limit with truncation *(feeds)*
- address CodeRabbit review — import aliases, kwarg dedup, error sanitization *(mcp)*
- resolve merge conflicts with staging/api-hardening
- normalise naive datetimes to UTC in export for timezone portability *(cli)*
- align setup overview with daily stale-entry check tier *(skills)*
- align setup scheduling guidance and move deprecation warnings post-auth *(skills)*
- format code and fix expires_at timezone roundtrip in export/import *(cli)*
- align daily task label and tighten CronList poll detection *(skills)*
- remove cron creation from /watch, defer to /setup *(skills)*
- use MCP tool calls in CronCreate prompts for local transport (#269) *(skills)*
- suppress unfixed CPython 3.13.13 CVEs in Grype config *(security)*
- add trailing newline to duckdb.py *(store)*
- apply CodeRabbit auto-fixes
- use CASCADE when dropping FTS schema (#266) *(store)*
- fix broken test imports, store.add→store, FeedPoller patch, metadata fields *(test)*
- update imports after removing analytics tool re-registrations *(test)*
- add missing trailing newlines across 12 files *(lint)*
- update tool count and expected set to 18 tools *(test)*
- apply CodeRabbit auto-fixes
- address remaining CodeRabbit review comments on PR #250 *(test)*
- use CASCADE when dropping FTS schema (#266) *(store)*
- add method to ASGI scope in middleware tests *(test)*
- resolve ruff errors in bulk ingest code *(lint)*
- address CodeRabbit review on PR #264 *(mcp)*
- resolve 5 open findings from security review (#112) *(security)*
- remove unused variables flagged by ruff lint *(test)*
- resolve 7 CodeRabbit issues (#255, #256, #258, #259, #260, #261, #262)
- update error code count test and ruff lint fix *(mcp)*
- address CodeRabbit review comments on PR #250 *(mcp)*
- Phase A foundation fixes (#232, #238, #241, #240) *(mcp)*
- address remaining CodeRabbit review comments
- remove proof artifacts, fix CodeRabbit issues, fix CI mypy
- address validation follow-up issues *(mcp)*
- resolve duplicate Authorization header in changelog workflow *(ci)*
- stop leaking conflict-detector system prompt in store response (#200) *(mcp)*
- use correct hook format with matcher and nested hooks array *(plugin)*

### CI/CD

- trigger PR checks
- suppress upstream CVEs in Docker base image (#271) *(scan)*
- stop tearing down on PR close *(staging)*
- accept /deploy_staging underscore alias *(staging)*
- print staging endpoint URL in PR comments *(staging)*
- use startsWith for command match to stop self-triggering *(staging)*
- dispatch distill_ops via gh workflow run (actions:write) *(staging)*
- scope buildx GHA cache per PR *(staging)*
- build from remote Git context instead of actions/checkout *(staging)*
- split resolve/build jobs, gate build on staging-deploy env *(staging)*
- deploy on PR comment, teardown on close *(staging)*

### Documentation

- annotate second-brain post as updated for 0.4.0 *(blog)*
- reconcile docs site with shipped staging/api-hardening surface
- correct tool count to 16 in remove-absorbed-tools feature file *(specs)*
- align api-consolidation feature files with shipped behavior *(specs)*
- reconcile setup rules, investigate phase 3, and /setup tool list *(skills)*
- correct tool count in mcp server/http docstrings (#313) *(test)*
- sync Mode A entry_type list and add bare --batch regression test *(skills)*
- restructure roadmap with priority tiers
- mention /teardown_staging alias in teardown-trigger sentence *(staging)*
- comprehensive v0.3 documentation update

### Features

- raise budget default to unlimited; surface provider 429 *(embedding)*
- omit conflict_prompt from distillery_store by default *(mcp)*
- gh-sync returns async via server-side background job *(feeds)*
- add distillery_status tool for in-protocol health probe (#313) *(mcp)*
- add --batch mode with flexible filters (#301) *(classify)*
- use real author from source payloads (#302) *(sync)*
- dynamic MCP transport resolution for SessionStart hook (#303) *(cli)*
- add --purge option to /watch remove for archiving entries *(feeds)*
- support group_by='tags' in distillery_list *(store)*
- async sync pipeline with batched storage for watch and gh-sync *(feeds)*
- replace webhook scheduling with Claude Code routines *(skills)*
- add sync_history option to distillery_watch add action *(feeds)*
- add distillery_store_batch tool for bulk entry ingestion *(mcp)*
- add store_batch to protocol and DuckDB backend *(store)*
- phase 5 — validate relation types on add action *(mcp)*
- phase 4 — fix validate_required bug, add enum/int helpers *(mcp)*
- phase 3 — standardize error codes across all handlers *(mcp)*
- phase 2 — register 5 missing tool handlers as MCP tools *(mcp)*
- phase 1 — rewrite all 12 tool docstrings with structured template *(mcp)*
- update all 14 SKILL.md files for 12-tool API surface (T04.2) *(skills)*
- add maintenance classify command for batch entry classification *(cli)*
- rewire /api/maintenance to poll → rescore → classify-batch pipeline *(mcp)*
- update test assertions for 12-tool surface and add entry-type schema resource tests *(mcp)*
- add POST /hooks/classify-batch webhook endpoint *(mcp)*
- wire stale_days, group_by, output params into distillery_list tool *(mcp)*
- add /hooks/poll and /hooks/rescore webhook endpoints with query params *(mcp)*
- add heuristic classifier with centroid computation *(classification)*
- extend list_entries with stale_days, group_by, output params *(store)*

### Miscellaneous

- ignore .claude/worktrees/ in git
- bump python-multipart from 0.0.22 to 0.0.26 *(deps)*
- bump authlib from 1.6.9 to 1.6.11 *(deps)*
- bump langchain-text-splitters from 1.1.1 to 1.1.2 *(deps)*
- bump langchain-openai from 1.1.12 to 1.1.14 *(deps)*
- bump authlib from 1.6.9 to 1.6.11 *(deps)*
- bump langchain-text-splitters from 1.1.1 to 1.1.2 *(deps)*
- bump langchain-openai from 1.1.12 to 1.1.14 *(deps)*
- merge main into staging/api-hardening
- bump langsmith from 0.7.24 to 0.7.31 *(deps)*
- bump pytest from 9.0.2 to 9.0.3 *(deps)*
- bump plugin.json version to 0.4.0
- bump version to 0.4.0
- suppress CVE-2026-31790 in Grype scan (openssl 3.6.1)

### Refactoring

- revert Phase 2 tool re-registrations, restore 13-tool surface *(mcp)*

### Testing

- exercise http:// scheme in source-alias regression test *(mcp)*
- drop double-marked helper tests; assert on shared suffix *(store,truncation)*
- verify userConfig default matches Fly.io URL *(plugin)*
- align async-sync tests with SyncResult contract and sanitized errors *(feeds)*
- add tests for store_batch and bulk ingest pipeline *(store)*
- add comprehensive test suite for list extensions (T01.3) *(mcp)*
- migrate tests for removed tools and add negative test suite (T02.3) *(mcp)*

### Release

- v0.4.0 — Full-Proof

## [0.3.2] - 2026-04-09

### Bug Fixes

- use peter-evans/create-pull-request for changelog PR *(ci)*

### Miscellaneous

- bump version to 0.3.2

## [0.3.1] - 2026-04-09

### Bug Fixes

- changelog workflow creates PR instead of pushing to main *(ci)*
- update server.json to MCP Registry schema 2025-12-11 *(ci)*

### Documentation

- add server.json to release version bump checklist

### Miscellaneous

- bump version to 0.3.1

## [0.3.0] - 2026-04-09

### Bug Fixes

- address CodeRabbit review concerns on /setup skill *(hooks)*
- remove UserPromptSubmit from plugin.json, add scope-aware /setup hook config *(hooks)*
- make graders tolerant of Agent/Skill delegation *(eval)*
- address PR review comments *(hooks)*
- add missing trailing newlines to pass ruff W292
- apply CodeRabbit auto-fixes
- apply CodeRabbit auto-fixes
- address CodeRabbit review findings on session-hooks PR *(mcp)*
- update invalid source test to expect rejection instead of fallback *(test)*
- expose session_id and source params on MCP tool signatures *(mcp)*
- wrap correction write set in a single transaction *(store)*
- add reserved tag-prefix guard to _handle_correct *(store)*
- add budget/size gates and fix tags validation order in _handle_correct *(store)*
- close DuckDB on lifespan shutdown to checkpoint WAL *(store)*
- reject date-only expires_at input *(mcp)*
- normalize expires_at to UTC before storing *(mcp)*
- use TIMESTAMP for expires_at, unify stale/expired entry shape *(store)*
- update migration assertions for schema version 9 *(tests)*
- merge main, resolve conflicts, address review findings *(store)*
- address additional review findings
- resolve remaining review comments on team-skills PR
- address review findings on plugin version pinning
- address code review findings
- update tool and skill assertions for team-skills feature *(test)*

### Documentation

- update README for /setup auto-config and nested hook format *(hooks)*
- add plugin manifest policy to RELEASING.md
- add release branch workflow to RELEASING.md
- document all files requiring version bump in RELEASING.md
- add corrections guidance to CONVENTIONS.md *(skills)*
- update /briefing registry entry to match rewritten skill *(skills)*
- capitalize GitHub in gh-sync trigger phrase
- add RELEASING.md with release process and tag format rules
- capitalize Claude Desktop in plugin install page
- update tool/skill counts and add pytest-httpx dependency
- add 12-spec-team-skills for /digest, /gh-sync, /investigate, /briefing *(spec)*

### Features

- inline UserPromptSubmit counter in plugin.json *(hooks)*
- add session_id as first-class Entry field *(store)*
- extend EntrySource with inference, documentation, external provenance values *(models)*
- add distillery_correct tool with entry_relations backend *(store)*
- add hook dispatcher with UserPromptSubmit memory nudge *(hooks)*
- add team mode to /briefing skill *(skills)*
- rewrite /briefing as solo-first knowledge dashboard *(skills)*
- add SessionStart briefing hook script *(hooks)*
- add expires_at column for time-limited entries *(store)*
- add orthogonal verification field for entry quality tracking *(store)*
- add /gh-sync skill for GitHub issue/PR knowledge tracking *(skills)*
- add GitHubSyncAdapter for structured issue/PR sync *(feeds)*
- add /investigate deep context builder skill *(skills)*
- add distillery_relations tool for managing entry relations *(mcp)*
- add add_relation, get_related, remove_relation to protocol and DuckDBStore *(store)*
- add /briefing team knowledge dashboard skill *(skills)*
- add migration 8 for entry_relations table with backfill *(store)*
- add /digest skill for team activity summaries *(skills)*

### Miscellaneous

- bump plugin and lockfile to 0.3.0
- bump version to 0.3.0
- bump langchain-core from 1.2.24 to 1.2.28 *(deps)*
- remove proof artifact files from branch
- address review findings on corrections chain PR
- add specs, remove proof artifacts
- bump cryptography from 46.0.6 to 46.0.7 *(deps)*
- address remaining review nitpicks
- trigger CI with updated secrets
- pin plugin version to release tag and add server version compatibility
- remove proof artifacts from tracked files

### Refactoring

- remove unnecessary flock from prompt counter *(hooks)*
- extract _parse_iso8601_utc helper, derive schema version in tests *(mcp)*
- SyncResult as dataclass, add retry with rate-limit handling *(feeds)*

### Styling

- apply ruff formatting to crud and cli *(mcp)*

### Testing

- add 11 promptfoo scenarios for features since v0.2.1 *(eval)*
- add integration test script for hook dispatcher *(hooks)*

## [0.2.1] - 2026-04-08

### Bug Fixes

- guard event shape before accessing dict methods *(feeds)*
- exclude feed entries from interest profile and add curated-first pass to /pour *(feeds)*
- use min-max normalization for hybrid search RRF scores *(store)*
- separate error handling for count_entries in distillery_list *(mcp)*
- extract git-cliff binary from nested tarball directory *(ci)*
- use absolute GitHub URLs for README images *(docs)*

### Features

- filter low-value GitHub event types at adapter level *(feeds)*
- add total_count to distillery_list responses *(store)*

### Miscellaneous

- bump version to 0.2.1

### Styling

- use ternary for ruff SIM compliant score normalization

### Testing

- tighten total_count assertions to exact expected counts

## [0.2.0] - 2026-04-07

### Bug Fixes

- make version assertions dynamic instead of hardcoded *(tests)*
- clarify pour Pass 2 tag expansion with correct prefix derivation *(skills)*
- address CodeRabbit review findings
- address CI failures — migration rollback test and CodeQL URL check
- correct docstring — login_summary uses full auth_events *(mcp)*
- remove blank line in JSON block in local-setup.md *(docs)*
- address CodeRabbit review feedback
- restore pip install mention in plugin-install.md *(docs)*
- add type guard for tool_calls in grader, revert CodeRabbit auto-fixes *(eval)*
- apply CodeRabbit auto-fixes
- move shutil import to module level *(eval)*
- rewrite assertions in Python with GradingResult dicts *(eval)*
- bump Node.js 20 → 22 and pin promptfoo@0.118.0 *(ci)*
- isolate DuckDB per test and return GradingResult objects *(eval)*
- apply CodeRabbit auto-fixes
- add uv option to docs/contributing.md setup *(docs)*
- pin promptfoo@0.118.0 to avoid jsdom ESM breakage *(ci)*
- add pip install from PyPI option to README Quick Start *(docs)*
- address PR review — pin uv version, clarify ephemeral vs persistent install *(docs)*
- pin promptfoo@0.118.0 to avoid jsdom ESM breakage *(ci)*
- bump Node.js 20 → 22 for promptfoo ESM compatibility *(ci)*
- harden changelog workflow — pin git-cliff, fix push reliability *(ci)*
- address PR review — consolidate type alias, add docstrings, add refresh audit *(auth)*
- use workflow_dispatch instead of repository_dispatch for deploy *(ci)*
- apply CodeRabbit auto-fixes
- pass config to Grype scan action, add CVE-2026-4046 *(security)*

### CI/CD

- add MCP Registry and Smithery automated publishing *(registry)*
- add PyPI download badge, changelog generation, git-cliff config

### Documentation

- update architecture, roadmap, and mcp-setup for feed-intelligence
- update CONVENTIONS.md for radar/pour retrieval changes *(skills)*
- add T03.1 proof artifacts for source tag derivation unit *(specs)*
- remove plugin install suggestion from /setup wizard *(skills)*
- clarify plugin install + uvx as two-step flow
- update /setup wizard to recommend uvx as primary setup *(skills)*
- recommend uvx as primary setup, demote demo server to fallback
- update docs for GitHub token passthrough and audit metrics
- add spec, questions, and review report for sprint1-foundation *(spec)*
- add uv/uvx as recommended installation and runtime tool

### Features

- upgrade radar and pour retrieval strategies *(skills)*
- implement hybrid BM25 + vector search with RRF fusion *(store)*
- add distillery retag backfill command *(cli)*
- add hybrid search configuration fields *(config)*
- add migration 7 for FTS index on entries.content *(store)*
- add keyword-to-tag map and topic tag matching *(feeds)*
- derive source tags from feed item metadata *(feeds)*
- add get_tag_vocabulary to protocol and DuckDBStore *(store)*
- expose audit params in tool schema and validate date_from format *(mcp)*
- add scope="audit" to distillery_metrics tool *(mcp)*
- add query_audit_log to DistilleryStore protocol and DuckDBStore *(store)*
- wire GITHUB_TOKEN through _build_adapter to GitHubAdapter *(feeds)*
- add audit events for OAuth authentication *(auth)*
- auto-deploy on container publish (#133) *(ci)*

### Miscellaneous

- bump marketplace.json plugin version to 0.2.0
- bump version to 0.2.0
- remove proof artifacts from PR
- add exploitability analysis for glibc and CPython CVEs *(security)*
- suppress unfixable CVEs in Grype scan *(security)*
- bump pypa/gh-action-pypi-publish in /.github/workflows *(deps)*

### Refactoring

- move inline import re to module level *(feeds)*
- use store.get_tag_vocabulary in tag_tree handler *(mcp)*

### Merge

- resolve conflict with main — keep both get_tag_vocabulary and query_audit_log

## [0.1.1] - 2026-04-04

### Bug Fixes

- grant contents:write to scan job for release asset uploads *(ci)*

### Documentation

- add blog post — Building a Second Brain for Claude Code

### Miscellaneous

- bump version to 0.1.1

## [0.1.0] - 2026-04-04

### Bug Fixes

- use tag ref for pypa/gh-action-pypi-publish *(ci)*
- correct pinned SHA for pypa/gh-action-pypi-publish *(ci)*
- change SessionStart hook from prompt to command type *(plugin)*
- move hooks into plugin manifest so they fire for all users (#131) *(plugin)*
- update skills path in eval runner to match repo root *(eval)*
- update plugin tests for skills/ at repo root *(test)*
- fix manifest validation errors blocking plugin install *(plugin)*
- update skills path reference in skills/index.md *(docs)*
- update plugin test for ../skills/ relative path *(test)*
- address second-round CodeRabbit review findings
- address CodeRabbit review findings
- include created_by and last_modified_by in export SELECT and entry_cols *(cli)*
- pass config to Grype scan action, add CVE-2026-4046 *(security)*
- address CI lint failures and CodeRabbit review findings *(plugin)*
- apply CodeRabbit auto-fixes
- add missing logger import and fix test lint issue *(mcp)*
- move type: ignore comment to correct line in __main__.py *(mcp)*
- address CI lint failures and CodeRabbit review findings *(skills)*
- apply CodeRabbit auto-fixes
- update stale tool references from consolidated MCP surface *(skills)*
- correct double-parentheses syntax in dedup tool references *(docs)*
- address CI lint failures and CodeRabbit review findings
- use static license badge instead of GitHub API badge *(readme)*
- enforce UTF-8 locale and guard clear for headless recording *(scripts)*
- make demo script deterministic and regenerate GIF
- resolve merge conflict, restore Demo section
- remove accidentally committed root demo files
- correct /tune threshold ordering logic *(skills)*
- address CodeRabbit review findings
- add distillery_update to /radar allowed-tools and fix docstring *(skills)*
- restore CONVENTIONS.md sections and update tool count to 24
- use distillery_check_dedup in bookmark skill for consistent dedup *(skills)*
- add missing tools to allowed-tools per skill body usage *(skills)*
- resolve merge conflict with main
- increase --max-turns from 5 to 10 for /pour multi-pass retrieval *(eval)*
- fix invalid regex flag and widen watch-list assertion *(eval)*
- widen assertion patterns for caching and pour scenarios *(eval)*
- handle output as string or object in promptfoo assertions *(eval)*
- make promptfoo assertions resilient to LLM non-determinism *(eval)*
- strip MCP prefix from tool names in promptfoo provider *(eval)*
- use stream-json --verbose to capture tool calls in promptfoo provider *(eval)*
- use distillery-dev.yaml with JINA_API_KEY secret for MCP server *(eval)*
- add --dangerously-skip-permissions to promptfoo provider *(eval)*
- split eval-pr into validate (gate) and eval (informational) jobs *(eval)*
- apply CodeRabbit auto-fixes
- align spec with PR scope and fix reporting path *(docs)*
- address code review feedback and remove proofs *(docs)*
- address CodeRabbit review findings *(eval)*
- add stdin=DEVNULL to eval runner, improve empty response diagnostics *(eval)*
- make promptfoo eval non-blocking, add config validation gate *(eval)*
- use haiku model for promptfoo CI gate *(eval)*
- remove invalid no-error assertion type from promptfoo config *(eval)*
- use JSON output format for Claude CLI, remove tracked proof files *(eval)*
- switch promptfoo provider from Anthropic API to Claude CLI *(eval)*
- remove unused DefaultsConfig import in test_config.py *(test)*
- replace Starlette Mount with ASGI dispatcher for webhook routing *(mcp)*
- address second round of CodeRabbit review comments *(mcp)*
- resolve mypy strict type errors in aggregate_entries *(mcp)*
- address CodeRabbit review comments on PR #88 *(mcp)*
- propagate FastMCP lifespan, harden audit and MCP response parsing *(mcp)*
- correct allowed_tools tool name for remote trigger *(skills)*
- address PR review — atomic cooldowns, init lock, body-size guard, limit validation *(mcp)*
- add webhooks section to Fly.io deploy config *(config)*
- correct allowed_tools tool name for remote trigger *(skills)*
- update plugin doc tests for new docs structure *(test)*
- paginate /user/orgs fallback for users in >100 orgs *(auth)*
- use suspend instead of stop for faster Fly.io resume *(deploy)*
- address CI lint errors and CodeRabbit review feedback *(auth)*
- address CodeRabbit review feedback on PR #77 *(docs)*
- address PR review — Dockerfile, Grype summary, and action pinning *(ci)*
- persist OAuth tokens across Fly.io restarts *(deploy)*
- resolve merge conflict — keep signal.signal() after logging *(mcp)*
- handle SIGTERM to flush DuckDB WAL before Fly.io shutdown *(mcp)*
- handle SIGTERM to flush DuckDB WAL before Fly.io shutdown *(mcp)*
- persist OAuth tokens across Fly.io restarts *(deploy)*
- SHA-pin actions, split scan/publish jobs, update to Node.js 24 *(ci)*
- suppress glibc and cpython CVEs with no upstream fix *(ci)*
- require RESET_DB=true env var for DB reset *(deploy)*
- address CodeRabbit round 3 feedback *(deploy,mcp)*
- address CodeRabbit round 2 review feedback *(mcp)*
- one-time DB reset to recover from corrupt WAL *(deploy)*
- address remaining CodeRabbit review feedback *(mcp)*
- address CodeRabbit review feedback *(mcp)*
- exclude server.py from coverage and add pragma on auth helper *(ci)*
- omit middleware.py from coverage to restore 80% threshold *(ci)*
- restore missing files and add py.typed marker *(ci)*
- suppress base image CVEs in Grype config *(ci)*
- update anchore/scan-action from v4 to v7 *(ci)*
- force Grype DB update before scanning *(ci)*
- address CodeRabbit review feedback *(ci)*
- one-time DB reset to recover from corrupt WAL *(deploy)*
- add avatar_url to auth.py claims list for consistency *(docs)*
- omit middleware.py from coverage to restore 80% threshold *(ci)*
- restore missing files and add py.typed marker *(ci)*
- disable Grype DB cache to prevent stale database errors *(ci)*
- simplify atexit handler and add close() tests *(store)*
- checkpoint WAL on shutdown to persist feed_sources *(store)*
- pre-install DuckDB VSS extension in Docker image *(deploy)*
- update flyctl-action to flyctl-actions (repo renamed) *(chore)*
- address CodeRabbit review feedback *(mcp)*
- address CodeRabbit review feedback *(store)*
- address CodeRabbit review feedback *(store)*
- prevent VSS extension install from hanging without network *(store)*
- use sync MagicMock for store.connection in conflict test *(test)*
- remove extra blank line flagged by ruff I001 *(test)*
- address ruff lint errors in rate limiting code *(store)*
- resolve merge conflict with recent_searches removal *(mcp)*
- address CodeRabbit review feedback *(store)*
- use persistent sentinel to prevent feed re-seeding *(store)*
- apply CodeRabbit auto-fixes
- resolve merge conflict and address CodeRabbit review *(skills)*
- wrap watch handler store calls in structured WATCH_ERROR boundary *(mcp)*
- seed YAML sources only on first run to preserve /watch removes *(store)*
- return not-found for --source against empty DB *(cli)*
- address CodeRabbit review feedback *(store)*
- patch ProxyDCRClient redirect validation (correct target) *(auth)*
- also patch MCP SDK redirect validation for localhost ports *(auth)*
- fix /data volume permissions for non-root user *(deploy)*
- patch CIMD localhost redirect validation for RFC 8252 *(auth)*
- address CodeRabbit review feedback *(deploy)*
- require 512MB for Fly.io (256MB causes OOM) *(deploy)*
- fix Fly health check path and Dockerfile resolution *(deploy)*
- keep README.md in Docker build context *(deploy)*
- use claude_args for disallowed tools instead of unsupported input
- list all 10 skills in README, add missing /setup
- prevent code review bot from editing PR title/description
- move plugin manifest to .claude-plugin/ and fix schema compliance
- address second-round PR review comments
- address PR review comments from CodeRabbit
- gracefully degrade when DuckDB VSS extension is unavailable *(store)*
- exclude same-batch entries from poll dedup check *(feeds)*
- increase timeout to 60min, lower pass threshold to 50% *(eval)*
- normalize MCP tool name prefixes in scorer *(eval)*
- remove --bare flag and add feed metadata to radar scenarios *(eval)*
- normalize cosine similarity scores from [-1,1] to [0,1] *(store)*
- move duplicate check inside _watch_lock to prevent TOCTOU race *(mcp)*
- address round 3 CodeRabbit review findings
- add 'feed' to _VALID_ENTRY_TYPES *(mcp)*
- address CodeRabbit review findings on PR #36
- sort imports alphabetically in mcp_bridge.py *(eval)*
- remove duplicate _MockEmbeddingProvider; use HashEmbeddingProvider directly *(eval)*
- unify mock model label in test config to match provider *(eval)*
- align mock embedding provider model names to resolve nightly mismatch *(eval)*
- address remaining PR review comments (round 2)
- address PR review comments
- add skill file existence/frontmatter checks and defensive next() calls *(tests)*
- remove weak OR fallbacks in transport option test *(tests)*
- resolve mypy untyped-decorator errors and ruff trailing newline *(ci)*
- apply CodeRabbit auto-fixes
- address CodeRabbit review issues and CI lint failure *(skills)*
- exclude eval/runner.py from coverage to restore 80% threshold *(ci)*
- fix ruff I001 import sorting and F401 unused yaml import *(tests)*
- use importlib.import_module to avoid mypy import-not-found for optional anthropic dep *(eval)*
- apply CodeRabbit auto-fixes
- address CodeRabbit review issues for S3/MotherDuck storage *(store)*
- resolve mypy errors for FastMCP decorator and eval optional deps *(ci)*
- add type: ignore for optional anthropic import, remove stale ignore *(eval)*
- address CodeRabbit review issues and CI failures *(eval)*
- fix ruff lint errors in eval module *(eval)*
- apply CodeRabbit auto-fixes
- address CodeRabbit review issues in MCP demo slide *(docs)*
- replace em dash with hyphen in Mermaid subgraph label *(readme)*
- apply CodeRabbit auto-fixes
- use ON CONFLICT DO NOTHING and catch ConstraintException *(store)*
- share singleton store across stateless HTTP sessions *(mcp)*
- use INSERT OR IGNORE for meta bootstrap to handle concurrent init *(store)*
- add missing trailing newlines to server.py and duckdb.py
- apply CodeRabbit auto-fixes
- retry on DuckDB write-write conflicts during initialization *(store)*
- add missing trailing newline to server.py
- apply CodeRabbit auto-fixes
- add compat shim for lifespan context across FastMCP versions *(mcp)*
- address second round of CodeRabbit review findings
- apply CodeRabbit auto-fixes
- add lazy module-level mcp attribute for FastMCP auto-discovery *(mcp)*
- apply CodeRabbit auto-fixes
- address CodeRabbit review findings
- add missing trailing newlines to fix ruff W292 CI failures
- apply CodeRabbit auto-fixes
- address code review findings across MCP server, config, and tests
- grant write permissions to claude code review action *(ci)*
- fix YAML quoting and read-only mode for in-memory DB in CLI tests *(cli)*
- replace ASCII architecture with CSS box diagram *(slides)*
- add mobile responsive styles for presentation *(slides)*
- add types-PyYAML to dev dependencies for mypy strict *(deps)*
- add enablement parameter to configure-pages action *(pages)*
- add missing PyPI classifiers and claude-code keyword (T01) *(metadata)*
- apply ruff auto-fixes to remaining source and test files (T03) *(lint)*
- enforce Python 3.11+, enable mypy strict mode, fix ruff violations

### CI/CD

- add PyPI publish workflow (#134)
- add GitHub Action for Fly.io deployment *(deploy)*
- update nightly workflow to use Claude Code CLI with OAuth token *(eval)*
- add nightly eval workflow
- add GitHub Pages workflow to publish demo slides via Jekyll *(pages)*

### Documentation

- add generic database migrations section to operator guide *(deploy)*
- update all docs for 18-tool post-consolidation surface
- add proof artifacts for T19 import KeyError fix *(specs)*
- fix import CLI syntax to use --input flag (T17) *(fly)*
- add database migrations section to Fly.io README (T04) *(fly)*
- replace demo GIF with /distill → /pour recording
- add terminal demo recording to README
- add terminal demo recording to README
- remove proof artifacts and add webhook endpoint spec with Gherkin scenarios
- fix inconsistent /api prefix in project structure comment
- update architecture, skills, and deployment docs for webhook endpoints
- remove blog post content from promotion readiness spec *(spec)*
- add launch blog post draft *(blog)*
- add badges, demo section, and .env.example *(readme)*
- add vulnerability disclosure policy *(security)*
- add spec for promotion readiness *(promotion)*
- add spec for eval framework supplement *(eval)*
- always create a PR, never push directly to main *(claude)*
- sync presentation slides with current docs
- add demo server warning to README quick start
- move demo server warning to right after /setup instructions
- add demo server warning to home page quick start
- update plugin install to use /setup instead of distillery_status
- remove Second Brain and Tiago Forte references
- add demo server warnings for hosted Fly.io instance
- center social card content vertically
- simplify social card — logo, title, tagline only
- add GitHub social card matching dark theme
- simplify roadmap — remove phase numbers and spec references
- refresh architecture diagram and fix home page logo path
- dark theme, splash landing page, and docs polish
- update CLAUDE.md for new docs structure *(claude)*
- fix MD040 fence languages, /tune example, and MotherDuck consistency
- remove redundant old docs and specs to reduce drift
- address CodeRabbit review feedback on PR #83
- replace Jekyll with MkDocs Material documentation site
- move skills into .claude-plugin/ and refresh all docs *(skills)*
- document GitHub OAuth as identity-only gate *(auth)*
- add docstrings to all test methods in test_budget.py *(test)*
- update references for deploy/ directory structure *(deploy)*
- clarify config files and deployment instructions *(deployment)*
- update install instructions for marketplace-based plugin install
- add investment pitch focus to presentation.html *(presentation)*
- rewrite demo-deck.md for conference talk
- fix presentation.html — correct skill count, phases, remove spec refs
- fix drift — presentation tool count (7→21), add feeds scope
- update all docs for specs 09-10 (21 tools, 9 skills, 1000+ tests)
- add spec-10 validation report (all gates PASS)
- update skill count from 6 to 9 in README
- add plugin install section to README
- update all docs for HTTP transport and GitHub OAuth
- add 10-spec validation report (all gates PASS) *(spec)*
- add team setup and deployment guides, skills audit (T03) *(spec)*
- add 10-spec-github-team-oauth *(spec)*
- add spec-09 validation report (all gates PASS)
- add 09-spec-cli-eval-runner *(spec)*
- replace Mermaid diagram with SVG architecture diagram
- align Mermaid diagram colors with logo palette *(readme)*
- replace ASCII architecture diagram with Mermaid *(readme)*
- update all docs for specs 05-08 (17 tools, 600+ tests, FastMCP)
- add spec-08 infrastructure improvements with backlog and CLAUDE.md
- add spec-06 MVP maturity validation report
- add 05-spec-developer-experience with research and validation *(spec)*
- add slides link to README nav bar
- add presentation slides and spec 04 (public release)
- add CONTRIBUTING.md and CHANGELOG.md for public release (T02)
- add README, roadmap, demo deck, specs, and logo assets

### Features

- show schema_version and duckdb_version in distillery status (T01.3) *(cli)*
- add distillery import subcommand (T03.2) *(cli)*
- add version tracking keys to _meta at startup (T01.2) *(store)*
- add migration runner and schema version reader (T02.2) *(store)*
- add distillery export subcommand (T03.1) *(cli)*
- create migrations.py with 6 extracted migration functions *(store)*
- pin DuckDB version to 1.5.x with compatible release clause *(store)*
- add spec for DuckDB version pinning and schema migrations *(store)*
- add distillery_configure tool for runtime config changes *(mcp)*
- add project filter to distillery_review_queue *(mcp)*
- integrate retrieval metrics into CLI display with thresholds *(eval)*
- add --compare-cost flag for cost regression detection *(eval)*
- add golden retrieval dataset and extend ScenarioResult model *(eval)*
- extend baseline JSON with per-scenario and aggregate cost data *(eval)*
- add promptfooconfig.yaml with smoke-test scenarios *(eval)*
- add eval-pr.yml CI workflow for promptfoo gate *(eval)*
- add retrieval_scorer.py with precision/recall/MRR computation *(eval)*
- add _errors.py module with standardized error codes *(mcp)*
- add DefaultsConfig dataclass for MCP handler defaults *(config)*
- add output_mode and content_max_length to distillery_list; add distillery_aggregate *(mcp)*
- add per-endpoint audit records for webhook invocations *(mcp)*
- implement maintenance webhook handler with digest entry storage *(mcp)*
- implement poll and rescore webhook handlers *(mcp)*
- compose webhook app alongside MCP in __main__.py *(mcp)*
- add webhook app factory with bearer auth and cooldown enforcement *(mcp)*
- add WebhookConfig dataclass and wire into ServerConfig *(config)*
- update /setup to use webhook scheduling, remove RemoteTrigger *(skills)*
- add GitHub Actions cron workflow for webhook scheduling *(feeds)*
- add daily rescore and weekly maintenance to /setup *(skills)*
- add GitHub org membership restriction for HTTP transport *(auth)*
- add formatted Grype and SBOM summaries to PR checks *(ci)*
- migrate to Chainguard Wolfi base image *(deploy)*
- attach SBOMs to releases and migrate Fly deploy to GHCR image *(ci)*
- add Cosign keyless signing and in-toto attestations *(ci)*
- add supply chain scanning workflow with SBOM and vulnerability gate *(ci)*
- add version and build SHA to status response *(mcp)*
- add rate limiting, embedding budget, and DB size monitoring *(store)*
- persist feed sources in DuckDB instead of in-memory config *(store)*
- switch plugin default to Fly.io hosted endpoint *(config)*
- add Fly.io deployment configuration *(deploy)*
- add marketplace manifest for self-hosted plugin installation
- add /setup onboarding wizard and update plugin manifest *(skills)*
- improve poll pipeline with defusedxml, interest scoring, rescore tool, and URL normalization *(feeds)*
- add distillery-dev.yaml with Jina embeddings and /tmp storage *(config)*
- add /radar and /tune skills, update CONVENTIONS.md *(skills)*
- add RelevanceScorer, FeedPoller, and distillery_poll tool (T03) *(feeds,mcp,cli)*
- add InterestExtractor and distillery_interests/suggest_sources tools (T04) *(feeds,mcp)*
- add GitHub and RSS adapters with FeedItem normalisation (T02) *(feeds)*
- add feed entry type, FeedsConfig, and distillery_watch tool (T01) *(store,mcp,config,skills)*
- add GitHub OAuth authentication for HTTP transport (T02) *(mcp)*
- add HTTP transport and MotherDuck validation (T01) *(mcp)*
- rewrite ClaudeEvalRunner to use CLI instead of anthropic SDK (T02) *(eval)*
- add HashEmbeddingProvider for mock embedding in eval and dev (T01) *(mcp)*
- add Claude Code plugin manifest and installation guide *(skills)*
- add S3-backed DuckDB and MotherDuck persistent storage *(store)*
- add interactive JS demo slide for hosted MCP *(docs)*
- Claude-powered skill evaluation framework *(eval)*
- add TagsConfig and reserved prefix enforcement (T03) *(config,mcp,skills)*
- add hierarchical tag namespace (T01) *(store,mcp)*
- update test_e2e_mcp.py for FastMCP interface (T03.1) *(tests)*
- add @mcp.tool() wrappers for 3 analytics tools and verify 15-tool registration (T02.3) *(mcp)*
- add @mcp.tool() wrappers for 7 search, classification, and conflict tools (T02.2) *(mcp)*
- add @mcp.tool() wrappers for 5 core CRUD tools (T02.1) *(mcp)*
- update __main__.py to use FastMCP built-in runner (T01.3) *(mcp)*
- replace Server with FastMCP scaffold and lifespan context manager (T01.2) *(mcp)*
- swap mcp dependency for fastmcp (T01.1) *(deps)*
- add distillery_stale tool and test_stale.py with full coverage (T02.2) *(mcp)*
- add distillery_quality tool and fix test_feedback.py (T01.4) *(mcp)*
- wire implicit feedback into search and get handlers (T01.3) *(mcp)*
- add test_conflict.py with full coverage for ConflictChecker and MCP conflict tools (T03.3) *(tests)*
- integrate ConflictChecker into distillery_store and add distillery_check_conflicts tool (T03.2) *(mcp)*
- add test_metrics.py with full coverage for distillery_metrics tool (T04.2) *(tests)*
- add log_search() and log_feedback() to store protocol and DuckDB (T01.2) *(store)*
- add search_log and feedback_log tables to DuckDB schema (T01.1) *(store)*
- harden CI with Python matrix, coverage threshold, and test markers *(ci)*
- add MCP server E2E test suite (T04) *(tests)*
- consolidate shared fixtures into tests/conftest.py *(tests)*
- add distillery CLI entry point and clean up dependencies *(cli)*
- align ruff, mypy, and pytest config with agentry conventions (T03) *(config)*
- switch to Apache 2.0 license and add PyPI classifiers (T01) *(metadata)*
- write /classify SKILL.md with classify-by-ID, batch inbox, and review queue modes (T04) *(skills)*
- add dedup thresholds to config and distillery_check_dedup tool (T03) *(config,mcp)*
- add distillery_classify, review_queue, resolve_review tools (T02) *(mcp)*
- implement ClassificationEngine and DeduplicationChecker (T01) *(classification)*
- write /minutes SKILL.md with new meeting, update, and list modes (T05.1) *(skills)*
- write /pour SKILL.md with multi-pass retrieval and structured synthesis (T03.1) *(skills)*
- write /bookmark SKILL.md — URL fetch, summarize, and store with dedup (T04.1) *(skills)*
- write /recall SKILL.md with semantic search, filters, and provenance (T02.1) *(skills)*
- write /distill SKILL.md with duplicate detection flow (T01.2) *(skills)*
- establish shared conventions and skill directory structure (T01.1) *(skills)*
- implement distillery_store, distillery_get, distillery_update MCP tools (T04.2) *(mcp)*
- implement distillery_search, distillery_find_similar, distillery_list tools (T04.3) *(mcp)*
- scaffold MCP server with startup, status tool, and entry points (T04.1) *(mcp)*
- integrate embedding provider into DuckDBStore and add _meta table (T03.4) *(store)*
- implement JinaEmbeddingProvider with retry and task types (T03.2) *(embedding)*
- implement OpenAIEmbeddingProvider with rate limiting and factory *(embedding)*
- add T02.3 proof artifacts for DuckDBStore CRUD operations *(store)*
- implement DuckDBStore search, find_similar, and list_entries *(store)*
- implement DuckDBStore connection, schema, and VSS index *(store)*
- implement YAML configuration system for T01.3 *(config)*
- implement Entry dataclass, enums, and SearchResult *(models)*
- add T02.1 proof artifacts for DistilleryStore protocol *(store)*
- define DistilleryStore protocol and SearchResult dataclass *(store)*
- create pyproject.toml and project directory structure *(project)*

### Miscellaneous

- remove proof artifacts from branch
- move skills directory to plugin root *(plugin)*
- suppress unfixable CVEs in Grype scan *(security)*
- remaining audit improvements from #119 *(plugin)*
- bump pygments from 2.19.2 to 2.20.0 *(deps)*
- bump fastmcp from 3.1.1 to 3.2.0 *(deps)*
- gitignore root .cast/.gif working files
- add tune/SKILL.md distillery_configure changes *(skills)*
- update /tune to use distillery_configure *(skills)*
- add --project flag to classify, minutes, radar *(skills)*
- standardize confirmation output across write skills *(skills)*
- trim /classify and document progressive disclosure pattern *(skills)*
- add dedup check to /radar SKILL.md (issue #98, item 1) *(skills)*
- extract /setup references for progressive disclosure *(skills)*
- add dedup check to /minutes *(skills)*
- add userConfig for sensitive API keys to plugin.json *(plugin)*
- rewrite skill descriptions to concise purpose statements *(skills)*
- add allowed-tools, disable-model-invocation, context, and effort to frontmatter *(skills)*
- add spec for plugin audit and skill hardening *(skills)*
- re-trigger CI
- remove blog draft and drafts dir from PR
- add MkDocs build output to .gitignore
- remove proof artifacts from tracking
- add T01 proof artifacts for supply chain scanning *(ci)*
- address review advisories *(deploy)*
- move Prefect Horizon configs into deploy/prefect/ *(deploy)*
- add Prefect Horizon deployment configuration *(deployment)*
- remove proof artifacts from tracking, add gitignore pattern
- add .worktrees to gitignore
- switch distillery.yaml to MotherDuck backend *(config)*
- commit distillery.yaml and update .gitignore *(config)*
- verify full CI pipeline passes after FastMCP migration (T03.2) *(ci)*
- remove proof artifacts, validation reports, and devcontainer
- fix lint/type errors, add devcontainer and Makefile, add spec-06 docs
- relocate brainstorm doc, add GitHub Actions CI workflow (T04) *(repo)*

### Refactoring

- generic Dockerfile, extract deploy configs to distill_ops
- replace ad-hoc init with migration system (T02.3) *(store)*
- consolidate 6 tools into existing tools (spec-07) *(mcp)*
- remove unused ANSI color variables from demo script *(scripts)*
- replace hardcoded defaults with config.defaults reads *(mcp)*
- replace INVALID_INPUT/VALIDATION_ERROR with INVALID_PARAMS *(mcp)*
- extract validate_limit helper *(mcp)*
- slim server.py to 489 lines, complete module split *(mcp)*
- extract feeds handlers to tools/feeds.py *(mcp)*
- extract analytics handlers to tools/analytics.py *(mcp)*
- extract quality handlers to tools/quality.py *(mcp)*
- extract classify handlers to tools/classify.py *(mcp)*
- extract search handlers to tools/search.py *(mcp)*
- extract CRUD handlers to tools/crud.py *(mcp)*
- create tools/ package with shared utilities *(mcp)*
- add spec for server.py split and test coverage *(mcp)*
- address second-round CodeRabbit review feedback *(auth)*
- address review advisories in supply chain workflow *(ci)*
- replace in-memory recent_searches with search_log queries *(store)*
- replace in-memory recent_searches with search_log queries *(store)*
- slim SKILL.md files by 51% and consolidate shared patterns *(skills)*
- extract _is_remote_db_path/_normalize_db_path helpers and fix W292 *(mcp)*

### Testing

- add migration system tests for T02.4 *(store)*
- add export/import round-trip tests and fix metadata serialization (T03.3) *(cli)*
- verify distillery_configure tests pass (T03.3) *(mcp)*
- add unit tests for cost tracking and comparison *(eval)*
- add end-to-end validation proofs for promptfoo PR CI gate *(eval)*
- add unit tests for retrieval scorer *(eval)*
- add adversarial scenarios for malformed input, empty store, boundaries *(eval)*
- coverage gap sweep reaches 95% on mcp/ package (T04.5) *(mcp)*
- add analytics handler tests (T04.2) *(mcp)*
- add feeds handler tests *(mcp)*
- add check_conflicts handler tests in test_mcp_conflicts.py *(mcp)*
- add 35 unit tests for all 3 middleware classes *(mcp)*
- update tool count assertions for distillery_aggregate *(mcp)*
- add webhook handler tests for poll, rescore, and maintenance *(mcp)*
- add webhook infrastructure tests for auth, cooldowns, and composition *(mcp)*
- update tests for HTTP transport default *(plugin)*
- update test_plugin.py for new manifest structure
- add setup skill scenarios, expand watch scenarios, update plugin assertions *(eval)*
- update dedup tests to use normalized similarity thresholds *(classification)*
- add eval scenarios for radar and tune skills *(skills)*
- add comprehensive unit tests for eval package *(eval)*
- add MCP server tests and setup documentation (T04.4) *(mcp)*
- add embedding provider tests and store integration tests (T03.5) *(embedding)*
- add protocol compliance tests, DuckDB store tests, and CLI health check (T02.5) *(store)*
- add comprehensive test suites for Entry and Config (T01.4) *(models,config)*

### Merge

- resolve conflict with main (take PR #126 skills path and tool count)

### Revert

- remove security hardening changes pushed directly to main

