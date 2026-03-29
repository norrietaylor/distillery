#!/bin/bash
#
# smoke-test.sh — Distillery MCP Server Health Check
#
# Usage:
#   ./scripts/smoke-test.sh <endpoint-url>
#
# Examples:
#   ./scripts/smoke-test.sh http://localhost:8000
#   ./scripts/smoke-test.sh https://distillery.myteam.com
#   ./scripts/smoke-test.sh https://my-lambda-function-url.lambda-url.us-east-1.on.aws
#
# Validates:
# 1. /health endpoint returns status: ok
# 2. MCP initialize handshake succeeds
# 3. tools/list returns exactly 21 tools
# 4. Handles auth-enabled mode (401 → DCR instructions)
#
# Exit codes:
#   0 - All tests passed
#   1 - Test failed or invalid input
#   2 - Missing curl or jq
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Utility Functions
# ============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $*"
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

# ============================================================================
# Validation
# ============================================================================

if [ $# -ne 1 ]; then
    cat <<EOF
${RED}Error: Missing endpoint URL${NC}

Usage: $0 <endpoint-url>

Examples:
  $0 http://localhost:8000
  $0 https://distillery.myteam.com
  $0 https://my-lambda-function-url.lambda-url.us-east-1.on.aws

EOF
    exit 1
fi

ENDPOINT_URL="$1"

# Validate URL format (basic check)
if ! [[ "$ENDPOINT_URL" =~ ^https?:// ]]; then
    log_fail "Invalid URL format: $ENDPOINT_URL"
    log_info "URL must start with http:// or https://"
    exit 1
fi

# Check dependencies
for cmd in curl python3; do
    if ! command -v "$cmd" &> /dev/null; then
        log_fail "Required command not found: $cmd"
        exit 2
    fi
done

log_info "Distillery MCP Smoke Test"
log_info "Endpoint: $ENDPOINT_URL"
echo ""

# ============================================================================
# Test 1: /health endpoint
# ============================================================================

log_info "Test 1: /health endpoint"

HEALTH_RESPONSE=$(curl --silent --show-error --max-time 30 \
    --write-out "\n%{http_code}" \
    "${ENDPOINT_URL}/health" 2>&1 || true)

# Split response and status code
HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -1)
BODY=$(echo "$HEALTH_RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ]; then
    # Parse the response
    STATUS=$(echo "$BODY" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('status', ''))
except:
    print('')
" 2>/dev/null || echo "")

    if [ "$STATUS" = "ok" ]; then
        log_pass "/health returned status: ok"
    else
        log_fail "/health returned unexpected status: $STATUS"
        log_info "Full response: $BODY"
        exit 1
    fi
elif [ "$HTTP_CODE" = "401" ]; then
    log_warn "/health returned 401 (Unauthorized) — server requires authentication"
    log_info ""
    log_info "This server has GitHub OAuth enabled. To authenticate:"
    log_info "  1. Set up your GitHub OAuth token from the Distillery UI"
    log_info "  2. Use /recall or other commands from Claude Code"
    log_info "  3. See docs/deployment.md for more info"
    log_info ""
    log_fail "Cannot complete smoke test without authentication"
    exit 1
else
    log_fail "/health returned HTTP $HTTP_CODE"
    log_info "Full response: $BODY"
    exit 1
fi

echo ""

# ============================================================================
# Test 2: MCP initialize handshake
# ============================================================================

log_info "Test 2: MCP initialize handshake"

INIT_RESPONSE=$(curl --silent --show-error --max-time 30 \
    --request POST \
    --header "Content-Type: application/json" \
    --write-out "\n%{http_code}" \
    --data '{
      "jsonrpc": "2.0",
      "id": 1,
      "method": "initialize",
      "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {
          "name": "distillery-smoke-test",
          "version": "1.0.0"
        }
      }
    }' \
    "${ENDPOINT_URL}/mcp" 2>&1 || true)

HTTP_CODE=$(echo "$INIT_RESPONSE" | tail -1)
BODY=$(echo "$INIT_RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    # Verify response has a result field
    HAS_RESULT=$(echo "$BODY" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print('yes' if 'result' in d else 'no')
except:
    print('no')
" 2>/dev/null || echo "no")

    if [ "$HAS_RESULT" = "yes" ]; then
        log_pass "MCP initialize handshake succeeded"
    else
        log_fail "MCP initialize returned invalid response (no result field)"
        log_info "Full response: $BODY"
        exit 1
    fi
elif [ "$HTTP_CODE" = "401" ]; then
    log_warn "MCP initialize returned 401 (Unauthorized)"
    log_fail "Cannot complete smoke test without authentication"
    exit 1
else
    log_fail "MCP initialize returned HTTP $HTTP_CODE"
    log_info "Full response: $BODY"
    exit 1
fi

echo ""

# ============================================================================
# Test 3: tools/list returns 21 tools
# ============================================================================

log_info "Test 3: tools/list (expecting 21 tools)"

TOOLS_RESPONSE=$(curl --silent --show-error --max-time 30 \
    --request POST \
    --header "Content-Type: application/json" \
    --write-out "\n%{http_code}" \
    --data '{
      "jsonrpc": "2.0",
      "id": 2,
      "method": "tools/list",
      "params": {}
    }' \
    "${ENDPOINT_URL}/mcp" 2>&1 || true)

HTTP_CODE=$(echo "$TOOLS_RESPONSE" | tail -1)
BODY=$(echo "$TOOLS_RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ]; then
    TOOL_COUNT=$(echo "$BODY" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    tools = d.get('result', {}).get('tools', [])
    print(len(tools))
except:
    print('0')
" 2>/dev/null || echo "0")

    if [ "$TOOL_COUNT" -eq 21 ]; then
        log_pass "tools/list returned $TOOL_COUNT tools"
    else
        log_fail "tools/list returned $TOOL_COUNT tools, expected 21"
        log_info "Full response: $(echo "$BODY" | head -c 500)..."
        exit 1
    fi
elif [ "$HTTP_CODE" = "401" ]; then
    log_warn "tools/list returned 401 (Unauthorized)"
    log_fail "Cannot complete smoke test without authentication"
    exit 1
else
    log_fail "tools/list returned HTTP $HTTP_CODE"
    log_info "Full response: $BODY"
    exit 1
fi

echo ""

# ============================================================================
# Summary
# ============================================================================

log_pass "All smoke tests passed!"
log_info "Distillery MCP server is ready for production use."

exit 0
