#!/bin/zsh
# Launched by ~/Library/LaunchAgents/local.distillery-rescore.plist daily.
# Recomputes relevance scores for stored feed entries via POST /api/rescore.

set -eu
source "$HOME/.distillery/_webhook_common.sh"
call_webhook rescore "$SERVER_BASE/api/rescore" 20 '^(202|409|429)$'
