---
name: tune
description: "Display and adjust feed relevance thresholds for alerts and digests"
allowed-tools:
  - "mcp__*__distillery_configure"
effort: low
model: haiku
---

<!-- Trigger phrases: tune, /tune, adjust thresholds, change alert threshold, set digest threshold, tune my feed, show thresholds -->

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
- `--alert` must be greater than or equal to `--digest`
- `--max` must be a positive integer
- `--reset` takes precedence over `--alert`/`--digest` if all provided
- If validation fails, display error and stop

### Step 3: Retrieve Current Configuration

Call `distillery_configure(action="get", section="feeds.thresholds")` and extract `alert` (default: 0.85) and `digest` (default: 0.60). If the call returns an error or the section is absent, show defaults and note live values could not be confirmed.

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

Apply each change via `distillery_configure`:

- For alert: `distillery_configure(section="feeds.thresholds", key="alert", value="<new_value>")`
- For digest: `distillery_configure(section="feeds.thresholds", key="digest", value="<new_value>")`

**Important:** When both thresholds change, determine the correct order to satisfy the `alert >= digest` constraint:
- If both new values are **higher** than current: set `alert` first (raises the ceiling before the floor)
- If both new values are **lower** than current: set `digest` first (lowers the floor before the ceiling)
- If only one changes: apply that change directly

If the user passes `--max`, inform them that `max_items_per_poll` is not yet configurable at runtime and skip that change.

If `distillery_configure` returns an error, display the error message and stop. Do not proceed with remaining changes if an earlier one fails.

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

**After changes or reset:** Same table with Previous/New columns sourced from `distillery_configure` response (`previous_value` and `new_value` fields). Include a confirmation line:

```text
Changes applied at runtime and persisted to distillery.yaml.
```

If `disk_written` is false in the response, instead show: "Changes applied in memory only — no config file found to persist to disk."

**Tuning guide** (always include):

```
Tuning Guide:
- Raise alert threshold to reduce noise (fewer high-priority alerts)
- Lower digest threshold to capture more items in the digest
- Alert must always be higher than digest
- Defaults: alert=0.85, digest=0.60
```

## Rules

- Always call `distillery_configure(action="get", section="feeds.thresholds")` first to verify MCP availability and retrieve current thresholds
- In read-only mode, display thresholds without confirmation
- Validate `--alert` >= `--digest` before applying; reject invalid combinations
- Always ask for confirmation before applying changes
- Use `distillery_configure` to apply changes at runtime — no manual YAML editing required
- When both alert and digest change, order calls to avoid constraint violations (alert first when raising, digest first when lowering)
- On MCP errors, see CONVENTIONS.md error handling -- display and stop
- Always include the tuning guide after displaying thresholds
