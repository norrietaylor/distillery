<script lang="ts">
  /**
   * HealthOverview — Unit 3 of the Manage tab.
   *
   * Displays aggregate knowledge base metrics:
   *   - Row of MetricCards: Total, Active, Pending Review, Archived, Inbox
   *   - Pie chart: entries by type (list group_by=entry_type)
   *   - Bar chart: entries by status (list group_by=status)
   *   - Storage size in human-readable units
   *
   * Refreshes on refreshTick and on project change.
   */

  import MetricCard from "./MetricCard.svelte";
  import PieChart from "./PieChart.svelte";
  import BarChart from "./BarChart.svelte";
  import type { McpBridge } from "$lib/mcp-bridge";
  import { selectedProject, refreshTick } from "$lib/stores";

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge: McpBridge;
  }

  let { bridge }: Props = $props();

  // ── Metric card state ────────────────────────────────────────────────────

  let totalEntries = $state<number | null>(null);
  let activeCount = $state<number | null>(null);
  let pendingReviewCount = $state<number | null>(null);
  let archivedCount = $state<number | null>(null);
  let inboxCount = $state<number | null>(null);
  let storageBytes = $state<number | null>(null);

  let loadingMetrics = $state(false);
  let errorMetrics = $state<string | null>(null);

  // ── Stale-request guard ──────────────────────────────────────────────────
  let _loadToken = 0;

  // ── Chart state ──────────────────────────────────────────────────────────

  interface GroupItem {
    label: string;
    value: number;
    color: string;
  }

  let typeData = $state<GroupItem[]>([]);
  let statusData = $state<GroupItem[]>([]);

  let loadingTypeChart = $state(false);
  let loadingStatusChart = $state(false);
  let errorTypeChart = $state<string | null>(null);
  let errorStatusChart = $state<string | null>(null);

  // ── Color mapping ────────────────────────────────────────────────────────

  /**
   * Color-consistent type palette.
   * Same color for a given type across pie chart, bar chart, and elsewhere.
   */
  const TYPE_COLORS: Record<string, string> = {
    session: "#89b4fa",     // blue
    bookmark: "#94e2d5",    // teal
    minutes: "#a6e3a1",     // green
    meeting: "#fab387",     // peach
    reference: "#f9e2af",   // yellow
    idea: "#cba6f7",        // purple
    person: "#f38ba8",      // red
    project: "#89dceb",     // sky
    digest: "#74c7ec",      // sapphire
    github: "#b4befe",      // lavender
    feed: "#eba0ac",        // flamingo
    // Legacy key retained for backward-compat with existing data
    insight: "#cba6f7",     // purple/accent
  };

  const STATUS_COLORS: Record<string, string> = {
    active: "#a6e3a1",        // green
    pending_review: "#f9e2af", // yellow
    archived: "#a6adc8",       // muted
    inbox: "#cba6f7",          // purple
  };

  function typeColor(label: string): string {
    return TYPE_COLORS[label.toLowerCase()] ?? "#585b70";
  }

  function statusColor(label: string): string {
    return STATUS_COLORS[label.toLowerCase()] ?? "#585b70";
  }

  // ── Parsing helpers ──────────────────────────────────────────────────────

  /** Parse a stat count from tool response text. */
  function parseCount(text: string): number {
    const labelMatch = text.match(/(?:count|total)[:\s]+(\d+)/i);
    if (labelMatch) return parseInt(labelMatch[1]!, 10);
    const bareMatch = text.match(/^\s*(\d+)\s*$/m);
    if (bareMatch) return parseInt(bareMatch[1]!, 10);
    const firstNum = text.match(/\d+/);
    if (firstNum) return parseInt(firstNum[0]!, 10);
    return 0;
  }

  /**
   * Parse storage_bytes from a stats response.
   * The list(output=stats) response may include a "storage_bytes: N" or
   * "storage: N bytes" field.
   */
  function parseStorageBytes(text: string): number | null {
    const match = text.match(/storage(?:_bytes)?[:\s]+(\d+)/i);
    if (match) return parseInt(match[1]!, 10);
    return null;
  }

  /**
   * Parse group_by response — expects lines like:
   *   label: count
   * or JSON array [{ entry_type: "X", count: N }]
   */
  function parseGroupBy(text: string, keyField: string): Array<{ label: string; count: number }> {
    // Try JSON first
    try {
      const json = JSON.parse(text) as unknown;
      const arr = Array.isArray(json) ? (json as Record<string, unknown>[]) : [];
      if (arr.length > 0 && (keyField in arr[0]! || "count" in arr[0]!)) {
        return arr.map((item) => ({
          label: String(item[keyField] ?? item["label"] ?? "unknown"),
          count: Number(item["count"] ?? item["value"] ?? 0),
        }));
      }
    } catch {
      // Fall through to line-based parsing
    }

    // Line-based: "insight: 12" or "insight — 12" or "insight 12"
    const lines = text.split("\n");
    const result: Array<{ label: string; count: number }> = [];
    for (const line of lines) {
      const match = line.match(/^\s*([\w_-]+)\s*[:\-—\s]\s*(\d+)\s*$/);
      if (match) {
        result.push({ label: match[1]!, count: parseInt(match[2]!, 10) });
      }
    }
    return result;
  }

  // ── Fetch functions ──────────────────────────────────────────────────────

  /** Fetch summary metrics. Returns true if all four status counts were parsed. */
  async function fetchMetrics(project: string | null): Promise<boolean> {
    if (!bridge) return false;
    loadingMetrics = true;
    errorMetrics = null;
    try {
      const args: Record<string, unknown> = { output: "stats" };
      if (project) args.project = project;
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        errorMetrics = "Failed to load metrics";
        totalEntries = null;
        storageBytes = null;
        return false;
      }
      totalEntries = parseCount(result.text);
      storageBytes = parseStorageBytes(result.text);

      // Also parse per-status counts from stats response if present
      const activeMatch = result.text.match(/active[:\s]+(\d+)/i);
      if (activeMatch) activeCount = parseInt(activeMatch[1]!, 10);
      const pendingMatch = result.text.match(/pending_review[:\s]+(\d+)/i);
      if (pendingMatch) pendingReviewCount = parseInt(pendingMatch[1]!, 10);
      const archivedMatch = result.text.match(/archiv(?:ed)?[:\s]+(\d+)/i);
      if (archivedMatch) archivedCount = parseInt(archivedMatch[1]!, 10);
      const inboxMatch = result.text.match(/inbox[:\s]+(\d+)/i);
      if (inboxMatch) inboxCount = parseInt(inboxMatch[1]!, 10);

      return (
        activeMatch !== null &&
        pendingMatch !== null &&
        archivedMatch !== null &&
        inboxMatch !== null
      );
    } catch (err) {
      errorMetrics = err instanceof Error ? err.message : "Failed to load metrics";
      totalEntries = null;
      storageBytes = null;
      return false;
    } finally {
      loadingMetrics = false;
    }
  }

  /** Fetch individual status counts when stats doesn't include breakdown. */
  async function fetchStatusCounts(project: string | null) {
    if (!bridge) return;
    const statuses: Array<[string, (v: number | null) => void]> = [
      ["active", (v) => { activeCount = v; }],
      ["pending_review", (v) => { pendingReviewCount = v; }],
      ["archived", (v) => { archivedCount = v; }],
    ];
    const inboxArgs: Record<string, unknown> = { entry_type: "inbox", output: "stats" };
    if (project) inboxArgs.project = project;

    await Promise.all([
      ...statuses.map(async ([status, setter]) => {
        const args: Record<string, unknown> = { status, output: "stats" };
        if (project) args.project = project;
        try {
          const result = await bridge.callTool("distillery_list", args);
          setter(result.isError ? null : parseCount(result.text));
        } catch {
          setter(null);
        }
      }),
      (async () => {
        try {
          const result = await bridge.callTool("distillery_list", inboxArgs);
          inboxCount = result.isError ? null : parseCount(result.text);
        } catch {
          inboxCount = null;
        }
      })(),
    ]);
  }

  /** Fetch type distribution for pie chart. */
  async function fetchTypeChart(project: string | null) {
    if (!bridge) return;
    loadingTypeChart = true;
    errorTypeChart = null;
    try {
      const args: Record<string, unknown> = { group_by: "entry_type" };
      if (project) args.project = project;
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        errorTypeChart = "Failed to load type distribution";
        typeData = [];
        return;
      }
      const parsed = parseGroupBy(result.text, "entry_type");
      typeData = parsed.map((item) => ({
        label: item.label,
        value: item.count,
        color: typeColor(item.label),
      }));
    } catch (err) {
      errorTypeChart = err instanceof Error ? err.message : "Failed to load type chart";
      typeData = [];
    } finally {
      loadingTypeChart = false;
    }
  }

  /** Fetch status distribution for bar chart. */
  async function fetchStatusChart(project: string | null) {
    if (!bridge) return;
    loadingStatusChart = true;
    errorStatusChart = null;
    try {
      const args: Record<string, unknown> = { group_by: "status" };
      if (project) args.project = project;
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        errorStatusChart = "Failed to load status distribution";
        statusData = [];
        return;
      }
      const parsed = parseGroupBy(result.text, "status");
      statusData = parsed.map((item) => ({
        label: item.label,
        value: item.count,
        color: statusColor(item.label),
      }));
    } catch (err) {
      errorStatusChart = err instanceof Error ? err.message : "Failed to load status chart";
      statusData = [];
    } finally {
      loadingStatusChart = false;
    }
  }

  /** Refresh all health data. Uses a request token to discard stale results. */
  async function loadAll(project: string | null) {
    const token = ++_loadToken;

    const [statusCountsParsed] = await Promise.all([
      fetchMetrics(project),
      fetchTypeChart(project),
      fetchStatusChart(project),
    ]);

    // Guard: if a newer loadAll() has started, discard these results.
    if (token !== _loadToken) return;

    // Only call fetchStatusCounts as a fallback when fetchMetrics didn't
    // include all four status breakdowns.
    if (!statusCountsParsed) {
      await fetchStatusCounts(project);
      // Guard again after the fallback fetch.
      if (token !== _loadToken) return;
    }
  }

  // ── Storage formatting ───────────────────────────────────────────────────

  /**
   * Format bytes to human-readable string.
   * Returns "N KB", "N.N MB", or "N.N GB" as appropriate.
   */
  function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  const storageDisplay = $derived(
    storageBytes !== null ? formatBytes(storageBytes) : null,
  );

  // ── Reactive load ────────────────────────────────────────────────────────

  $effect(() => {
    const _tick = $refreshTick;
    const project = $selectedProject;
    void loadAll(project);
  });
</script>

<section class="health-overview" aria-label="Health overview">
  <!-- Metric cards row -->
  <div class="metrics-row">
    <MetricCard
      label="Total Entries"
      value={totalEntries}
      loading={loadingMetrics}
      error={errorMetrics}
    />
    <MetricCard
      label="Active"
      value={activeCount}
      loading={loadingMetrics}
      error={errorMetrics}
    />
    <MetricCard
      label="Pending Review"
      value={pendingReviewCount}
      loading={loadingMetrics}
      error={errorMetrics}
    />
    <MetricCard
      label="Archived"
      value={archivedCount}
      loading={loadingMetrics}
      error={errorMetrics}
    />
    <MetricCard
      label="Inbox"
      value={inboxCount}
      loading={loadingMetrics}
      error={errorMetrics}
    />
  </div>

  <!-- Storage size -->
  {#if storageDisplay !== null}
    <div class="storage-row" aria-label="Storage size">
      <span class="storage-label">Storage</span>
      <span class="storage-value">{storageDisplay}</span>
    </div>
  {/if}

  <!-- Charts row -->
  <div class="charts-row">
    <!-- Pie chart: entries by type -->
    <div class="chart-card">
      <h3 class="chart-title">Entries by Type</h3>
      {#if loadingTypeChart}
        <div class="chart-loading" aria-busy="true" aria-live="polite">Loading...</div>
      {:else if errorTypeChart}
        <div class="chart-error" role="alert">{errorTypeChart}</div>
      {:else}
        <PieChart
          data={typeData}
          ariaLabel="Pie chart of entries by type"
          width={220}
          height={220}
        />
      {/if}
    </div>

    <!-- Bar chart: entries by status -->
    <div class="chart-card chart-card--bar">
      <h3 class="chart-title">Entries by Status</h3>
      {#if loadingStatusChart}
        <div class="chart-loading" aria-busy="true" aria-live="polite">Loading...</div>
      {:else if errorStatusChart}
        <div class="chart-error" role="alert">{errorStatusChart}</div>
      {:else}
        <BarChart
          data={statusData}
          ariaLabel="Bar chart of entries by status"
          width={360}
          height={180}
        />
      {/if}
    </div>
  </div>
</section>

<style>
  .health-overview {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .metrics-row {
    display: flex;
    flex-direction: row;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  @media (max-width: 600px) {
    .metrics-row {
      flex-direction: column;
    }
  }

  .storage-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
  }

  .storage-label {
    color: var(--fg-muted, #a6adc8);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-size: 0.75rem;
  }

  .storage-value {
    color: var(--fg, #cdd6f4);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .charts-row {
    display: flex;
    flex-direction: row;
    gap: 1.5rem;
    flex-wrap: wrap;
    align-items: flex-start;
  }

  .chart-card {
    background: var(--card-bg, #181825);
    border: 1px solid var(--border, #313244);
    border-radius: 8px;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    flex: 0 0 auto;
  }

  .chart-card--bar {
    flex: 1;
    min-width: 280px;
  }

  .chart-title {
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--fg-muted, #a6adc8);
    margin: 0;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .chart-loading,
  .chart-error {
    font-size: 0.85rem;
    color: var(--fg-muted, #a6adc8);
    min-height: 80px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .chart-error {
    color: var(--error, #f38ba8);
  }
</style>
