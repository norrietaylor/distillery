# Local macOS launchd setup

One-shot installer for running a self-hosted Distillery server on macOS with
supervised lifecycle and scheduled ingestion pipelines.

## What it installs

| LaunchAgent | Cadence | What it does |
|---|---|---|
| `local.distillery` | supervised | runs the GHCR container in the foreground; restarts on exit |
| `local.distillery-update` | Mon 09:00 | pulls `:latest`; restarts the server if the digest changed |
| `local.distillery-poll` | every 30 min | `POST /api/poll` — ingest new feed items |
| `local.distillery-classify` | every 2 h | `POST /api/hooks/classify-batch` — drain the inbox |
| `local.distillery-rescore` | daily 04:15 | `POST /api/rescore` — refresh relevance scores |
| `local.distillery-maintenance` | Mon 05:00 | `POST /api/maintenance` — full pipeline (poll → rescore → classify) |

All ingestion goes through the running server's HTTP surface, not a sibling
CLI process — DuckDB is single-writer, and the server holds the write lock.

## Install

```bash
./install.sh
```

The installer:

1. Verifies Docker (OrbStack or Docker Desktop) is reachable.
2. Reads or prompts for a Jina API key; stores it in the login Keychain.
3. Generates a 32-byte webhook bearer secret; stores it in the Keychain.
4. Writes `~/.distillery/{distillery.yaml,*.sh}` and six plists in
   `~/Library/LaunchAgents/`.
5. Bootstraps each agent and kickstarts the server.

It's idempotent — re-running refreshes scripts and plists without touching
the DB or existing secrets.

## Uninstall

```bash
./uninstall.sh                           # unload agents, remove scripts/plists/container
./uninstall.sh --purge-data              # also delete distillery.yaml + DB + logs
./uninstall.sh --purge-secrets           # also delete Keychain entries
```

## See also

Full walkthrough: [docs/getting-started/local-macos.md](../../docs/getting-started/local-macos.md).
