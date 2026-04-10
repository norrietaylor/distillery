<script lang="ts">
  import type { Snippet } from "svelte";
  import type { McpBridge } from "$lib/mcp-bridge";
  import { workingSet, pinEntry, unpinEntry, isEntryPinned } from "$lib/stores";
  import LoadingSkeleton from "./LoadingSkeleton.svelte";
  import ScoreBadge from "./ScoreBadge.svelte";
  import DataTable from "./DataTable.svelte";
  import type { Column } from "./DataTable.svelte";

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge?: McpBridge | null;
    /** Search query to execute against distillery_recall. */
    query?: string;
    /** Optional callback when a row is clicked — receives the entry id. */
    onRowClick?: (entryId: string) => void;
  }

  let { bridge = null, query = "", onRowClick }: Props = $props();

  /** Toggle pin state for a result row. */
  function togglePin(row: SearchResult, event: MouseEvent): void {
    event.stopPropagation();
    if (isEntryPinned(row.id, $workingSet)) {
      unpinEntry(row.id);
    } else {
      pinEntry({
        id: row.id,
        title: row.content.split("\n")[0]?.slice(0, 60) || row.id,
        type: row.entry_type || "entry",
        content: row.content,
        pinnedAt: new Date().toISOString(),
      });
    }
  }

  /** A single search result as returned by the recall tool. */
  interface SearchResult {
    id: string;
    content: string;
    entry_type: string;
    source: string;
    score: number;
    tags: string[];
    created_at: string;
    [key: string]: unknown;
  }

  let results = $state<SearchResult[]>([]);
  let loading = $state(false);
  let loadError = $state<string | null>(null);
  let filterText = $state("");
  let expandedId = $state<string | null>(null);

  /** Parse a line of text output into SearchResult objects. */
  function parseResults(text: string): SearchResult[] {
    if (!text.trim()) return [];
    // Try JSON array first, then newline-delimited JSON.
    try {
      const parsed: unknown = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed.map(normalizeResult);
      }
      if (parsed && typeof parsed === "object") {
        return [normalizeResult(parsed as Record<string, unknown>)];
      }
    } catch {
      // fall through to line-by-line
    }

    const list: SearchResult[] = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const obj: unknown = JSON.parse(trimmed);
        if (obj && typeof obj === "object") {
          list.push(normalizeResult(obj as Record<string, unknown>));
        }
      } catch {
        // skip unparseable lines
      }
    }
    return list;
  }

  function normalizeResult(obj: Record<string, unknown>): SearchResult {
    const raw = obj as Partial<SearchResult>;
    return {
      ...obj,
      id: String(raw.id ?? crypto.randomUUID()),
      content: String(raw.content ?? ""),
      entry_type: String(raw.entry_type ?? raw.type ?? ""),
      source: String(raw.source ?? ""),
      score: typeof raw.score === "number" ? raw.score : 0,
      tags: Array.isArray(raw.tags) ? (raw.tags as string[]) : [],
      created_at: String(raw.created_at ?? raw.published_at ?? ""),
    };
  }

  /** Content preview: first line up to 80 chars. */
  function contentPreview(content: string): string {
    const first = content.split("\n")[0] ?? content;
    return first.length > 80 ? first.slice(0, 80) + "…" : first;
  }

  /** Format an ISO date string to a human-readable date. */
  function formatDate(iso: string): string {
    if (!iso) return "—";
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

  async function search(q: string) {
    if (!bridge?.isConnected || !q.trim()) {
      results = [];
      return;
    }
    loading = true;
    loadError = null;
    try {
      const result = await bridge.callTool("distillery_recall", { query: q.trim(), limit: 50 });
      if (result.isError) {
        loadError = result.text || "Search failed";
        results = [];
        return;
      }
      results = parseResults(result.text);
    } catch (err) {
      loadError = err instanceof Error ? err.message : "Search failed";
      results = [];
    } finally {
      loading = false;
    }
  }

  // Re-run search when query prop changes
  $effect(() => {
    void search(query);
  });

  /** Client-side filter against content, type, source, tags. */
  let filteredResults = $derived.by((): SearchResult[] => {
    const q = filterText.trim().toLowerCase();
    if (!q) return results;
    return results.filter((r) =>
      r.content.toLowerCase().includes(q) ||
      r.entry_type.toLowerCase().includes(q) ||
      r.source.toLowerCase().includes(q) ||
      r.tags.some((t) => t.toLowerCase().includes(q)),
    );
  });

  /** Build column definitions. */
  function buildColumns(scoreSnippet?: Snippet<[SearchResult]>, pinSnippet?: Snippet<[SearchResult]>): Column<SearchResult>[] {
    return [
      {
        key: "content",
        label: "Content",
        sortable: false,
        renderText: (row) => contentPreview(row.content),
      },
      {
        key: "entry_type",
        label: "Type",
        sortable: true,
      },
      {
        key: "score",
        label: "Score",
        sortable: true,
        renderSnippet: scoreSnippet,
      },
      {
        key: "tags",
        label: "Tags",
        sortable: false,
        renderText: (row) => row.tags.join(", "),
      },
      {
        key: "created_at",
        label: "Date",
        sortable: true,
        renderText: (row) => formatDate(row.created_at),
      },
      {
        key: "id",
        label: "",
        sortable: false,
        renderSnippet: pinSnippet,
      },
    ];
  }

  function handleRowClick(row: SearchResult) {
    expandedId = expandedId === row.id ? null : row.id;
    onRowClick?.(row.id);
  }

  let expandedResult = $derived.by((): SearchResult | null => {
    if (!expandedId) return null;
    return filteredResults.find((r) => r.id === expandedId) ?? null;
  });
</script>

<section class="results-list" aria-labelledby="results-list-heading">
  <div class="section-header">
    <h2 id="results-list-heading" class="section-title">Search Results</h2>
    {#if results.length > 0}
      <input
        class="filter-input"
        type="search"
        placeholder="Filter results..."
        bind:value={filterText}
        aria-label="Filter search results"
      />
    {/if}
  </div>

  {#if loading}
    <LoadingSkeleton rows={5} label="Searching..." />
  {:else if loadError}
    <div class="error-banner" role="alert">
      <strong>Error:</strong> {loadError}
    </div>
  {:else if !query.trim()}
    <p class="empty-state">Enter a query above to search the knowledge base.</p>
  {:else if results.length === 0}
    <p class="empty-state">No results found for "{query}".</p>
  {:else}
    {#snippet scoreCell(row: SearchResult)}
      <ScoreBadge score={row.score} />
    {/snippet}

    {#snippet pinCell(row: SearchResult)}
      <button
        class="pin-btn"
        class:pin-btn--active={isEntryPinned(row.id, $workingSet)}
        onclick={(e) => togglePin(row, e)}
        aria-label={isEntryPinned(row.id, $workingSet) ? `Unpin ${row.content.split("\n")[0]?.slice(0, 40) || row.id}` : `Pin ${row.content.split("\n")[0]?.slice(0, 40) || row.id}`}
      >
        {isEntryPinned(row.id, $workingSet) ? "Unpin" : "Pin"}
      </button>
    {/snippet}

    <DataTable
      columns={buildColumns(scoreCell, pinCell)}
      rows={filteredResults}
      defaultSortKey="score"
      defaultSortDir="desc"
      pageSize={20}
      rowKey="id"
      onRowClick={handleRowClick}
      expandedRowId={expandedId}
    />

    {#if expandedResult}
      {@const entry = expandedResult}
      <div class="detail-panel" aria-label="Result detail">
        <div class="detail-header">
          <span class="detail-type">{entry.entry_type || "entry"}</span>
          {#if entry.source}
            <span class="detail-source">{entry.source}</span>
          {/if}
          <ScoreBadge score={entry.score} />
          <span class="detail-date">{formatDate(entry.created_at)}</span>
          <button
            class="pin-btn"
            class:pin-btn--active={isEntryPinned(entry.id, $workingSet)}
            onclick={(e) => togglePin(entry, e)}
            aria-label={isEntryPinned(entry.id, $workingSet) ? "Unpin entry" : "Pin entry"}
          >
            {isEntryPinned(entry.id, $workingSet) ? "Unpin" : "Pin"}
          </button>
          <button
            class="close-btn"
            onclick={() => { expandedId = null; }}
            aria-label="Close detail panel"
          >
            &times;
          </button>
        </div>

        {#if entry.tags.length > 0}
          <div class="detail-tags">
            {#each entry.tags as tag (tag)}
              <span class="tag">{tag}</span>
            {/each}
          </div>
        {/if}

        <div class="detail-content">
          <pre>{entry.content}</pre>
        </div>
      </div>
    {/if}
  {/if}
</section>

<style>
  .results-list {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .section-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .filter-input {
    padding: 0.35rem 0.65rem;
    font-size: 0.85rem;
    background: var(--input-bg, #313244);
    color: var(--fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    min-width: 180px;
    max-width: 260px;
  }

  .filter-input::placeholder {
    color: var(--fg-muted, #a6adc8);
  }

  .error-banner {
    padding: 0.75rem 1rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    border: 1px solid var(--error, #f38ba8);
    border-radius: 6px;
    color: var(--error, #f38ba8);
    font-size: 0.875rem;
  }

  .empty-state {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
    font-style: italic;
    text-align: center;
    padding: 1.5rem 0;
  }

  /* Detail panel */
  .detail-panel {
    background: var(--detail-bg, #181825);
    border: 1px solid var(--border, #313244);
    border-radius: 6px;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .detail-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .detail-type {
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.15rem 0.45rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border-radius: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .detail-source {
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--fg-muted, #a6adc8);
  }

  .detail-date {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    margin-left: auto;
  }

  .close-btn {
    background: none;
    border: none;
    color: var(--fg-muted, #a6adc8);
    font-size: 1.25rem;
    cursor: pointer;
    padding: 0 0.25rem;
    line-height: 1;
  }

  .close-btn:hover {
    color: var(--fg, #cdd6f4);
  }

  .detail-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }

  .tag {
    display: inline-block;
    padding: 0.15rem 0.45rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border-radius: 10px;
    font-size: 0.7rem;
    font-weight: 500;
  }

  .detail-content {
    background: var(--code-bg, #11111b);
    border-radius: 4px;
    padding: 0.75rem;
    overflow-x: auto;
    max-height: 300px;
    overflow-y: auto;
  }

  .detail-content pre {
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  /* Pin button */
  .pin-btn {
    padding: 0.15rem 0.45rem;
    font-size: 0.75rem;
    border-radius: 4px;
    border: 1px solid var(--border, #45475a);
    background: none;
    color: var(--fg-muted, #a6adc8);
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.1s, color 0.1s, border-color 0.1s;
  }

  .pin-btn:hover {
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border-color: color-mix(in srgb, var(--accent, #89b4fa) 40%, transparent);
  }

  .pin-btn--active {
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border-color: color-mix(in srgb, var(--accent, #89b4fa) 40%, transparent);
  }

  .pin-btn--active:hover {
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    color: var(--error, #f38ba8);
    border-color: color-mix(in srgb, var(--error, #f38ba8) 40%, transparent);
  }
</style>
