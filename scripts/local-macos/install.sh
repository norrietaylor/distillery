#!/usr/bin/env bash
# Install the Distillery local macOS setup:
#   • supervised server container (GHCR image) via launchd
#   • weekly image-update agent
#   • four scheduled webhook agents: poll / classify / rescore / maintenance
#
# Safe to re-run; reinstalls scripts, rewrites plists, reloads agents.
# Does not destroy the DuckDB file or existing Keychain entries.
#
# Usage:
#   ./install.sh              # interactive
#   ./install.sh --jina-key "jina_..."
#   ./install.sh --no-kickstart   # install but don't start agents
#
# The generated webhook bearer secret is created on first run only; subsequent
# runs leave it alone. Delete it with `security delete-generic-password
# -a "$USER" -s DISTILLERY_WEBHOOK_SECRET` to rotate.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
TEMPLATES=$SCRIPT_DIR/templates

DATA_DIR=$HOME/.distillery
LAUNCHAGENTS=$HOME/Library/LaunchAgents

JINA_KEY_CLI=""
DO_KICKSTART=1

while [ $# -gt 0 ]; do
  case "$1" in
    --jina-key)
      if [ $# -lt 2 ] || [[ "$2" == -* ]]; then
        echo "--jina-key requires a value" >&2
        exit 2
      fi
      JINA_KEY_CLI="$2"
      shift 2
      ;;
    --no-kickstart)   DO_KICKSTART=0; shift ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

log() { printf '  %s\n' "$*"; }
bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

# ---- preflight --------------------------------------------------------------

bold "Preflight"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "this installer is macOS-only (uname=$(uname -s))" >&2
  exit 1
fi
log "macOS detected"

require security
require launchctl
require curl
require python3
log "security / launchctl / curl / python3 available"

# Locate docker binary. OrbStack installs to ~/.orbstack/bin; Docker Desktop
# installs to /usr/local/bin. Prefer whichever `docker` is on PATH; fall back
# to the common install locations.
DOCKER=""
for candidate in "$(command -v docker 2>/dev/null || true)" \
                 "$HOME/.orbstack/bin/docker" \
                 "/usr/local/bin/docker" \
                 "/opt/homebrew/bin/docker"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    DOCKER=$candidate
    break
  fi
done
if [ -z "$DOCKER" ]; then
  echo "docker not found — install OrbStack (https://orbstack.dev) or Docker Desktop" >&2
  exit 1
fi
log "docker: $DOCKER"

DOCKER_DIR=$(dirname "$DOCKER")

if ! "$DOCKER" info >/dev/null 2>&1; then
  echo "docker daemon is not running — start OrbStack/Docker Desktop and re-run" >&2
  exit 1
fi
log "docker daemon reachable"

# ---- secrets ----------------------------------------------------------------

bold "Secrets (login Keychain)"

# Jina API key: keep existing entry, or accept --jina-key, or prompt.
if security find-generic-password -a "$USER" -s JINA_API_KEY -w >/dev/null 2>&1; then
  log "JINA_API_KEY: already in Keychain (keeping existing value)"
else
  if [ -z "$JINA_KEY_CLI" ]; then
    echo
    read -r -s -p "  Jina API key (free tier at https://jina.ai) [paste, not echoed]: " JINA_KEY_CLI
    echo
  fi
  if [ -z "$JINA_KEY_CLI" ]; then
    echo "JINA_API_KEY is required" >&2
    exit 1
  fi
  security add-generic-password -a "$USER" -s JINA_API_KEY -w "$JINA_KEY_CLI" -U
  log "JINA_API_KEY: stored"
fi

# Webhook bearer secret: generate once, then leave alone.
if security find-generic-password -a "$USER" -s DISTILLERY_WEBHOOK_SECRET -w >/dev/null 2>&1; then
  log "DISTILLERY_WEBHOOK_SECRET: already in Keychain (keeping existing value)"
else
  SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  security add-generic-password -a "$USER" -s DISTILLERY_WEBHOOK_SECRET -w "$SECRET" -U
  log "DISTILLERY_WEBHOOK_SECRET: generated and stored"
fi

# ---- data dir + config ------------------------------------------------------

bold "Data directory"

mkdir -p "$DATA_DIR"
log "ensured $DATA_DIR"

if [ -f "$DATA_DIR/distillery.yaml" ]; then
  log "distillery.yaml: already present (keeping existing; compare against $TEMPLATES/distillery.yaml for changes)"
else
  cp "$TEMPLATES/distillery.yaml" "$DATA_DIR/distillery.yaml"
  log "distillery.yaml: installed"
fi

# ---- scripts ----------------------------------------------------------------

bold "Scripts"

install_script() {
  local src="$1" dst="$2"
  # Substitute the detected docker path into any __DOCKER__ placeholder.
  sed -e "s|__DOCKER__|$DOCKER|g" "$src" >"$dst"
  chmod +x "$dst"
  log "$(basename "$dst")"
}

install_script "$TEMPLATES/run.sh"              "$DATA_DIR/run.sh"
install_script "$TEMPLATES/update.sh"           "$DATA_DIR/update.sh"
install_script "$TEMPLATES/_webhook_common.sh"  "$DATA_DIR/_webhook_common.sh"
install_script "$TEMPLATES/poll.sh"             "$DATA_DIR/poll.sh"
install_script "$TEMPLATES/classify.sh"         "$DATA_DIR/classify.sh"
install_script "$TEMPLATES/rescore.sh"          "$DATA_DIR/rescore.sh"
install_script "$TEMPLATES/maintenance.sh"      "$DATA_DIR/maintenance.sh"

# ---- LaunchAgents -----------------------------------------------------------

bold "LaunchAgents"

mkdir -p "$LAUNCHAGENTS"

install_plist() {
  local label="$1"
  local src="$TEMPLATES/launchd/${label}.plist"
  local dst="$LAUNCHAGENTS/${label}.plist"
  sed -e "s|__HOME__|$HOME|g" \
      -e "s|__DOCKER_DIR__|$DOCKER_DIR|g" \
      "$src" >"$dst"
  log "$(basename "$dst")"
}

AGENTS=(
  local.distillery
  local.distillery-update
  local.distillery-poll
  local.distillery-classify
  local.distillery-rescore
  local.distillery-maintenance
)

for label in "${AGENTS[@]}"; do
  install_plist "$label"
done

# ---- load + start -----------------------------------------------------------

bold "Load agents"

UID_NUM=$(id -u)
for label in "${AGENTS[@]}"; do
  plist="$LAUNCHAGENTS/${label}.plist"
  # Bootout first so re-installs pick up changes, then bootstrap.
  launchctl bootout "gui/$UID_NUM/$label" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$UID_NUM" "$plist"
  log "$label: loaded"
done

if [ "$DO_KICKSTART" -eq 1 ]; then
  bold "Verify"
  launchctl kickstart -k "gui/$UID_NUM/local.distillery" >/dev/null 2>&1 || true
  log "server kickstarted; waiting for http://127.0.0.1:8000 ..."

  ready=0
  for _ in $(seq 1 30); do
    if curl -sS --max-time 2 -o /dev/null "http://127.0.0.1:8000/" 2>/dev/null; then
      ready=1; break
    fi
    sleep 1
  done
  if [ "$ready" -eq 1 ]; then
    log "server is responding"
  else
    log "server did not respond within 30s — check $DATA_DIR/server.err.log"
  fi
fi

bold "Done"
cat <<EOF
  Data dir:       $DATA_DIR
  LaunchAgents:   $LAUNCHAGENTS/local.distillery*.plist
  Logs:           $DATA_DIR/*.log
  Uninstall:      $SCRIPT_DIR/uninstall.sh

Point Claude Code at the server by adding to ~/.claude/settings.json:

  {
    "mcpServers": {
      "distillery": {
        "type": "http",
        "url": "http://127.0.0.1:8000/mcp"
      }
    }
  }

Then run /setup inside Claude Code to configure the reporting routines.
EOF
