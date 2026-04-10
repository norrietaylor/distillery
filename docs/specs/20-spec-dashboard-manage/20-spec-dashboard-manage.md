# 20-spec-dashboard-manage

## Introduction/Overview

Phase 4 of the Distillery Dashboard adds the Manage tab — curator and admin functions for inbox triage, review queue management, system health monitoring, and feed source health. It provides batch classification of inbox entries with inline type/confidence controls, a review queue for approving or reclassifying low-confidence entries, aggregate health charts showing knowledge base composition, and a source health table showing poll status and error rates. This is the final dashboard tab, completing the 4-tab application.

## Goals

1. **Enable inbox triage** — classify untyped inbox entries individually or in batch with type selection and confidence scoring
2. **Provide review queue management** — approve, reclassify, or archive entries flagged as pending review with classification metadata visibility
3. **Display system health** — entry counts by type/status as charts, storage size, and activity trends
4. **Show feed source health** — last poll time, items stored, error counts, and status indicators for each source

## User Stories

- As a **curator**, I want to classify inbox entries by type so that new feed items and imports are properly categorized and searchable
- As a **curator**, I want to review low-confidence classifications so that I can approve correct ones and reclassify incorrect ones before they pollute search results
- As an **operator**, I want to see knowledge base health metrics (entries by type, by status, storage size) so that I can monitor growth and identify imbalances
- As an **operator**, I want to see feed source health (last poll, errors) so that I can identify broken or stale sources

## Demoable Units of Work

### Unit 1: Inbox Triage

**Purpose:** Classify untyped inbox entries individually or in batch, moving them from inbox status to properly typed active entries or to the review queue.

**Functional Requirements:**

- The system shall display an "Inbox" section with a DataTable populated by calling `list(entry_type="inbox", status="active", project={{ project_filter }}, limit=50)`
- The system shall display columns: Preview (first 80 chars of content), Source, Created Date, Tags, Actions
- The system shall provide per-row actions:
  - **Classify** — expands an inline form below the row with: type selector (all entry types except "inbox"), confidence slider (0.0–1.0, step 0.05, default 0.7), reasoning text input, and "Apply" button
  - **Investigate** — navigates to the Explore tab with the entry loaded in the detail panel
  - **Archive** — calls `resolve_review(entry_id=<id>, action="archive", reviewer={{ user }})` with confirmation
- The system shall call `classify(entry_id=<id>, entry_type={{ classify_type }}, confidence={{ classify_confidence }}, reasoning={{ classify_reasoning }})` when "Apply" is clicked
- The system shall remove the row from the table on successful classification (entry is no longer type "inbox")
- The system shall display a success toast showing the assigned type and whether the entry went to active or pending_review (based on confidence threshold)
- The system shall support batch mode: checkbox selection column, "Classify all as..." dropdown above the table that applies the selected type with default confidence (0.7) to all checked entries
- The system shall process batch classifications sequentially, showing a progress indicator ("Classifying 3 of 12...")
- The system shall display the inbox count as a badge on the Manage tab navigation item, refreshed on the global auto-refresh interval
- The system shall show an empty state "Inbox is empty. New feed items and imports will appear here." when no inbox entries exist

**Proof Artifacts:**

- Test: `dashboard/src/components/InboxTriage.test.ts` passes — covers table rendering, inline classify form, confidence slider, apply action, row removal, batch mode, progress indicator, archive action, empty state
- Screenshot: Inbox triage showing entries with expanded inline classification form and batch selection checkboxes

---

### Unit 2: Review Queue

**Purpose:** Manage entries flagged as pending_review — approve correct classifications, reclassify incorrect ones, or archive irrelevant entries.

**Functional Requirements:**

- The system shall display a "Review Queue" section with a DataTable populated by calling `list(status="pending_review", project={{ project_filter }}, limit=50)`
- The system shall display columns: Preview (first 80 chars), Type (current assigned type), Confidence, Classified At, Actions
- The system shall display Confidence as a colored badge: red (<0.4), yellow (0.4–0.7), green (>0.7)
- The system shall support row expansion to show classification metadata: confidence score, classification reasoning, classified_at timestamp, and suggested_project (if any)
- The system shall provide per-row actions:
  - **Approve** — calls `resolve_review(entry_id=<id>, action="approve", reviewer={{ user }})`, removes row from table, shows success toast
  - **Reclassify** — expands an inline type selector; on submit calls `resolve_review(entry_id=<id>, action="reclassify", new_entry_type={{ selected_type }}, reviewer={{ user }})`, removes row, shows toast
  - **Archive** — calls `resolve_review(entry_id=<id>, action="archive", reviewer={{ user }})` with confirmation, removes row
- The system shall support batch approve: checkbox selection + "Approve all selected" button above the table
- The system shall process batch approvals sequentially with a progress indicator
- The system shall display the pending review count as a badge on the Manage tab navigation item (combined with inbox count or separate)
- The system shall show an empty state "No entries pending review." when the queue is empty

**Proof Artifacts:**

- Test: `dashboard/src/components/ReviewQueue.test.ts` passes — covers table rendering, confidence badge colors, row expansion with metadata, approve/reclassify/archive actions, batch approve, empty state
- Screenshot: Review queue showing entries with confidence badges, expanded metadata, and reclassify inline form

---

### Unit 3: Health Overview

**Purpose:** Display aggregate knowledge base metrics and composition charts for operator visibility.

**Functional Requirements:**

- The system shall display a "Health" section with a row of metric cards: Total Entries, Active, Pending Review, Archived, Inbox
- The system shall populate metrics by calling `list(output="stats", project={{ project_filter }})`
- The system shall display a pie chart showing entries by type, populated by calling `list(group_by="entry_type", project={{ project_filter }})`
- The system shall display a bar chart showing entries by status, populated by calling `list(group_by="status", project={{ project_filter }})`
- The system shall display storage size (from `output="stats"` response) formatted in human-readable units (KB, MB, GB)
- The system shall refresh all health data on the auto-refresh interval and on manual refresh
- The system shall handle the case where the knowledge base is empty (zero entries) with appropriate empty-state charts (not errors)
- The system shall use color-consistent type/status mapping across charts (same color for "session" type in pie chart and elsewhere)

**Proof Artifacts:**

- Test: `dashboard/src/components/HealthOverview.test.ts` passes — covers metric cards, pie chart data, bar chart data, storage display, refresh, empty KB state
- Screenshot: Health overview showing metric cards, pie chart of entry types, and bar chart of entry statuses

---

### Unit 4: Source Health

**Purpose:** Display feed source operational status — last poll time, items stored, error counts — so operators can identify broken or stale sources.

**Functional Requirements:**

- The system shall display a "Source Health" DataTable populated by calling `watch(action="list")`
- The system shall display columns: Source (URL), Type (RSS/GitHub badge), Label, Last Poll, Items Stored, Errors, Status
- The system shall derive the Status column from last poll time relative to the configured poll interval:
  - **Green** ("Healthy"): polled within the interval
  - **Yellow** ("Overdue"): last poll older than 1.5x the interval
  - **Red** ("Error"): last poll had errors, or older than 3x the interval
  - **Gray** ("Never polled"): no poll recorded
- The system shall display Last Poll as a relative time ("5 minutes ago", "2 hours ago", "3 days ago")
- The system shall support row expansion showing: full URL, trust weight, poll interval, added date, and last poll timestamp (absolute)
- The system shall provide a "Remove" action in the expanded row that calls `watch(action="remove", url={{ source_url }})` with confirmation
- The system shall refresh source health data on the auto-refresh interval
- The system shall show an empty state "No feed sources configured. Add sources in the Capture tab." with a link/button to navigate to the Capture tab

**Proof Artifacts:**

- Test: `dashboard/src/components/SourceHealth.test.ts` passes — covers table rendering, status derivation (all 4 states), relative time display, row expansion, remove action, empty state with navigation
- Screenshot: Source health table showing sources with green/yellow/red status badges and expanded detail row

## Non-Goals (Out of Scope)

- **Admin settings panel** (configure thresholds, manage users, API keys) — deferred to a future admin-specific spec
- **Audit trail / operation history** — the `distillery metrics --scope audit` CLI covers this; no dashboard equivalent in this phase
- **Embedding budget display** — `distillery metrics --scope budget` is an operator CLI concern, not a dashboard feature
- **Manual poll trigger** from the dashboard — polls run on cron via webhooks
- **User/role management** — OAuth provides identity; role assignment is a server-side concern
- **Real-time WebSocket updates** — polling-based refresh only

## Design Considerations

- **Sub-navigation within Manage tab**: Inbox Triage and Review Queue are the primary views (most frequent use). Health Overview and Source Health are secondary. Use internal tabs or an accordion layout:
  ```
  [Inbox] [Review] [Health] [Sources]
  ```
- **Badge counts** on sub-tabs: Inbox count on "Inbox" sub-tab, pending review count on "Review" sub-tab. These update on auto-refresh.
- **Inline forms** for classify and reclassify expand below the row, pushing other rows down. Only one inline form open at a time.
- **Charts** should be simple and readable at a glance. Use a lightweight charting library compatible with Svelte (e.g., Chart.js via svelte-chartjs, or Layercake).
- **Batch operations** show a progress bar/counter. If any item fails, continue processing and report failures at the end.

## Repository Standards

- **Svelte components** follow the naming convention from Phase 1 scaffold
- **TypeScript strict mode** for all dashboard code
- **vitest** for component tests
- **Conventional Commits**: `feat(dashboard): ...`
- All MCP tool calls go through the `callTool()` bridge established in spec-17 Unit 1

## Technical Considerations

- **Charting library**: Need a Svelte-compatible charting solution. Options: Layercake (Svelte-native, SVG-based, lightweight), Chart.js via svelte-chartjs wrapper, or raw SVG. Layercake is recommended for Svelte alignment and bundle size.
- **Batch processing**: Sequential `classify` or `resolve_review` calls, not parallel, to avoid rate limiting. Each call updates progress state. Failures are collected and displayed as a summary toast at the end.
- **Status derivation**: Source health status is computed client-side from `last_poll_at` and `poll_interval_minutes` fields on the source object. If these fields aren't in the current `watch(action="list")` response, the MCP server may need to include them (check spec-16 `watch` tool returns).
- **Tab badge counts**: Run lightweight `list(output="stats", entry_type="inbox")` and `list(output="stats", status="pending_review")` calls on the global auto-refresh to update badge numbers without loading full entry lists.
- **Depends on spec-17**: Requires dashboard scaffold, MCP Apps bridge, nav shell, auto-refresh.
- **Depends on spec-16**: Uses `list(output="stats")`, `list(group_by="entry_type")`, `list(group_by="status")` from API consolidation.

## Security Considerations

- **Reviewer identity**: All `resolve_review` calls pass `reviewer={{ user }}` from OAuth identity for audit trail.
- **Role gating**: The Manage tab should be accessible to curator and admin roles only. Developer role sees a "You don't have access to this tab" message. Role check uses the `user_role` state set during auth.
- **Batch operations**: No additional auth check per item — if the user can access the Manage tab, they can classify/approve any entry in their project scope.

## Success Metrics

- Inbox triage (single entry): classify action completes within 2 seconds
- Batch classify (10 entries): completes within 15 seconds with progress indicator
- Review queue loads within 2 seconds for up to 50 entries
- Health charts render within 3 seconds
- Component test suite passes with ≥80% coverage

## Open Questions

1. **`watch(action="list")` response fields** — does the current response include `last_poll_at`, `items_stored`, and `error_count`? If not, the source health table will need the MCP server to add these fields.
