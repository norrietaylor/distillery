# /tune — Feed Relevance Thresholds

Displays and adjusts the alert and digest thresholds that control which feed entries surface in your digest.

## Usage

```text
/tune                           # Display current thresholds (read-only)
/tune --alert 0.90              # Set alert threshold
/tune --digest 0.50             # Set digest threshold
/tune --alert 0.85 --digest 0.60  # Set both
```

**Trigger phrases:** "tune my feed", "adjust thresholds", "change alert threshold", "set digest threshold", "show thresholds"

## Thresholds

| Threshold | Default | Purpose |
|-----------|---------|---------|
| **Alert** | 0.85 | High-priority items flagged for immediate attention |
| **Digest** | 0.60 | Regular items included in the `/radar` digest |

Feed entries with relevance scores at or above the **alert** threshold are flagged as high-priority. Entries at or above the **digest** threshold (but below alert) are included in the regular digest. Entries below the digest threshold are stored but not surfaced.

## Options

| Option | Description |
|--------|-------------|
| `--alert <value>` | Set alert threshold (0.0-1.0) |
| `--digest <value>` | Set digest threshold (0.0-1.0) |

!!! note "Validation"
    The alert threshold must be greater than or equal to the digest threshold. Both values must be between 0.0 and 1.0.

## Output

### Read-Only Mode (no flags)

```text
## Feed Relevance Thresholds

| Threshold | Value | Meaning |
|-----------|-------|---------|
| Alert     | 0.85  | High-priority items flagged for attention |
| Digest    | 0.60  | Items included in /radar digest |

### Tuning Guide
- **Raise alert** if you're getting too many false high-priority items
- **Lower alert** if you're missing important updates
- **Raise digest** if the digest is too noisy
- **Lower digest** if you're missing relevant items
```

### After Adjustment

Shows a before/after comparison and provides the YAML snippet for `distillery.yaml`:

```yaml
thresholds:
  alert: 0.90
  digest: 0.50
```

!!! info
    After changing thresholds, the MCP server needs to be restarted for the changes to take effect if you update `distillery.yaml` directly.

## Tips

- Start with the defaults (alert: 0.85, digest: 0.60) and adjust based on your experience
- If the digest is overwhelming, raise the digest threshold
- If you're missing important updates, lower the alert threshold
- Changes are shown as a preview with confirmation before applying
