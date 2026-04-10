# T09 Proof Summary — T02.1: MetricCard component and BriefingStats layout

## Task

Create `MetricCard.svelte` (large number, label, color coding prop) and
`BriefingStats.svelte` (row of 5 cards populated via MCP tool calls).
Wire `BriefingStats` into `App.svelte`.

## Proof Artifacts

| # | File | Type | Status |
|---|------|------|--------|
| 1 | T09-01-file.txt | file | PASS |
| 2 | T09-02-cli.txt | cli | PASS |

## Summary

### Files Created

- `dashboard/src/components/MetricCard.svelte` (3020 bytes)
  - Props: `label`, `value`, `variant` ("default" | "warning" | "danger"), `loading`, `error`
  - Displays large number with label; skeleton when loading; dash when error
  - Variant drives color coding via CSS classes

- `dashboard/src/components/BriefingStats.svelte` (8288 bytes)
  - Renders row of 5 `MetricCard` components
  - Fetches data via `bridge.callTool("distillery_list", ...)`:
    - Total Entries: `output="stats"`
    - Stale (30d): `stale_days=30, output="stats"`
    - Expiring Soon: `limit=100` filtered by `expires_at` within 14 days
    - Pending Review: `status="pending_review", output="stats"`
    - Inbox: `entry_type="inbox", output="stats"`
  - Color coding: Pending Review > 10 → danger; Stale > 50 → warning
  - Subscribes to `$refreshTick` and `$selectedProject` stores

### Files Modified

- `dashboard/src/App.svelte`
  - Added `import BriefingStats from "./components/BriefingStats.svelte"`
  - Added `<BriefingStats {bridge} />` as first child of `.home-section`

### Build Verification

Production build (`npm run build`) passes with 276 modules (up from 256),
confirming both new components are included in the bundle.

## Requirements Coverage

| Requirement | Status |
|-------------|--------|
| R02.1: Display row of 5 metric cards | PASS |
| R02.2: Populate via MCP tool calls | PASS |
| R02.7: Refresh on auto-refresh and manual refresh | PASS |
| R02.8: Color coding thresholds | PASS |
