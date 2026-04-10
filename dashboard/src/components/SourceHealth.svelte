<script lang="ts">
  /**
   * SourceHealth — Unit 4 of the Manage tab.
   *
   * Displays a DataTable of feed sources populated by watch(action="list").
   * Columns: Source (URL), Type (RSS/GitHub badge), Label, Last Poll, Items Stored, Errors, Status.
   *
   * Status is derived client-side from last_poll_at vs poll_interval_minutes:
   *   - Green ("Healthy"):      polled within the interval
   *   - Yellow ("Overdue"):     last poll older than 1.5x the interval
   *   - Red ("Error"):          errors present, or older than 3x the interval
   *   - Gray ("Never polled"): no poll recorded
   *
   * Row expansion shows full URL, trust weight, poll interval, added date, and
   * absolute last poll timestamp. A "Remove" action in the expanded row calls
   * watch(action="remove") with confirmation.
   *
   * Auto-refreshes on refreshTick and selectedProject changes.
   */

  import type { McpBridge } from "$lib/mcp-bridge";
  import { refreshTick, activeTab } from "$lib/stores";
  import LoadingSkeleton from "./LoadingSkeleton.svelte";

  interface Props {
    bridge: McpBridge;
  }

  let { bridge }: Props = $props();

  /** A single feed source as returned by watch(action="list"). */
  interface FeedSource {
    url: string;
    source_type: string;
    label: string;
    last_poll_at: string | null;
    items_stored: number;
    error_count: number;
    poll_interval_minutes: number;
    trust_weight: number;
    added_at: string;
    [key: string]: unknown;
  }

  type SourceStatus = "healthy" | "overdue" | "error" | "never";

  let sources = $state<FeedSource[]>([]);
  let loading = $state(false);
  let loadError = $state<string | null>(null);

  /** Which row is currently expanded (showing details). */
  let expandedRowId = $state<string | null>(null);

  /** Remove confirmation: url of source awaiting confirmation. */
  let removeConfirmUrl = $state<string | null>(null);
  let removeLoading = $state(false);

  /** Toast notification. */
  let toastMessage = $state<string | null>(null);
  let toastTimeout: ReturnType<typeof setTimeout> | null = null;

  function showToast(message: string) {
    if (toastTimeout) clearTimeout(toastTimeout);
    toastMessage = message;
    toastTimeout = setTimeout(() => {
      toastMessage = null;
    }, 4000);
  }

  /** Parse JSON response text into FeedSource array. */
  function parseSources(text: string): FeedSource[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed.map(normalizeSource);
      }
      if (parsed && typeof parsed === "object") {
        return [normalizeSource(parsed as Record<string, unknown>)];
      }
    } catch {
      // fall through to line-by-line parsing
    }
    const results: FeedSource[] = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const obj: unknown = JSON.parse(trimmed);
        if (obj && typeof obj === "object") {
          results.push(normalizeSource(obj as Record<string, unknown>));
        }
      } catch {
        // skip unparseable lines
      }
    }
    return results;
  }

  function normalizeSource(obj: Record<string, unknown>): FeedSource {
    const raw = obj as Partial<FeedSource>;
    return {
      ...obj,
      url: String(raw.url ?? ""),
      source_type: String(raw.source_type ?? raw["type"] ?? ""),
      label: String(raw.label ?? ""),
      last_poll_at: typeof raw.last_poll_at === "string" ? raw.last_poll_at : null,
      items_stored: typeof raw.items_stored === "number" ? raw.items_stored : 0,
      error_count: typeof raw.error_count === "number" ? raw.error_count : 0,
      poll_interval_minutes: typeof raw.poll_interval_minutes === "number"
        ? raw.poll_interval_minutes
        : 60,
      trust_weight: typeof raw.trust_weight === "number" ? raw.trust_weight : 1.0,
      added_at: String(raw.added_at ?? ""),
    };
  }

  async function loadSources() {
    if (!bridge?.isConnected) return;
    loading = true;
    loadError = null;
    try {
      const result = await bridge.callTool("distillery_watch", { action: "list" });
      if (result.isError) {
        loadError = result.text || "Failed to load sources";
        sources = [];
        return;
      }
      sources = parseSources(result.text);
    } catch (err) {
      loadError = err instanceof Error ? err.message : "Failed to load sources";
      sources = [];
    } finally {
      loading = false;
    }
  }

  // Reload on each refresh tick
  $effect(() => {
    const _tick = $refreshTick;
    void loadSources();
  });

  // ── Status derivation ────────────────────────────────────────────────────

  /**
   * Derive source status from last_poll_at, poll_interval_minutes, error_count.
   * - Gray:   never polled
   * - Green:  within interval
   * - Yellow: older than 1.5x interval
   * - Red:    errors present, or older than 3x interval
   */
  function deriveStatus(source: FeedSource): SourceStatus {
    if (!source.last_poll_at) return "never";
    if (source.error_count > 0) return "error";
    const intervalMs = source.poll_interval_minutes * 60 * 1000;
    const lastPoll = new Date(source.last_poll_at).getTime();
    const ageMs = Date.now() - lastPoll;
    if (ageMs > intervalMs * 3) return "error";
    if (ageMs > intervalMs * 1.5) return "overdue";
    return "healthy";
  }

  type StatusConfig = {
    label: string;
    tier: "green" | "yellow" | "red" | "gray";
  };

  function statusConfig(status: SourceStatus): StatusConfig {
    switch (status) {
      case "healthy": return { label: "Healthy", tier: "green" };
      case "overdue": return { label: "Overdue", tier: "yellow" };
      case "error":   return { label: "Error", tier: "red" };
      case "never":   return { label: "Never polled", tier: "gray" };
    }
  }

  // ── Relative time ────────────────────────────────────────────────────────

  /** Format an ISO date string as a relative time ("5 minutes ago"). */
  function relativeTime(iso: string | null): string {
    if (!iso) return "\u2014";
    try {
      const diffMs = Date.now() - new Date(iso).getTime();
      if (diffMs < 0) return "just now";
      const diffSec = Math.floor(diffMs / 1000);
      if (diffSec < 60) return `${diffSec} second${diffSec !== 1 ? "s" : ""} ago`;
      const diffMin = Math.floor(diffSec / 60);
      if (diffMin < 60) return `${diffMin} minute${diffMin !== 1 ? "s" : ""} ago`;
      const diffHr = Math.floor(diffMin / 60);
      if (diffHr < 24) return `${diffHr} hour${diffHr !== 1 ? "s" : ""} ago`;
      const diffDay = Math.floor(diffHr / 24);
      return `${diffDay} day${diffDay !== 1 ? "s" : ""} ago`;
    } catch {
      return iso;
    }
  }

  /** Format an ISO date to a readable absolute date. */
  function formatDate(iso: string): string {
    if (!iso) return "\u2014";
    try {
      return new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      }).format(new Date(iso));
    } catch {
      return iso;
    }
  }

  // ── Row interactions ─────────────────────────────────────────────────────

  function toggleRowExpand(url: string) {
    expandedRowId = expandedRowId === url ? null : url;
    // Close remove confirm if switching rows
    if (removeConfirmUrl !== url) {
      removeConfirmUrl = null;
    }
  }

  function confirmRemove(url: string) {
    removeConfirmUrl = url;
  }

  function cancelRemove() {
    removeConfirmUrl = null;
  }

  async function executeRemove(url: string) {
    removeLoading = true;
    try {
      const result = await bridge.callTool("distillery_watch", {
        action: "remove",
        url,
      });
      if (result.isError) {
        showToast(`Remove failed: ${result.text}`);
        return;
      }
      showToast("Source removed");
      sources = sources.filter((s) => s.url !== url);
      if (expandedRowId === url) expandedRowId = null;
    } catch (err) {
      showToast(`Remove failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      removeLoading = false;
      removeConfirmUrl = null;
    }
  }

  function navigateToCapture() {
    activeTab.set("capture");
  }
</script>

<section class="source-health" aria-labelledby="source-health-heading">
  <div class="section-header">
    <h2 id="source-health-heading" class="section-title">Source Health</h2>
  </div>

  {#if toastMessage}
    <div class="toast" role="status" aria-live="polite">
      {toastMessage}
    </div>
  {/if}

  {#if loading}
    <LoadingSkeleton rows={4} label="Loading feed sources..." />
  {:else if loadError}
    <div class="error-banner" role="alert">
      <strong>Error:</strong> {loadError}
    </div>
  {:else if sources.length === 0}
    <div class="empty-state" data-testid="empty-state">
      <p class="empty-state__text">No feed sources configured.</p>
      <button
        class="empty-state__link"
        onclick={navigateToCapture}
        aria-label="Go to Capture tab to add sources"
      >
        Add sources in the Capture tab
      </button>
    </div>
  {:else}
    <div class="datatable-scroll">
      <table class="datatable" aria-label="Feed source health">
        <thead>
          <tr>
            <th class="datatable-th">Source</th>
            <th class="datatable-th">Type</th>
            <th class="datatable-th">Label</th>
            <th class="datatable-th">Last Poll</th>
            <th class="datatable-th">Items Stored</th>
            <th class="datatable-th">Errors</th>
            <th class="datatable-th">Status</th>
          </tr>
        </thead>
        <tbody>
          {#each sources as source (source.url)}
            {@const status = deriveStatus(source)}
            {@const cfg = statusConfig(status)}
            {@const isExpanded = expandedRowId === source.url}

            <!-- Main row -->
            <tr
              class="datatable-row"
              class:datatable-row--expanded={isExpanded}
              aria-expanded={isExpanded}
            >
              <td class="datatable-td datatable-td--url">
                <button
                  class="expand-btn"
                  onclick={() => toggleRowExpand(source.url)}
                  aria-label="Toggle detail for source {source.url}"
                  data-testid="expand-btn-{source.url}"
                >
                  {source.url}
                </button>
              </td>
              <td class="datatable-td">
                <span
                  class="type-badge type-badge--{source.source_type.toLowerCase()}"
                  aria-label="Source type {source.source_type}"
                >
                  {source.source_type || "\u2014"}
                </span>
              </td>
              <td class="datatable-td">{source.label || "\u2014"}</td>
              <td class="datatable-td" data-testid="last-poll-{source.url}">
                {relativeTime(source.last_poll_at)}
              </td>
              <td class="datatable-td">{source.items_stored}</td>
              <td class="datatable-td">{source.error_count}</td>
              <td class="datatable-td">
                <span
                  class="status-badge status-badge--{cfg.tier}"
                  data-status={status}
                  aria-label="Status {cfg.label}"
                >
                  {cfg.label}
                </span>
              </td>
            </tr>

            <!-- Expanded detail row -->
            {#if isExpanded}
              <tr
                class="expanded-row"
                aria-label="Detail for source {source.url}"
              >
                <td colspan="7" class="expanded-td">
                  <div
                    class="detail-panel"
                    data-testid="detail-panel-{source.url}"
                  >
                    <dl class="detail-list">
                      <dt>Full URL</dt>
                      <dd class="detail-url">{source.url}</dd>
                      <dt>Trust Weight</dt>
                      <dd>{source.trust_weight}</dd>
                      <dt>Poll Interval</dt>
                      <dd>{source.poll_interval_minutes} minutes</dd>
                      <dt>Added</dt>
                      <dd>{formatDate(source.added_at)}</dd>
                      <dt>Last Poll (absolute)</dt>
                      <dd>{source.last_poll_at ?? "\u2014"}</dd>
                    </dl>

                    <div class="detail-actions">
                      {#if removeConfirmUrl === source.url}
                        <span class="confirm-prompt" role="alertdialog" aria-label="Remove confirmation for source {source.url}">
                          <span class="confirm-text">Remove this source? This cannot be undone.</span>
                          <button
                            class="action-btn action-btn--danger"
                            onclick={() => void executeRemove(source.url)}
                            disabled={removeLoading}
                            aria-label="Confirm remove source {source.url}"
                          >
                            {removeLoading ? "Removing..." : "Confirm"}
                          </button>
                          <button
                            class="action-btn"
                            onclick={cancelRemove}
                            disabled={removeLoading}
                            aria-label="Cancel remove source {source.url}"
                          >
                            Cancel
                          </button>
                        </span>
                      {:else}
                        <button
                          class="action-btn action-btn--danger"
                          onclick={() => confirmRemove(source.url)}
                          aria-label="Remove source {source.url}"
                        >
                          Remove
                        </button>
                      {/if}
                    </div>
                  </div>
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<style>
  .source-health {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .section-header {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .section-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .toast {
    padding: 0.6rem 1rem;
    background: color-mix(in srgb, var(--success, #a6e3a1) 15%, transparent);
    border: 1px solid var(--success, #a6e3a1);
    border-radius: 6px;
    color: var(--success, #a6e3a1);
    font-size: 0.85rem;
  }

  .error-banner {
    padding: 0.75rem 1rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    border: 1px solid var(--error, #f38ba8);
    border-radius: 6px;
    color: var(--error, #f38ba8);
    font-size: 0.875rem;
  }

  /* Empty state */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
    padding: 2rem 0;
    text-align: center;
  }

  .empty-state__text {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
    margin: 0;
  }

  .empty-state__link {
    background: none;
    border: none;
    color: var(--accent, #89b4fa);
    font-size: 0.875rem;
    cursor: pointer;
    text-decoration: underline;
    padding: 0;
  }

  .empty-state__link:hover {
    color: var(--fg, #cdd6f4);
  }

  /* DataTable */
  .datatable-scroll {
    overflow-x: auto;
  }

  .datatable {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
  }

  .datatable-th {
    text-align: left;
    padding: 0.6rem 0.75rem;
    border-bottom: 2px solid var(--border, #313244);
    font-weight: 600;
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    white-space: nowrap;
    user-select: none;
  }

  .datatable-row {
    border-bottom: 1px solid var(--border, #313244);
    transition: background 0.1s;
  }

  .datatable-row:hover {
    background: var(--row-hover, #313244);
  }

  .datatable-row--expanded {
    background: color-mix(in srgb, var(--accent, #89b4fa) 8%, transparent);
  }

  .datatable-td {
    padding: 0.55rem 0.75rem;
    vertical-align: middle;
    color: var(--fg, #cdd6f4);
  }

  .datatable-td--url {
    max-width: 240px;
  }

  /* Expand button */
  .expand-btn {
    background: none;
    border: none;
    padding: 0;
    color: var(--fg, #cdd6f4);
    font-size: 0.875rem;
    cursor: pointer;
    text-align: left;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 220px;
    display: block;
  }

  .expand-btn:hover {
    color: var(--accent, #89b4fa);
    text-decoration: underline;
  }

  /* Type badge */
  .type-badge {
    display: inline-block;
    padding: 0.15rem 0.45rem;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 500;
    background: color-mix(in srgb, var(--fg-muted, #a6adc8) 15%, transparent);
    color: var(--fg-muted, #a6adc8);
  }

  .type-badge--rss {
    background: color-mix(in srgb, #fab387 15%, transparent);
    color: #fab387;
  }

  .type-badge--github {
    background: color-mix(in srgb, #89b4fa 15%, transparent);
    color: #89b4fa;
  }

  /* Status badge */
  .status-badge {
    display: inline-block;
    padding: 0.2rem 0.5rem;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 600;
  }

  .status-badge--green {
    background: color-mix(in srgb, #a6e3a1 20%, transparent);
    color: #a6e3a1;
    border: 1px solid color-mix(in srgb, #a6e3a1 40%, transparent);
  }

  .status-badge--yellow {
    background: color-mix(in srgb, #f9e2af 20%, transparent);
    color: #f9e2af;
    border: 1px solid color-mix(in srgb, #f9e2af 40%, transparent);
  }

  .status-badge--red {
    background: color-mix(in srgb, #f38ba8 20%, transparent);
    color: #f38ba8;
    border: 1px solid color-mix(in srgb, #f38ba8 40%, transparent);
  }

  .status-badge--gray {
    background: color-mix(in srgb, #a6adc8 15%, transparent);
    color: #a6adc8;
    border: 1px solid color-mix(in srgb, #a6adc8 30%, transparent);
  }

  /* Expanded detail row */
  .expanded-row {
    background: var(--detail-bg, #181825);
  }

  .expanded-td {
    padding: 0;
  }

  .detail-panel {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border, #313244);
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .detail-list {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.35rem 1rem;
    margin: 0;
    font-size: 0.85rem;
  }

  .detail-list dt {
    color: var(--fg-muted, #a6adc8);
    font-weight: 600;
  }

  .detail-list dd {
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .detail-url {
    word-break: break-all;
  }

  .detail-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .confirm-prompt {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .confirm-text {
    font-size: 0.875rem;
    color: var(--fg, #cdd6f4);
  }

  /* Action buttons */
  .action-btn {
    padding: 0.3rem 0.65rem;
    font-size: 0.75rem;
    font-weight: 500;
    background: var(--btn-bg, #313244);
    color: var(--btn-fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
    white-space: nowrap;
  }

  .action-btn:hover:not(:disabled) {
    background: var(--btn-hover, #45475a);
  }

  .action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .action-btn--danger {
    background: color-mix(in srgb, #f38ba8 15%, transparent);
    border-color: color-mix(in srgb, #f38ba8 40%, transparent);
    color: #f38ba8;
  }

  .action-btn--danger:hover:not(:disabled) {
    background: color-mix(in srgb, #f38ba8 25%, transparent);
  }
</style>
