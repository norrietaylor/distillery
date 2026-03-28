---
name: tune
description: "Displays and adjusts Distillery feed relevance thresholds. Triggered by: 'tune', '/tune', 'adjust thresholds', 'change alert threshold', 'set digest threshold', 'tune my feed', 'show thresholds'."
---

# Tune -- Feed Relevance Threshold Management

Tune displays and adjusts the relevance thresholds used when scoring incoming feed items: the `alert` threshold (for high-priority items) and the `digest` threshold (for items included in the regular digest).

## Prerequisites

- The Distillery MCP server must be configured in your Claude Code settings
- See docs/mcp-setup.md for setup instructions

If the server is not available, the skill will display a setup message with next steps.

## When to Use

- When you want to see the current relevance thresholds (`/tune`)
- When you want to raise or lower the alert threshold (`/tune --alert 0.90`)
- When you want to raise or lower the digest threshold (`/tune --digest 0.50`)
- When asked to "show thresholds", "adjust my feed sensitivity", or "tune my feed"

## Process

### Step 1: Check MCP Availability

Call `distillery_status` to confirm the Distillery MCP server is running.

If the tool is unavailable or returns an error, display:

```
Warning: Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

To set up the server:
1. Ensure Distillery is installed: https://github.com/norrie-distillery/distillery
2. Configure the server in your Claude Code settings: see docs/mcp-setup.md
3. Restart Claude Code or reload MCP servers

For detailed setup instructions, see: docs/mcp-setup.md
```

Stop here if MCP is unavailable.

### Step 2: Parse Arguments

Parse optional arguments from the invocation:

| Flag | Description |
|------|-------------|
| `--alert N` | Set the alert threshold to N (float in [0.0, 1.0]) |
| `--digest N` | Set the digest threshold to N (float in [0.0, 1.0]) |
| `--max N` | Set the maximum number of items per poll cycle to N (positive integer) |
| `--reset` | Reset all thresholds to their defaults (alert: 0.85, digest: 0.60) |

If no flags are provided, the skill displays the current thresholds (read-only mode).

**Validation rules:**

- Both `--alert` and `--digest` values must be floats in [0.0, 1.0]
- The `--alert` value must be greater than the `--digest` value (alert must be stricter than digest)
- The `--max` value must be a positive integer
- If validation fails, display an error and stop before making any changes

### Step 3: Retrieve Current Configuration

Call `distillery_status` to retrieve the current server configuration including threshold values:

```
distillery_status()
```

Extract the `feeds` configuration from the response, specifically:
- `feeds.thresholds.alert` — current alert threshold (default: 0.85)
- `feeds.thresholds.digest` — current digest threshold (default: 0.60)

If the status response does not include feeds configuration, fall back to displaying the documented defaults (0.85 and 0.60) and note that live values could not be confirmed.

### Step 4: Apply Changes (if flags provided)

If `--reset` was specified, set the target values to defaults:
- alert: 0.85
- digest: 0.60
- max: (unchanged, reset does not affect max)

Otherwise use the values from `--alert`, `--digest`, and/or `--max`.

If threshold changes are requested, display a preview and ask for confirmation:

```
Proposed threshold changes:
  Alert:  <current> -> <new>
  Digest: <current> -> <new>
  Max items per poll: <current> -> <new>   (shown only if --max was provided)

Apply these changes? (yes/no)
```

Wait for the user to confirm. If the user declines, display:

```
No changes made.
```

And stop here.

**Applying changes:**

Since Distillery thresholds are configured in `distillery.yaml`, inform the user of the required change:

```
To apply these thresholds, update the following section in distillery.yaml:

feeds:
  thresholds:
    alert: <new_alert_value>
    digest: <new_digest_value>
  max_items_per_poll: <new_max_value>   # include only if --max was provided

The MCP server must be restarted for changes to take effect.
```

Display the full path to distillery.yaml if it can be determined from the environment.

**Note:** There is no live write mechanism for thresholds. All changes must be persisted via `distillery.yaml` and require an MCP server restart to take effect.

### Step 5: Display Results

Display the current (or updated) thresholds using the Output Format below.

## Output Format

**Read-only mode (no flags provided):**

```
Feed Relevance Thresholds

| Threshold | Value | Meaning |
|-----------|-------|---------|
| Alert     | 0.85  | Items at or above this score trigger an immediate alert |
| Digest    | 0.60  | Items at or above this score (but below alert) are included in the digest |

Items below the digest threshold (< 0.60) are discarded.

To adjust: /tune --alert <value> --digest <value>
Defaults: alert=0.85, digest=0.60
```

**After changes are applied:**

```
Feed Relevance Thresholds (updated)

| Threshold | Previous | New   | Meaning |
|-----------|----------|-------|---------|
| Alert     | 0.85     | 0.90  | Items at or above this score trigger an immediate alert |
| Digest    | 0.60     | 0.55  | Items at or above this score (but below alert) are included in the digest |

Update distillery.yaml to persist these thresholds across restarts.
```

**After --reset:**

```
Feed Relevance Thresholds (reset to defaults)

| Threshold | Value | Meaning |
|-----------|-------|---------|
| Alert     | 0.85  | Items at or above this score trigger an immediate alert |
| Digest    | 0.60  | Items at or above this score (but below alert) are included in the digest |

Update distillery.yaml to persist these defaults across restarts.
```

**Guidance on threshold tuning:**

Always include a brief guidance note after displaying thresholds:

```
Tuning Guide:
- Raise alert threshold to reduce noise (fewer high-priority alerts)
- Lower digest threshold to capture more items in the digest
- Alert must always be higher than digest
- Defaults: alert=0.85, digest=0.60
```

## Rules

- Always call `distillery_status` first to verify MCP availability
- In read-only mode (no flags), display thresholds without asking for confirmation
- Validate that `--alert` > `--digest` before applying any changes; reject invalid combinations
- Both threshold values must be floats in [0.0, 1.0]; reject out-of-range values
- Always ask for confirmation before applying threshold changes
- Changes to `distillery.yaml` are the user's responsibility; provide the exact YAML snippet to add/update
- Always include the Tuning Guide note after displaying thresholds
- If `distillery_status` returns an error, display it clearly:

```
Error: <error message from MCP tool>

Suggested Action:
- If "Connection error" -> Verify the Distillery MCP server is running
- If "Database error" -> Ensure the database path is writable and the file exists
```

- Do not enter infinite retry loops -- if a call fails, report the error and stop
- The `--reset` flag takes precedence over `--alert` and `--digest` if all are provided
