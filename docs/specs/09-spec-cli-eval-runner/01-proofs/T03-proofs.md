# T03 Proof Artifacts: CI Workflow Update

## Summary
Updated `.github/workflows/eval-nightly.yml` to use Claude Code CLI with `CLAUDE_CODE_OAUTH_TOKEN` instead of Anthropic SDK with `ANTHROPIC_API_KEY`.

## Proof Results

| Proof ID | Type | Description | Status | File |
|----------|------|-------------|--------|------|
| T03-01 | file | Node.js setup and Claude CLI install | PASS | T03-01-file.txt |
| T03-02 | file | CLAUDE_CODE_OAUTH_TOKEN and telemetry flag | PASS | T03-02-file.txt |
| T03-03 | file | ANTHROPIC_API_KEY removed | PASS | T03-03-file.txt |
| T03-04 | file | pyproject.toml eval extras clean | PASS | T03-04-file.txt |
| T03-05 | file | pip install uses [dev] only | PASS | T03-05-file.txt |

## Changes Made

1. Added Node.js setup step (actions/setup-node@v4 with node-version: "20")
2. Added Claude Code CLI installation step (npm install -g @anthropic-ai/claude-code)
3. Removed ANTHROPIC_API_KEY environment variable
4. Added CLAUDE_CODE_OAUTH_TOKEN and CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC environment variables
5. Updated pip install to use `.[dev]` only (removed eval extra)

## Verification

All functional requirements from spec section 3 (Unit 3: CI Workflow Update) satisfied:
- ✅ Node.js setup added
- ✅ Claude CLI installed via npm
- ✅ CLAUDE_CODE_OAUTH_TOKEN set in env
- ✅ ANTHROPIC_API_KEY removed
- ✅ pip install drops eval extra
- ✅ CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC set
- ✅ pytest -m eval command unchanged
- ✅ eval results upload unchanged
