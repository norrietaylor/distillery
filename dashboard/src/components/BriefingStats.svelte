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

  import { onMount } from "svelte";
  import MetricCard from "./MetricCard.svelte";
  import { McpBridge } from "$lib/mcp-bridge";
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

  /** Parse a stat count from tool response text. Expects "N" or "total: N" or "count: N" format. */
  function parseCount(text: string): number {
    // Try "count: N" or "total: N"
    const labelMatch = text.match(/(?:count|total)[:\s]+(\d+)/i);
    if (labelMatch) return parseInt(labelMatch[1]!, 10);
    // Try a bare number on its own line
    const bareMatch = text.match(/^\s*(\d+)\s*$/m);
    if (bareMatch) return parseInt(bareMatch[1]!, 10);
    // Try the first number in the response
    const firstNum = text.match(/\d+/);
    if (firstNum) return parseInt(firstNum[0]!, 10);
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
        totalEntries = parseCount(result.text);
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
        staleCount = parseCount(result.text);
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
      // Count entries with expires_at within 14 days
      // Response text contains entries; look for expires_at fields
      const now = Date.now();
      const fourteenDays = 14 * 24 * 60 * 60 * 1000;
      const cutoff = now + fourteenDays;
      let count = 0;
      // Match ISO dates following "expires_at" label
      const expiryMatches = result.text.matchAll(/expires_at[:\s]+(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}[^\s,\n]*)/gi);
      for (const match of expiryMatches) {
        const expiryDate = new Date(match[1]!);
        if (!isNaN(expiryDate.getTime()) && expiryDate.getTime() > now && expiryDate.getTime() <= cutoff) {
          count++;
        }
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
        pendingReview = parseCount(result.text);
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
        inboxCount = parseCount(result.text);
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
