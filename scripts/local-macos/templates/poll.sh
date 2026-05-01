#!/bin/zsh
# Launched by ~/Library/LaunchAgents/local.distillery-poll.plist every 30 min.
# Polls configured feed sources via POST /api/poll. The running server owns
# the DuckDB write lock, so ingestion must go through its HTTP surface.
#
# 202 = accepted, 409 = job already in flight, 429 = cooldown not elapsed.

set -eu
source "$HOME/.distillery/_webhook_common.sh"
call_webhook poll "$SERVER_BASE/api/poll" 20 '^(202|409|429)$'
