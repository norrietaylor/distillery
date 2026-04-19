# CLI Reference

Distillery ships two console entry points:

| Binary | Purpose |
|--------|---------|
| `distillery` | Knowledge-base administration: status, health, feed polling, export/import, batch classification, evaluation harness. |
| `distillery-mcp` | MCP server (stdio or streamable-HTTP). |

Both are installed by `pip install distillery-mcp` (or `uvx distillery-mcp`).

## `distillery`

### Global flags

These flags are available on the top-level command and on every subcommand.

| Flag | Default | Description |
|------|---------|-------------|
| `--version` | — | Print package version and exit. |
| `--config PATH` | `$DISTILLERY_CONFIG` → `./distillery.yaml` | Override the configuration file. |
| `--format {text,json}` | `text` | Output format. JSON is intended for scripting. |

```bash
distillery --version
distillery --config /etc/distillery/server.yaml status
distillery status --format json | jq .total_entries
```

---

### `distillery status`

Display database statistics: path, embedding model, schema version, DuckDB version, total entry count, and breakdowns by type and status.

```bash
distillery status
distillery status --format json
```

---

### `distillery health`

Probe database connectivity. Exits `0` if the database is reachable (or a writable parent directory exists for an uninitialised store), `1` otherwise. Suitable for container health checks.

```bash
distillery health && echo "ok"
```

---

### `distillery poll`

Run a feed poll cycle: fetch from each configured source, score against the interest profile, and store relevant items.

| Flag | Default | Description |
|------|---------|-------------|
| `--source URL` | — | Poll only this source (omit to poll all sources). |

```bash
distillery poll
distillery poll --source https://example.com/feed.xml
```

---

### `distillery retag`

Backfill topic tags on existing feed entries — useful after the keyword vocabulary changes.

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | `false` | Preview changes without writing. |
| `--force` | `false` | Retag every feed entry, not just those with empty tags. |

```bash
distillery retag --dry-run
distillery retag --force
```

---

### `distillery gh-backfill`

Backfill `project`, `tags`, `author`, and `metadata` on GitHub entries that were synced before [#312](https://github.com/norrietaylor/distillery/issues/312) shipped.

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | `false` | Report how many entries would be updated; do not write. |

```bash
distillery gh-backfill --dry-run
distillery gh-backfill
```

---

### `distillery export`

Export every entry and feed source to a JSON file. The export is portable across hosts as long as the embedding model matches.

| Flag | Default | Description |
|------|---------|-------------|
| `--output PATH` | required | Path to write the JSON file. |

```bash
distillery export --output ~/distillery-snapshot.json
```

The file contains a `version`, `exported_at`, `meta` (schema + DuckDB version), `entries[]`, and `feed_sources[]`. Datetimes are normalised to UTC ISO-8601.

---

### `distillery import`

Restore entries and feed sources from a `distillery export` file. Embeddings are recomputed under the running configuration's embedding provider.

| Flag | Default | Description |
|------|---------|-------------|
| `--input PATH` | required | JSON export file to read. |
| `--mode {merge,replace}` | `merge` | `merge` skips existing IDs; `replace` deletes everything first. |
| `--yes` | `false` | Skip the confirmation prompt for `--mode replace`. |

```bash
distillery import --input ~/distillery-snapshot.json
distillery import --input snap.json --mode replace --yes
```

---

### `distillery maintenance classify`

Run batch classification over the pending-review queue (or any entry-type filter). Mirrors the `/api/maintenance` webhook step that runs in scheduled deployments.

| Flag | Default | Description |
|------|---------|-------------|
| `--type TYPE` | `inbox` | Entry type filter for the batch. |
| `--mode {llm,heuristic}` | config default | Classification mode. `llm` uses the configured LLM; `heuristic` uses embedding-based rules. |

```bash
distillery maintenance classify
distillery maintenance classify --type inbox --mode heuristic
```

---

### `distillery eval`

Run skill evaluation scenarios against Claude. Requires `ANTHROPIC_API_KEY` and `pip install 'distillery[eval]'`.

| Flag | Default | Description |
|------|---------|-------------|
| `--skill NAME` | all | Run only scenarios for one skill (e.g. `recall`, `distill`). |
| `--scenarios-dir PATH` | `tests/eval/scenarios` | Directory of scenario YAML files. |
| `--save-baseline PATH` | — | Write current results as a JSON baseline for regression comparison. |
| `--baseline PATH` | — | Compare current run against this baseline. |
| `--model MODEL` | `claude-haiku-4-5-20251001` | Claude model under test. |
| `--compare-cost` | `false` | Print cost delta vs. baseline (requires `--baseline`). |

```bash
distillery eval --skill recall
distillery eval --baseline baselines/main.json --compare-cost
```

---

## `distillery-mcp`

Start the MCP server. Stdio is the default (no flags needed); HTTP requires `--transport http` and is intended for team / hosted deployments.

| Flag | Default | Description |
|------|---------|-------------|
| `--transport {stdio,http}` | `stdio` | Transport protocol. |
| `--host HOST` | `$DISTILLERY_HOST` → `0.0.0.0` | HTTP bind address (HTTP transport only). |
| `--port PORT` | `$DISTILLERY_PORT` → `8000` | HTTP bind port (HTTP transport only). |

```bash
# Local stdio (Claude Code default)
distillery-mcp

# Local HTTP for browser/team testing
distillery-mcp --transport http --host 127.0.0.1 --port 9000
```

For HTTP deployment with GitHub OAuth and webhook scheduling, see [Operator Deployment](../team/deployment.md).

---

## Environment variables

### Server lifecycle

| Variable | Used by | Purpose |
|----------|---------|---------|
| `DISTILLERY_CONFIG` | both | Path to `distillery.yaml` (overrides cwd lookup). |
| `DISTILLERY_HOST` | `distillery-mcp` | Default HTTP bind address. |
| `DISTILLERY_PORT` | `distillery-mcp` | Default HTTP bind port. |
| `DISTILLERY_BASE_URL` | `distillery-mcp` (HTTP) | Public URL used for OAuth redirects. |
| `DISTILLERY_ALLOWED_ORGS` | `distillery-mcp` (HTTP) | Comma-separated GitHub orgs allowed to authenticate. |
| `DISTILLERY_DASHBOARD_DIR` | `distillery-mcp` | Override the bundled MCP-Apps dashboard `dist/` location. |
| `DISTILLERY_WEBHOOK_SECRET` | `distillery-mcp` (HTTP) | Bearer token required by `/api/*` webhook endpoints. |

### Provider credentials

| Variable | Required when | Purpose |
|----------|---------------|---------|
| `JINA_API_KEY` | `embedding.provider: jina` | Jina embedding API key. |
| `OPENAI_API_KEY` | `embedding.provider: openai` | OpenAI embedding API key. |
| `ANTHROPIC_API_KEY` | `distillery eval` | Claude API key for the eval harness. |
| `GITHUB_TOKEN` | private GitHub feeds | Token used by the GitHub feed adapter. |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | `distillery-mcp --transport http` with `auth.provider: github` | OAuth App credentials. |
| `MOTHERDUCK_TOKEN` | MotherDuck storage backend | MotherDuck cloud token. |
| `AWS_DEFAULT_REGION` / `AWS_REGION` | S3 storage backend | Region for S3-backed storage. |

The `JINA_API_KEY` / `OPENAI_API_KEY` variable name is also configurable per provider via `embedding.api_key_env` in `distillery.yaml`.

---

## See also

- [MCP Server Reference](../getting-started/mcp-setup.md) — list of MCP tools and resources
- [Local Setup](../getting-started/local-setup.md) — first-time install and configuration
- [Operator Deployment](../team/deployment.md) — HTTP, GitHub OAuth, webhook scheduling
