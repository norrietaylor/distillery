#!/bin/zsh
# Launched by ~/Library/LaunchAgents/local.distillery-update.plist.
# Pulls ghcr.io/norrietaylor/distillery:latest; if the image changed,
# restarts the server and records the delta in ~/.distillery/update.log.

set -eu

DOCKER="__DOCKER__"
IMAGE=ghcr.io/norrietaylor/distillery:latest
PLATFORM=linux/amd64
LOG=$HOME/.distillery/update.log

# Wait up to 60s for the docker daemon to come up.
for _ in $(seq 1 30); do
  if "$DOCKER" info >/dev/null 2>&1; then break; fi
  sleep 2
done

OLD_SHA=$("$DOCKER" image inspect "$IMAGE" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
  | awk -F= '/^DISTILLERY_BUILD_SHA=/{print $2}') || OLD_SHA=""
OLD_DIGEST=$("$DOCKER" image inspect "$IMAGE" --format '{{.Id}}' 2>/dev/null || true)

"$DOCKER" pull --platform "$PLATFORM" --quiet "$IMAGE" >/dev/null

NEW_SHA=$("$DOCKER" image inspect "$IMAGE" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | awk -F= '/^DISTILLERY_BUILD_SHA=/{print $2}')
NEW_DIGEST=$("$DOCKER" image inspect "$IMAGE" --format '{{.Id}}')

TS=$(date -Iseconds)

if [ "$OLD_DIGEST" = "$NEW_DIGEST" ]; then
  echo "[$TS] no change (digest $NEW_DIGEST, build $NEW_SHA)" >> "$LOG"
  exit 0
fi

{
  echo "[$TS] image updated"
  echo "  old build: ${OLD_SHA:-<none>}   digest: ${OLD_DIGEST:-<none>}"
  echo "  new build: ${NEW_SHA}             digest: ${NEW_DIGEST}"
} >> "$LOG"

# Restart the server so it picks up the new image.
launchctl kickstart -k "gui/$(id -u)/local.distillery" >/dev/null 2>&1 || true
echo "  restarted local.distillery" >> "$LOG"
