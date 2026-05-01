#!/bin/zsh
# Launched by ~/Library/LaunchAgents/local.distillery-maintenance.plist weekly.
# Runs the orchestrated pipeline (poll -> rescore -> classify-batch) via
# POST /api/maintenance. Safe to run alongside the per-job agents; the
# server's per-endpoint cooldowns coalesce overlapping work.

set -eu
source "$HOME/.distillery/_webhook_common.sh"
call_webhook maintenance "$SERVER_BASE/api/maintenance" 30 '^(202|409|429)$'
