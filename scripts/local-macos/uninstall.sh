#!/usr/bin/env bash
# Tear down the Distillery local macOS setup.
#
# Default behaviour:
#   • Unload all local.distillery* LaunchAgents
#   • Stop and remove the docker container
#   • Remove plists from ~/Library/LaunchAgents
#   • Remove scripts from ~/.distillery (run.sh, update.sh, *.sh workers,
#     _webhook_common.sh)
#
# Preserved by default (destructive; requires explicit flags):
#   --purge-data    also delete distillery.yaml, distillery.db, logs
#   --purge-secrets also delete the Keychain entries (JINA_API_KEY,
#                   DISTILLERY_WEBHOOK_SECRET)
#
# Examples:
#   ./uninstall.sh
#   ./uninstall.sh --purge-data
#   ./uninstall.sh --purge-data --purge-secrets

set -euo pipefail

DATA_DIR=$HOME/.distillery
LAUNCHAGENTS=$HOME/Library/LaunchAgents

PURGE_DATA=0
PURGE_SECRETS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --purge-data)    PURGE_DATA=1; shift ;;
    --purge-secrets) PURGE_SECRETS=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

log() { printf '  %s\n' "$*"; }
bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }

AGENTS=(
  local.distillery
  local.distillery-update
  local.distillery-poll
  local.distillery-classify
  local.distillery-rescore
  local.distillery-maintenance
)

UID_NUM=$(id -u)

bold "Unload agents"
for label in "${AGENTS[@]}"; do
  if launchctl print "gui/$UID_NUM/$label" >/dev/null 2>&1; then
    launchctl bootout "gui/$UID_NUM/$label" >/dev/null 2>&1 || true
    log "$label: unloaded"
  else
    log "$label: not loaded"
  fi
done

bold "Remove container"
DOCKER=$(command -v docker 2>/dev/null || true)
[ -z "$DOCKER" ] && [ -x "$HOME/.orbstack/bin/docker" ] && DOCKER=$HOME/.orbstack/bin/docker
if [ -n "$DOCKER" ] && "$DOCKER" info >/dev/null 2>&1; then
  "$DOCKER" rm -f distillery >/dev/null 2>&1 || true
  log "container 'distillery' removed (if present)"
else
  log "docker not reachable — skipped"
fi

bold "Remove plists"
for label in "${AGENTS[@]}"; do
  if [ -f "$LAUNCHAGENTS/${label}.plist" ]; then
    rm -f "$LAUNCHAGENTS/${label}.plist"
    log "${label}.plist: removed"
  fi
done

bold "Remove scripts"
for f in run.sh update.sh poll.sh classify.sh rescore.sh maintenance.sh _webhook_common.sh; do
  if [ -f "$DATA_DIR/$f" ]; then
    rm -f "$DATA_DIR/$f"
    log "$f: removed"
  fi
done

if [ "$PURGE_DATA" -eq 1 ]; then
  bold "Purge data"
  for f in distillery.yaml distillery.db distillery.db.wal \
           server.log server.err.log update.log update.out.log update.err.log \
           poll.out.log poll.err.log classify.out.log classify.err.log \
           rescore.out.log rescore.err.log maintenance.out.log maintenance.err.log; do
    if [ -e "$DATA_DIR/$f" ]; then
      rm -f "$DATA_DIR/$f"
      log "$f: removed"
    fi
  done
  rmdir "$DATA_DIR" 2>/dev/null && log "$DATA_DIR: removed (empty)" || true
fi

if [ "$PURGE_SECRETS" -eq 1 ]; then
  bold "Purge secrets"
  for svc in JINA_API_KEY DISTILLERY_WEBHOOK_SECRET; do
    if security delete-generic-password -a "$USER" -s "$svc" >/dev/null 2>&1; then
      log "$svc: removed from Keychain"
    else
      log "$svc: not in Keychain"
    fi
  done
fi

bold "Done"
if [ "$PURGE_DATA" -eq 0 ]; then
  log "Data preserved in $DATA_DIR (pass --purge-data to delete)"
fi
if [ "$PURGE_SECRETS" -eq 0 ]; then
  log "Keychain entries preserved (pass --purge-secrets to delete)"
fi
