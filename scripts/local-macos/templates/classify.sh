#!/bin/zsh
# Launched by ~/Library/LaunchAgents/local.distillery-classify.plist every 2h.
# Batch-classifies pending inbox entries via POST /api/hooks/classify-batch.
# That endpoint is synchronous and returns 200 with a summary body.

set -eu
source "$HOME/.distillery/_webhook_common.sh"
call_webhook classify "$SERVER_BASE/api/hooks/classify-batch" 120 '^(200|202)$'
