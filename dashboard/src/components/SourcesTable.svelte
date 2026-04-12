<script lang="ts">
  import type { McpBridge } from "$lib/mcp-bridge";
  import DataTable from "./DataTable.svelte";
  import type { Column } from "./DataTable.svelte";

  interface Props {
    bridge: McpBridge | null;
    /** Bump this counter to trigger a refresh (e.g. after WatchSource adds a source). */
    refreshToken?: number;
  }

  let { bridge, refreshToken = 0 }: Props = $props();

  /** A feed source returned by watch(action="list"). */
  interface FeedSource {
    url: string;
    source_type: string;
    label: string;
    trust_weight: number;
    poll_interval?: string;
    added_at?: string;
  }

  /** Row shape for DataTable — must extend Record<string, unknown>. */
  type SourceRow = FeedSource & Record<string, unknown>;

  let sources = $state<SourceRow[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let expandedRowUrl = $state<string | null>(null);

  /** URL pending removal — awaiting confirmation. */
  let pendingRemoveUrl = $state<string | null>(null);
  /** Error message from a failed remove. */
  let removeError = $state<string | null>(null);

  /** Load sources from the MCP watch list. */
  async function loadSources() {
    if (!bridge) return;
    loading = true;
    error = null;
    try {
      const result = await bridge.callTool("distillery_watch", { action: "list" });
      if (result.isError) {
        error = result.text || "Failed to load sources";
        return;
      }
      sources = parseSources(result.text);
    } catch (err) {
      error = err instanceof Error ? err.message : "Failed to load sources";
    } finally {
      loading = false;
    }
  }

  /** Parse JSON response from watch list into SourceRow[]. */
  function parseSources(text: string): SourceRow[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed.map(normalizeSource);
      }
      if (parsed && typeof parsed === "object") {
        // Maybe { sources: [...] }
        const obj = parsed as Record<string, unknown>;
        if (Array.isArray(obj["sources"])) {
          return (obj["sources"] as unknown[]).map(normalizeSource);
        }
        return [normalizeSource(obj)];
      }
    } catch {
      // fall through
    }
    return [];
  }

  function normalizeSource(raw: unknown): SourceRow {
    const obj = raw as Record<string, unknown>;
    return {
      url: String(obj["url"] ?? ""),
      source_type: String(obj["source_type"] ?? obj["type"] ?? "rss"),
      label: String(obj["label"] ?? ""),
      trust_weight: typeof obj["trust_weight"] === "number" ? obj["trust_weight"] : 1.0,
      poll_interval: obj["poll_interval"] != null ? String(obj["poll_interval"]) : undefined,
      added_at: obj["added_at"] != null ? String(obj["added_at"]) : undefined,
    };
  }

  /** Handle row click — toggle expansion. */
  function handleRowClick(row: SourceRow) {
    const rowUrl = row["url"] as string;
    expandedRowUrl = expandedRowUrl === rowUrl ? null : rowUrl;
    pendingRemoveUrl = null;
    removeError = null;
  }

  /** Show confirmation dialog for removal. */
  function requestRemove(url: string) {
    pendingRemoveUrl = url;
  }

  /** Cancel removal. */
  function cancelRemove() {
    pendingRemoveUrl = null;
  }

  /** Confirm and execute removal with optimistic UI. */
  async function confirmRemove(url: string) {
    if (!bridge) return;

    // Optimistically remove the row
    const snapshot = [...sources];
    sources = sources.filter((s) => s["url"] !== url);
    expandedRowUrl = null;
    pendingRemoveUrl = null;
    removeError = null;

    try {
      const result = await bridge.callTool("distillery_watch", {
        action: "remove",
        url,
      });
      if (result.isError) {
        // Rollback
        sources = snapshot;
        removeError = result.text || "Failed to remove source";
      }
    } catch (err) {
      // Rollback
      sources = snapshot;
      removeError = err instanceof Error ? err.message : "Failed to remove source";
    }
  }

  /** Format trust weight to one decimal place. */
  function formatTrustWeight(value: number): string {
    return (Math.round(value * 10) / 10).toFixed(1);
  }

  /** Format added date to a short readable string. */
  function formatDate(value: string | undefined): string {
    if (!value) return "";
    try {
      return new Date(value).toLocaleDateString();
    } catch {
      return value;
    }
  }

  /** Truncate a URL to a display-safe length. */
  function truncateUrl(url: string, maxLen = 40): string {
    if (url.length <= maxLen) return url;
    return url.slice(0, maxLen - 1) + "…";
  }

  /** DataTable column definitions. */
  const columns: Column<SourceRow>[] = [
    {
      key: "url",
      label: "Source",
      renderText: (row) => truncateUrl(row["url"] as string),
    },
    {
      key: "source_type",
      label: "Type",
      renderText: (row) => (row["source_type"] as string).toUpperCase(),
    },
    { key: "label", label: "Label" },
    {
      key: "trust_weight",
      label: "Trust Weight",
      sortable: true,
      renderText: (row) => formatTrustWeight(row["trust_weight"] as number),
    },
    {
      key: "poll_interval",
      label: "Poll Interval",
      renderText: (row) => (row["poll_interval"] as string | undefined) ?? "",
    },
    {
      key: "added_at",
      label: "Added Date",
      sortable: true,
      renderText: (row) => formatDate(row["added_at"] as string | undefined),
    },
  ];

  // Load on mount and whenever the bridge or refreshToken changes.
  $effect(() => {
    void refreshToken;
    if (bridge) {
      void loadSources();
    }
  });
</script>

<div class="sources-table-card" data-testid="sources-table">
  <h2 class="card-title">Current Sources</h2>

  {#if removeError}
    <div class="error-banner" role="alert">
      {removeError}
    </div>
  {/if}

  {#if loading}
    <div class="loading-state" aria-label="Loading sources">
      <span class="spinner" aria-hidden="true"></span>
      Loading sources…
    </div>
  {:else if error}
    <div class="error-banner" role="alert">
      {error}
    </div>
  {:else if sources.length === 0}
    <p class="empty-state" data-testid="empty-state">
      No sources configured. Add an RSS feed or GitHub repo above.
    </p>
  {:else}
    <DataTable
      {columns}
      rows={sources}
      rowKey="url"
      defaultSortKey="added_at"
      onRowClick={handleRowClick}
      expandedRowId={expandedRowUrl}
    />

    {#if expandedRowUrl}
      {@const expandedSource = sources.find((s) => s["url"] === expandedRowUrl)}
      {#if expandedSource}
        <div class="detail-row" data-testid="detail-row">
          <div class="detail-url">
            <span class="detail-label">Full URL:</span>
            <span class="detail-value" title={expandedSource["url"] as string}>
              {expandedSource["url"]}
            </span>
          </div>

          {#if pendingRemoveUrl === expandedSource["url"]}
            <!-- Confirmation dialog -->
            <div class="confirm-dialog" role="dialog" aria-label="Confirm removal">
              <p class="confirm-message">
                Remove this source? Feed items already stored will remain.
              </p>
              <div class="confirm-actions">
                <button
                  class="btn btn--danger"
                  onclick={() => confirmRemove(expandedSource["url"] as string)}
                  aria-label="Confirm remove"
                >
                  Remove
                </button>
                <button
                  class="btn btn--secondary"
                  onclick={cancelRemove}
                  aria-label="Cancel remove"
                >
                  Cancel
                </button>
              </div>
            </div>
          {:else}
            <button
              class="btn btn--danger"
              onclick={() => requestRemove(expandedSource["url"] as string)}
              aria-label="Remove source"
            >
              Remove
            </button>
          {/if}
        </div>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .sources-table-card {
    background: var(--card-bg, #181825);
    border: 1px solid var(--border, #313244);
    border-radius: 8px;
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .card-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .loading-state {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
    padding: 1rem 0;
  }

  .spinner {
    display: inline-block;
    width: 0.75rem;
    height: 0.75rem;
    border: 2px solid currentColor;
    border-right-color: transparent;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .empty-state {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
    font-style: italic;
    padding: 1rem 0;
    margin: 0;
  }

  .error-banner {
    padding: 0.5rem 0.75rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    border: 1px solid var(--error, #f38ba8);
    border-radius: 6px;
    color: var(--error, #f38ba8);
    font-size: 0.8rem;
  }

  .detail-row {
    padding: 0.75rem 1rem;
    background: var(--detail-bg, #11111b);
    border: 1px solid var(--border, #313244);
    border-radius: 6px;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .detail-url {
    display: flex;
    gap: 0.5rem;
    align-items: flex-start;
    font-size: 0.85rem;
  }

  .detail-label {
    color: var(--fg-muted, #a6adc8);
    white-space: nowrap;
    font-weight: 500;
  }

  .detail-value {
    color: var(--fg, #cdd6f4);
    word-break: break-all;
    font-family: monospace;
    font-size: 0.8rem;
  }

  .confirm-dialog {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .confirm-message {
    font-size: 0.85rem;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .confirm-actions {
    display: flex;
    gap: 0.5rem;
  }

  .btn {
    padding: 0.35rem 0.8rem;
    font-size: 0.8rem;
    font-weight: 500;
    border-radius: 4px;
    cursor: pointer;
    transition: opacity 0.15s;
    border: 1px solid transparent;
  }

  .btn--danger {
    background: color-mix(in srgb, var(--error, #f38ba8) 20%, transparent);
    border-color: color-mix(in srgb, var(--error, #f38ba8) 50%, transparent);
    color: var(--error, #f38ba8);
  }

  .btn--danger:hover {
    opacity: 0.8;
  }

  .btn--secondary {
    background: var(--btn-bg, #313244);
    color: var(--btn-fg, #cdd6f4);
    border-color: var(--border, #45475a);
  }

  .btn--secondary:hover {
    opacity: 0.8;
  }
</style>
