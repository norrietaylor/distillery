# Local macOS (launchd)

Runs a supervised Distillery server on your Mac with scheduled ingestion, image updates, and maintenance — zero cloud, zero CI. Installed by `scripts/local-macos/install.sh`.

This is a different profile from the [stdio local setup](local-setup.md):

| | stdio (`local-setup.md`) | launchd (this page) |
|---|---|---|
| Transport | stdio | HTTP on `127.0.0.1:8000` |
| Lifecycle | launched per Claude Code session | supervised daemon, runs 24/7 |
| Scheduled work | optional Claude Code routines | six LaunchAgents |
| Image updates | manual | weekly auto-pull |
| Good for | single-user, low-footprint | heavier feed ingestion, personal KB |

## What gets installed

Six LaunchAgents in `~/Library/LaunchAgents/`:

| Label | Cadence | Purpose |
|---|---|---|
| `local.distillery` | supervised | Runs the GHCR container (`ghcr.io/norrietaylor/distillery:latest`) in the foreground; launchd restarts it on exit. |
| `local.distillery-update` | Mondays 09:00 | `docker pull` the `:latest` image; if the digest changed, kickstart the server. |
| `local.distillery-poll` | every 30 min | `POST /api/poll` — fetch new items from configured feed sources. |
| `local.distillery-classify` | every 2 hours | `POST /api/hooks/classify-batch` — batch-classify pending inbox entries. |
| `local.distillery-rescore` | daily 04:15 | `POST /api/rescore` — refresh feed-entry relevance scores. |
| `local.distillery-maintenance` | Mondays 05:00 | `POST /api/maintenance` — orchestrated `poll → rescore → classify-batch`. |

Plus these files in `~/.distillery/`:

- `distillery.yaml` — server config
- `run.sh`, `update.sh` — server supervisor + image-update worker
- `poll.sh`, `classify.sh`, `rescore.sh`, `maintenance.sh` — webhook workers
- `_webhook_common.sh` — shared helper sourced by the four workers
- `distillery.db` — the DuckDB file
- `*.log` — per-agent stdout/stderr

And two entries in the macOS login Keychain (`security` CLI):

- `JINA_API_KEY` — embedding provider key
- `DISTILLERY_WEBHOOK_SECRET` — bearer token for `/api/*` routes

## Prerequisites

- macOS (tested on Sonoma and later)
- [OrbStack](https://orbstack.dev) *or* Docker Desktop, running
- A free [Jina AI](https://jina.ai) API key

Docker on Apple Silicon runs the container under Rosetta (`linux/amd64`). No separate arm64 image is published.

## Install

```bash
git clone https://github.com/norrietaylor/distillery.git
cd distillery
./scripts/local-macos/install.sh
```

The installer will:

1. Verify Docker is reachable.
2. Prompt for your Jina API key (skipped if already in the Keychain).
3. Generate a 32-byte webhook bearer secret (skipped if already in the Keychain).
4. Write the config, scripts, and plists.
5. Bootstrap every agent and kickstart the server.
6. Wait up to 30 s for `http://127.0.0.1:8000/` to respond.

Re-run any time to refresh scripts/plists — the installer is idempotent and never touches the database or existing secrets.

### Flags

| Flag | Effect |
|---|---|
| `--jina-key <value>` | Pass the Jina key non-interactively (useful for scripted installs). |
| `--no-kickstart` | Load the agents but don't start the server or poll for readiness. |

## Point Claude Code at the server

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "distillery": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Restart Claude Code, then run `/setup` — it will detect the running server and offer to configure the reporting routines (feed health check, stale check, weekly digest). Those routines run inside Claude Code and complement the ingestion agents installed here.

## Verify

```bash
# All six agents loaded
launchctl list | grep distillery

# Kick the server in case it's not running
launchctl kickstart -k gui/$(id -u)/local.distillery

# Server is up
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/

# Webhook auth works (expects 202 Accepted)
SECRET=$(security find-generic-password -a "$USER" -s DISTILLERY_WEBHOOK_SECRET -w)
curl -sS -H "Authorization: Bearer $SECRET" -X POST http://127.0.0.1:8000/api/poll
```

Tail the logs to watch the agents fire:

```bash
tail -F ~/.distillery/{poll,classify,rescore,maintenance}.out.log
```

## Customizing

### Change the cadence

Edit the `StartInterval` (seconds) or `StartCalendarInterval` block in the plist, then reload:

```bash
launchctl bootout gui/$(id -u)/local.distillery-poll
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.distillery-poll.plist
```

### Rotate the webhook secret

```bash
security delete-generic-password -a "$USER" -s DISTILLERY_WEBHOOK_SECRET
./scripts/local-macos/install.sh     # regenerates on next install
launchctl kickstart -k gui/$(id -u)/local.distillery
```

### Add a feed source

Open Claude Code and run `/watch add <url>`, or call `distillery_watch` directly via the MCP.

### Disable one pipeline

```bash
launchctl bootout gui/$(id -u)/local.distillery-rescore
rm ~/Library/LaunchAgents/local.distillery-rescore.plist
```

## Troubleshooting

**Webhook returns 401.** The server didn't see `DISTILLERY_WEBHOOK_SECRET` at startup — check the Keychain entry exists, then `launchctl kickstart -k gui/$(id -u)/local.distillery`.

**Webhook returns 429 "too_early".** Per-endpoint cooldown. The worker treats this as success; nothing to fix.

**Container won't start.** Inspect `~/.distillery/server.err.log`. The supervisor exits 1 if `JINA_API_KEY` or `DISTILLERY_WEBHOOK_SECRET` is missing from the Keychain — launchd respects `ThrottleInterval=10` so it retries every 10 s.

**`IO Error: Conflicting lock`.** Something other than the server is trying to open the DuckDB file (`docker exec ... distillery <cmd>`, a second container, a CLI on the host). DuckDB is single-writer; only the running server process may open the DB for writes. Use the HTTP webhooks instead.

**Agents silently not firing.** `launchctl print gui/$(id -u)/<label>` shows the next fire time and the last exit status. For calendar-based agents, confirm the Mac was awake at the scheduled minute — `StartCalendarIntervalRunOnMissed=true` triggers a catch-up on next wake.

## Uninstall

```bash
./scripts/local-macos/uninstall.sh                       # unload agents, remove files
./scripts/local-macos/uninstall.sh --purge-data          # + delete DB, config, logs
./scripts/local-macos/uninstall.sh --purge-secrets       # + delete Keychain entries
```

Default uninstall preserves the database and Keychain entries so a re-install is non-destructive.
