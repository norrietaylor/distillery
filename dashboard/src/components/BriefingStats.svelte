<script lang="ts">
  /**
   * BriefingStats — the morning briefing header row.
   *
   * Displays 5 metric cards populated via MCP tool calls:
   *   1. Total Entries    — list(output="stats")
   *   2. Stale (30d)      — list(stale_days=30, output="stats")
   *   3. Expiring Soon    — list() filtered to expires_at within 14 days
   *   4. Pending Review   — list(status="pending_review", output="stats")
   *   5. Inbox            — list(entry_type="inbox", output="stats")
   *
   * Color coding:
   *   - Pending Review > 10 → danger (red)
   *   - Stale > 50          → warning (yellow)
   */

  import MetricCard from "./MetricCard.svelte";
  import type { McpBridge } from "$lib/mcp-bridge";
  import { selectedProject, refreshTick } from "$lib/stores";

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge: McpBridge;
  }

  let { bridge }: Props = $props();

  // Metric state
  let totalEntries = $state<number | null>(null);
  let staleCount = $state<number | null>(null);
  let expiringSoon = $state<number | null>(null);
  let pendingReview = $state<number | null>(null);
  let inboxCount = $state<number | null>(null);

  // Loading/error state per card
  let loadingTotal = $state(false);
  let loadingStale = $state(false);
  let loadingExpiring = $state(false);
  let loadingPending = $state(false);
  let loadingInbox = $state(false);

  let errorTotal = $state<string | null>(null);
  let errorStale = $state<string | null>(null);
  let errorExpiring = $state<string | null>(null);
  let errorPending = $state<string | null>(null);
  let errorInbox = $state<string | null>(null);

  /**
   * Shape of the ``distillery_list {output: "stats"}`` response.
   *
   * The server returns::
   *
   *     {"entries_by_type":   {"session": 12, "bookmark": 5, "inbox": 3, ...},
   *      "entries_by_status": {"active": 42, "pending_review": 7, ...},
   *      "total_entries":     N,
   *      "storage_bytes":     N}
   *
   * All three cards that this component previously fetched in separate
   * `distillery_list` calls — total, pending review, inbox — are
   * fully determined by a single stats payload. We collapse them into
   * one call both to halve the network round-trips and to stay under
   * the 60 req/min HTTP rate limit during auto-refresh.
   */
  interface StatsPayload {
    entries_by_type?: Record<string, number>;
    entries_by_status?: Record<string, number>;
    total_entries?: number;
    storage_bytes?: number;
  }

  function parseStats(text: string): StatsPayload | null {
    try {
      const parsed = JSON.parse(text) as StatsPayload;
      if (parsed && typeof parsed === "object") {
        return parsed;
      }
    } catch {
      // Non-JSON response — treat as empty so each card can show 0 / 0 / 0
      // rather than propagating the parse error to every consumer.
    }
    return null;
  }

  /**
   * Fetch total/pending/inbox counts in a single ``distillery_list
   * {output: "stats"}`` call and populate all three state variables.
   *
   * This used to be three separate fetches (`fetchTotal`, `fetchPending`,
   * `fetchInbox`) — but `entries_by_status.pending_review` and
   * `entries_by_type.inbox` are already in the same stats payload as
   * `total_entries`, so asking the server three times is wasteful and
   * historically pushed us past the 60 req/min rate limit during
   * auto-refresh. Any error from the single call marks all three
   * cards as errored; a successful call with missing sub-keys
   * populates each card with 0 rather than null so the UI stays
   * numeric.
   */
  async function fetchPrimaryStats(project: string | null) {
    loadingTotal = true;
    loadingPending = true;
    loadingInbox = true;
    errorTotal = null;
    errorPending = null;
    errorInbox = null;
    try {
      const args: Record<string, unknown> = { output: "stats" };
      if (project) args.project = project;
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        const msg = "Failed to load entry stats";
        errorTotal = msg;
        errorPending = msg;
        errorInbox = msg;
        totalEntries = null;
        pendingReview = null;
        inboxCount = null;
        return;
      }
      const stats = parseStats(result.text);
      if (stats === null) {
        const msg = "Malformed stats response";
        errorTotal = msg;
        errorPending = msg;
        errorInbox = msg;
        totalEntries = null;
        pendingReview = null;
        inboxCount = null;
        return;
      }
      totalEntries = typeof stats.total_entries === "number" ? stats.total_entries : 0;
      pendingReview = stats.entries_by_status?.pending_review ?? 0;
      inboxCount = stats.entries_by_type?.inbox ?? 0;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load entry stats";
      errorTotal = msg;
      errorPending = msg;
      errorInbox = msg;
      totalEntries = null;
      pendingReview = null;
      inboxCount = null;
    } finally {
      loadingTotal = false;
      loadingPending = false;
      loadingInbox = false;
    }
  }

  /**
   * Fetch stale entries count (30 days).
   *
   * This needs its own call because ``stale_days`` is a SQL WHERE
   * predicate that constrains which entries the stats aggregation
   * sees — it can't be derived from the primary stats payload.
   */
  async function fetchStale(project: string | null) {
    loadingStale = true;
    errorStale = null;
    try {
      const args: Record<string, unknown> = { stale_days: 30, output: "stats" };
      if (project) args.project = project;
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        errorStale = "Failed to load stale count";
        staleCount = null;
      } else {
        const stats = parseStats(result.text);
        staleCount = stats !== null && typeof stats.total_entries === "number"
          ? stats.total_entries
          : 0;
      }
    } catch (err) {
      errorStale = err instanceof Error ? err.message : "Failed to load stale count";
      staleCount = null;
    } finally {
      loadingStale = false;
    }
  }

  /** Fetch entries expiring within the next 14 days. */
  async function fetchExpiring(project: string | null) {
    loadingExpiring = true;
    errorExpiring = null;
    try {
      const args: Record<string, unknown> = { limit: 100 };
      if (project) args.project = project;
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        errorExpiring = "Failed to load expiring count";
        expiringSoon = null;
        return;
      }
      const now = Date.now();
      const fourteenDays = 14 * 24 * 60 * 60 * 1000;
      const cutoff = now + fourteenDays;

      // Try JSON-first parsing (same approach as ExpiringSoon.svelte)
      let count: number | null = null;
      try {
        const data = JSON.parse(result.text) as unknown;
        const entries: Array<{ expires_at?: string }> = Array.isArray(data)
          ? (data as Array<{ expires_at?: string }>)
          : Array.isArray((data as { entries?: unknown }).entries)
            ? ((data as { entries: Array<{ expires_at?: string }> }).entries)
            : [];
        count = entries.filter((e) => {
          if (!e.expires_at) return false;
          const t = new Date(e.expires_at).getTime();
          return !isNaN(t) && t > now && t <= cutoff;
        }).length;
      } catch {
        // Fall back to regex matching on response text
        let regexCount = 0;
        const expiryMatches = result.text.matchAll(
          /expires_at[:\s]+(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}[^\s,\n]*)/gi,
        );
        for (const match of expiryMatches) {
          const t = new Date(match[1]!).getTime();
          if (!isNaN(t) && t > now && t <= cutoff) {
            regexCount++;
          }
        }
        count = regexCount;
      }
      expiringSoon = count;
    } catch (err) {
      errorExpiring = err instanceof Error ? err.message : "Failed to load expiring count";
      expiringSoon = null;
    } finally {
      loadingExpiring = false;
    }
  }

  /**
   * Load all metrics in parallel.
   *
   * Three tool calls instead of the original five: one primary stats
   * call that feeds total/pending/inbox, plus separate calls for
   * stale (which needs the ``stale_days`` filter) and expiring
   * (which fetches actual entries to inspect ``expires_at`` locally,
   * since there's no server-side ``expires_before`` filter yet).
   */
  async function loadAll(project: string | null) {
    await Promise.all([
      fetchPrimaryStats(project),
      fetchStale(project),
      fetchExpiring(project),
    ]);
  }

  // Derive color coding variants
  const pendingVariant = $derived(
    pendingReview !== null && pendingReview > 10 ? "danger" : "default"
  );
  const staleVariant = $derived(
    staleCount !== null && staleCount > 50 ? "warning" : "default"
  );

  // Reload on refresh tick or project change
  $effect(() => {
    // Depend on refresh tick and selected project
    const _tick = $refreshTick;
    const project = $selectedProject;
    void loadAll(project);
  });
</script>

<section class="briefing-stats" aria-label="Knowledge base metrics">
  <MetricCard
    label="Total Entries"
    value={totalEntries}
    loading={loadingTotal}
    error={errorTotal}
  />
  <MetricCard
    label="Stale (30d)"
    value={staleCount}
    variant={staleVariant}
    loading={loadingStale}
    error={errorStale}
  />
  <MetricCard
    label="Expiring Soon"
    value={expiringSoon}
    loading={loadingExpiring}
    error={errorExpiring}
  />
  <MetricCard
    label="Pending Review"
    value={pendingReview}
    variant={pendingVariant}
    loading={loadingPending}
    error={errorPending}
  />
  <MetricCard
    label="Inbox"
    value={inboxCount}
    loading={loadingInbox}
    error={errorInbox}
  />
</section>

<style>
  .briefing-stats {
    display: flex;
    flex-direction: row;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  /* At narrow viewports, let cards wrap gracefully */
  @media (max-width: 600px) {
    .briefing-stats {
      flex-direction: column;
    }
  }
</style>
