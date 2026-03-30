---
name: tune
description: "Displays and adjusts Distillery feed relevance thresholds. Triggered by: 'tune', '/tune', 'adjust thresholds', 'change alert threshold', 'set digest threshold', 'tune my feed', 'show thresholds'."
---

# Tune -- Feed Relevance Threshold Management

Displays and adjusts the `alert` threshold (high-priority items) and `digest` threshold (regular digest inclusion) used when scoring incoming feed items.

## When to Use

- See current thresholds (`/tune`)
- Adjust alert or digest thresholds (`/tune --alert 0.90 --digest 0.50`)
- Triggered by "show thresholds", "adjust my feed sensitivity", "tune my feed"

## Process

### Step 1: Check MCP

See CONVENTIONS.md -- skip if already confirmed this conversation.

### Step 2: Parse Arguments

| Flag | Description |
|------|-------------|
| `--alert N` | Set alert threshold (float in [0.0, 1.0]) |
| `--digest N` | Set digest threshold (float in [0.0, 1.0]) |
| `--max N` | Set max items per poll cycle (positive integer) |
| `--reset` | Reset to defaults (alert: 0.85, digest: 0.60) |

No flags = read-only mode (display current thresholds).

**Validation rules:**

- Both `--alert` and `--digest` must be floats in [0.0, 1.0]
- `--alert` must be greater than `--digest`
- `--max` must be a positive integer
- `--reset` takes precedence over `--alert`/`--digest` if all provided
- If validation fails, display error and stop

### Step 3: Retrieve Current Configuration

Call `distillery_status` and extract `feeds.thresholds.alert` (default: 0.85) and `feeds.thresholds.digest` (default: 0.60). If feeds config is absent, show defaults and note live values could not be confirmed.

### Step 4: Apply Changes (if flags provided)

If `--reset`, target defaults (alert: 0.85, digest: 0.60; max unchanged).

Preview changes and ask for confirmation:

```
Proposed threshold changes:
  Alert:  <current> -> <new>
  Digest: <current> -> <new>
  Max items per poll: <current> -> <new>   (if --max provided)

Apply these changes? (yes/no)
```

If declined, display "No changes made." and stop.

Since thresholds live in `distillery.yaml`, provide the exact YAML snippet to update:

```
feeds:
  thresholds:
    alert: <new_alert_value>
    digest: <new_digest_value>
  max_items_per_poll: <new_max_value>   # if --max provided
```

Include the full path to `distillery.yaml` if determinable. The MCP server must be restarted for changes to take effect.

### Step 5: Display Results

**Read-only mode:**

```
Feed Relevance Thresholds

| Threshold | Value | Meaning |
|-----------|-------|---------|
| Alert     | 0.85  | Items at or above this score trigger an immediate alert |
| Digest    | 0.60  | Items at or above this score (but below alert) are included in the digest |

Items below the digest threshold (< 0.60) are discarded.
To adjust: /tune --alert <value> --digest <value>
```

**After changes or reset:** Same table with Previous/New columns. Include "Update distillery.yaml to persist these thresholds across restarts."

**Tuning guide** (always include):

```
Tuning Guide:
- Raise alert threshold to reduce noise (fewer high-priority alerts)
- Lower digest threshold to capture more items in the digest
- Alert must always be higher than digest
- Defaults: alert=0.85, digest=0.60
```

## Rules

- Always call `distillery_status` first to verify MCP availability
- In read-only mode, display thresholds without confirmation
- Validate `--alert` > `--digest` before applying; reject invalid combinations
- Always ask for confirmation before applying changes
- Changes to `distillery.yaml` are the user's responsibility; provide exact YAML
- On MCP errors, see CONVENTIONS.md error handling -- display and stop
- Always include the tuning guide after displaying thresholds
