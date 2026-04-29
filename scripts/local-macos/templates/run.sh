#!/bin/zsh
# Launched by ~/Library/LaunchAgents/local.distillery.plist.
# Runs the Distillery MCP server (GHCR image) in the foreground so launchd
# can supervise it and restart on exit.

set -eu

DOCKER="__DOCKER__"
IMAGE=ghcr.io/norrietaylor/distillery:latest
PLATFORM=linux/amd64        # no arm64 manifest on GHCR; runs under Rosetta
NAME=distillery
DATA_DIR=$HOME/.distillery
PORT=8000

# Wait up to 60s for the docker daemon. OrbStack and Docker Desktop both
# auto-start on demand, but a cold-from-shutdown start (or a login before
# autostart kicks in) can take 20-40s before the socket is ready.
for _ in $(seq 1 30); do
  if "$DOCKER" info >/dev/null 2>&1; then break; fi
  sleep 2
done

JINA_API_KEY=$(security find-generic-password -a "$USER" -s JINA_API_KEY -w 2>/dev/null || true)
if [ -z "${JINA_API_KEY}" ]; then
  echo "JINA_API_KEY not found in Keychain (service=JINA_API_KEY)." >&2
  echo "  security add-generic-password -a \"$USER\" -s JINA_API_KEY -w <key> -U" >&2
  exit 1
fi

DISTILLERY_WEBHOOK_SECRET=$(security find-generic-password -a "$USER" -s DISTILLERY_WEBHOOK_SECRET -w 2>/dev/null || true)
if [ -z "${DISTILLERY_WEBHOOK_SECRET}" ]; then
  echo "DISTILLERY_WEBHOOK_SECRET not found in Keychain (service=DISTILLERY_WEBHOOK_SECRET)." >&2
  echo "  security add-generic-password -a \"$USER\" -s DISTILLERY_WEBHOOK_SECRET \\" >&2
  echo "    -w \"\$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')\" -U" >&2
  exit 1
fi

# Clean up any prior instance (stale after crash, reboot, or image swap).
"$DOCKER" rm -f "$NAME" >/dev/null 2>&1 || true

exec "$DOCKER" run \
  --rm \
  --name "$NAME" \
  --platform "$PLATFORM" \
  -p 127.0.0.1:${PORT}:8000 \
  -v "$DATA_DIR":/data \
  -e DISTILLERY_CONFIG=/data/distillery.yaml \
  -e JINA_API_KEY="$JINA_API_KEY" \
  -e DISTILLERY_WEBHOOK_SECRET="$DISTILLERY_WEBHOOK_SECRET" \
  -e DISTILLERY_HOST=0.0.0.0 \
  -e DISTILLERY_PORT=8000 \
  "$IMAGE"
