# T12 Proof Summary — T03.2: ExpiringSoon component

## Task

T12: T03.2 — Create ExpiringSoon.svelte and ExpiryCard.svelte components for displaying entries expiring within 14 days.

## Artifacts

| File | Type | Status |
|------|------|--------|
| 12-01-test.txt | test | PASS |

## Results

### 12-01-test.txt — ExpiringSoon vitest suite

Command: `cd dashboard && npm test -- --run ExpiringSoon`

All 16 tests pass:

**Empty state (2 tests)**
- Shows empty state when no entries are expiring within 14 days
- Shows empty state with helpful hint text

**Display (7 tests)**
- Shows section heading
- Renders expiring entries within 14 days (excludes entries beyond 14 days)
- Shows days remaining for each entry
- Shows expiry date for each entry
- Sorts entries by days remaining ascending
- Handles entries array nested under 'entries' key
- Shows loading skeleton during fetch

**Error state (2 tests)**
- Shows error message when list call fails
- Shows error when bridge throws

**Action buttons (5 tests)**
- Renders Archive and Extend buttons for each entry
- Calls distillery_update with status=archived on archive click
- Calls distillery_update with expires_at=+30d on extend click
- Refreshes the list after a successful action
- Shows error message when archive action fails

## Implementation Notes

- `ExpiringSoon.svelte`: fetches entries via `distillery_list`, filters to `expires_at` within 14 days, sorts by days remaining ascending
- `ExpiryCard.svelte`: alert card with entry title, expiry date, days remaining badge, Archive and Extend action buttons
- `vitest.config.ts`: added `resolve.conditions: ['browser']` to enable Svelte 5 client-side rendering in jsdom tests
- `App.svelte`: integrated ExpiringSoon component into the home section
