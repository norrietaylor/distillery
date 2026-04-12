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
   * Parse the ``total_entries`` field from a ``distillery_list`` stats payload.
   *
   * The server returns JSON of the form::
   *
   *     {"entries_by_type": {...}, "entries_by_status": {...},
   *      "total_entries": N, "storage_bytes": N}
   *
   * We pull ``total_entries`` directly rather than regex-scraping the text —
   * an earlier version of this component used ``/(?:count|total)[:\s]+(\d+)/``
   * which failed to match ``total_entries":N`` (the ``_entries":`` glue is not
   * whitespace or colon) and silently fell back to "first number in the
   * response", returning whichever entry type happened to serialize first
   * instead of the actual total.
   */
  function parseStatsTotal(text: string): number {
    try {
      const parsed = JSON.parse(text) as { total_entries?: unknown };
      if (typeof parsed.total_entries === "number") {
        return parsed.total_entries;
      }
    } catch {
      // Non-JSON response — return 0 so the card shows "0" instead of NaN.
    }
    return 0;
  }

  /** Fetch total entries count. */
  async function fetchTotal(project: string | null) {
    loadingTotal = true;
    errorTotal = null;
    try {
      const args: Record<string, unknown> = { output: "stats" };
      if (project) args.project = project;
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        errorTotal = "Failed to load total entries";
        totalEntries = null;
      } else {
        totalEntries = parseStatsTotal(result.text);
      }
    } catch (err) {
      errorTotal = err instanceof Error ? err.message : "Failed to load total entries";
      totalEntries = null;
    } finally {
      loadingTotal = false;
    }
  }

  /** Fetch stale entries count (30 days). */
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
        staleCount = parseStatsTotal(result.text);
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

  /** Fetch pending review count. */
  async function fetchPending(project: string | null) {
    loadingPending = true;
    errorPending = null;
    try {
      const args: Record<string, unknown> = { status: "pending_review", output: "stats" };
      if (project) args.project = project;
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        errorPending = "Failed to load pending review count";
        pendingReview = null;
      } else {
        pendingReview = parseStatsTotal(result.text);
      }
    } catch (err) {
      errorPending = err instanceof Error ? err.message : "Failed to load pending review count";
      pendingReview = null;
    } finally {
      loadingPending = false;
    }
  }

  /** Fetch inbox count. */
  async function fetchInbox(project: string | null) {
    loadingInbox = true;
    errorInbox = null;
    try {
      const args: Record<string, unknown> = { entry_type: "inbox", output: "stats" };
      if (project) args.project = project;
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        errorInbox = "Failed to load inbox count";
        inboxCount = null;
      } else {
        inboxCount = parseStatsTotal(result.text);
      }
    } catch (err) {
      errorInbox = err instanceof Error ? err.message : "Failed to load inbox count";
      inboxCount = null;
    } finally {
      loadingInbox = false;
    }
  }

  /** Load all metrics in parallel. */
  async function loadAll(project: string | null) {
    await Promise.all([
      fetchTotal(project),
      fetchStale(project),
      fetchExpiring(project),
      fetchPending(project),
      fetchInbox(project),
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
