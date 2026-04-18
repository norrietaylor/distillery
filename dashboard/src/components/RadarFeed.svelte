<script lang="ts">
  import type { Snippet } from "svelte";
  import { selectedProject, refreshTick, currentUser } from "$lib/stores";
  import type { McpBridge } from "$lib/mcp-bridge";
  import LoadingSkeleton from "./LoadingSkeleton.svelte";
  import ScoreBadge from "./ScoreBadge.svelte";
  import DataTable from "./DataTable.svelte";
  import type { Column } from "./DataTable.svelte";

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge?: McpBridge | null;
  }

  let { bridge = null }: Props = $props();

  /** A single radar feed entry as returned by the list tool. */
  interface FeedEntry {
    id: string;
    content: string;
    source: string;
    score: number;
    created_at: string;
    tags: string[];
    project?: string | null;
    [key: string]: unknown;
  }

  let entries = $state<FeedEntry[]>([]);
  let loading = $state(false);
  let loadError = $state<string | null>(null);
  let filterText = $state("");
  let expandedId = $state<string | null>(null);
  let bookmarkStatus = $state<Record<string, "idle" | "loading" | "success" | "error">>({});

  /** Parse a ``distillery_list`` text response into FeedEntry objects. */
  function parseEntries(text: string): FeedEntry[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      // distillery_list returns {entries: [...], count, total_count, ...}
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        const wrapped = parsed as Record<string, unknown>;
        if (Array.isArray(wrapped.entries)) {
          return (wrapped.entries as Array<Record<string, unknown>>).map(normalizeEntry);
        }
        // fallback: bare entry object (older response shape)
        return [normalizeEntry(wrapped)];
      }
      if (Array.isArray(parsed)) {
        return parsed.map((e) => normalizeEntry(e as Record<string, unknown>));
      }
    } catch {
      // fall through to line-by-line
    }

    const results: FeedEntry[] = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const obj: unknown = JSON.parse(trimmed);
        if (obj && typeof obj === "object") {
          results.push(normalizeEntry(obj as Record<string, unknown>));
        }
      } catch {
        // skip unparseable lines
      }
    }
    return results;
  }

  function normalizeEntry(obj: Record<string, unknown>): FeedEntry {
    const raw = obj as Partial<FeedEntry>;
    return {
      ...obj,
      id: String(raw.id ?? crypto.randomUUID()),
      content: String(raw.content ?? ""),
      source: String(raw.source ?? ""),
      score: typeof raw.score === "number" ? raw.score : 0,
      created_at: String(raw.created_at ?? raw.published_at ?? ""),
      tags: Array.isArray(raw.tags) ? (raw.tags as string[]) : [],
      project: typeof raw.project === "string" ? raw.project : null,
    };
  }

  /** ISO date string 7 days ago. */
  function sevenDaysAgo(): string {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return d.toISOString().split("T")[0] ?? d.toISOString();
  }

  /** Content preview: first 80 chars. */
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

  async function loadEntries() {
    if (!bridge?.isConnected) return;
    loading = true;
    loadError = null;
    try {
      const args: Record<string, unknown> = {
        entry_type: "feed",
        limit: 20,
        date_from: sevenDaysAgo(),
      };
      if ($selectedProject) {
        args["project"] = $selectedProject;
      }
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        loadError = result.text || "Failed to load radar feed";
        entries = [];
        return;
      }
      entries = parseEntries(result.text);
    } catch (err) {
      loadError = err instanceof Error ? err.message : "Failed to load radar feed";
      entries = [];
    } finally {
      loading = false;
    }
  }

  // Reload on each refresh tick and project change
  $effect(() => {
    const _tick = $refreshTick;
    const _project = $selectedProject;
    void loadEntries();
  });

  /** Client-side filter against all text fields. */
  let filteredEntries = $derived.by((): FeedEntry[] => {
    const q = filterText.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => {
      return (
        e.content.toLowerCase().includes(q) ||
        e.source.toLowerCase().includes(q) ||
        e.tags.some((t) => t.toLowerCase().includes(q))
      );
    });
  });

  /** Build column definitions, injecting the score snippet when provided. */
  function buildColumns(scoreSnippet?: Snippet<[FeedEntry]>): Column<FeedEntry>[] {
    return [
      {
        key: "content",
        label: "Title",
        sortable: false,
        renderText: (row) => contentPreview(row.content),
      },
      {
        key: "source",
        label: "Source",
        sortable: false,
      },
      {
        key: "score",
        label: "Score",
        sortable: true,
        renderSnippet: scoreSnippet,
      },
      {
        key: "created_at",
        label: "Published Date",
        sortable: true,
        renderText: (row) => formatDate(row.created_at),
      },
      {
        key: "tags",
        label: "Tags",
        sortable: false,
        renderText: (row) => row.tags.join(", "),
      },
    ];
  }

  function handleRowClick(row: FeedEntry) {
    expandedId = expandedId === row.id ? null : row.id;
  }

  async function handleBookmark(entry: FeedEntry) {
    if (!bridge?.isConnected) return;
    bookmarkStatus = { ...bookmarkStatus, [entry.id]: "loading" };
    try {
      const args: Record<string, unknown> = {
        content: entry.content,
        entry_type: "bookmark",
        author: $currentUser?.login ?? "user",
      };
      // Prefer the entry's own project so bookmarks don't get misattributed
      // when viewing "All projects" or if the filter changes after open.
      if (entry.project) args["project"] = entry.project;
      else if ($selectedProject) args["project"] = $selectedProject;
      const result = await bridge.callTool("distillery_store", args);
      bookmarkStatus = {
        ...bookmarkStatus,
        [entry.id]: result.isError ? "error" : "success",
      };
    } catch {
      bookmarkStatus = { ...bookmarkStatus, [entry.id]: "error" };
    }
  }

  let expandedEntry = $derived.by((): FeedEntry | null => {
    if (!expandedId) return null;
    return filteredEntries.find((e) => e.id === expandedId) ?? null;
  });
</script>

<section class="radar-feed" aria-labelledby="radar-feed-heading">
  <div class="section-header">
    <h2 id="radar-feed-heading" class="section-title">Radar Feed</h2>
    <input
      class="filter-input"
      type="search"
      placeholder="Filter entries..."
      bind:value={filterText}
      aria-label="Filter radar feed entries"
    />
  </div>

  {#if loading}
    <LoadingSkeleton rows={5} label="Loading radar feed..." />
  {:else if loadError}
    <div class="error-banner" role="alert">
      <strong>Error:</strong> {loadError}
    </div>
  {:else}
    {#snippet scoreCell(row: FeedEntry)}
      <ScoreBadge score={row.score} />
    {/snippet}

    <DataTable
      columns={buildColumns(scoreCell)}
      rows={filteredEntries}
      defaultSortKey="score"
      defaultSortDir="desc"
      pageSize={20}
      rowKey="id"
      onRowClick={handleRowClick}
      expandedRowId={expandedId}
    />

    {#if expandedEntry}
      {@const entry = expandedEntry}
      <div class="detail-panel" aria-label="Entry detail">
        <div class="detail-header">
          <span class="detail-source">{entry.source || "Unknown source"}</span>
          <ScoreBadge score={entry.score} />
          <span class="detail-date">{formatDate(entry.created_at)}</span>
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

        <div class="detail-actions">
          {#if bookmarkStatus[entry.id] === "success"}
            <span class="bookmark-success" role="status">Bookmarked!</span>
          {:else if bookmarkStatus[entry.id] === "error"}
            <span class="bookmark-error" role="alert">Bookmark failed. Try again.</span>
            <button
              class="action-btn"
              onclick={() => handleBookmark(entry)}
              aria-label="Retry bookmark"
            >
              Retry Bookmark
            </button>
          {:else}
            <button
              class="action-btn action-btn--primary"
              onclick={() => handleBookmark(entry)}
              disabled={bookmarkStatus[entry.id] === "loading"}
              aria-label="Bookmark this entry"
            >
              {bookmarkStatus[entry.id] === "loading" ? "Bookmarking…" : "Bookmark"}
            </button>
          {/if}
        </div>
      </div>
    {/if}

    {#if !loading && entries.length === 0 && !loadError}
      <p class="empty-state">No radar feed entries found in the last 7 days.</p>
    {/if}
  {/if}
</section>

<style>
  .radar-feed {
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

  .detail-source {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--accent, #89b4fa);
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

  .detail-actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .action-btn {
    padding: 0.4rem 0.9rem;
    font-size: 0.8rem;
    font-weight: 500;
    background: var(--btn-bg, #313244);
    color: var(--btn-fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
  }

  .action-btn:hover:not(:disabled) {
    background: var(--btn-hover, #45475a);
  }

  .action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .action-btn--primary {
    background: color-mix(in srgb, var(--accent, #89b4fa) 20%, transparent);
    border-color: color-mix(in srgb, var(--accent, #89b4fa) 50%, transparent);
    color: var(--accent, #89b4fa);
  }

  .action-btn--primary:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent, #89b4fa) 35%, transparent);
  }

  .bookmark-success {
    font-size: 0.8rem;
    color: var(--success, #a6e3a1);
    font-weight: 500;
  }

  .bookmark-error {
    font-size: 0.8rem;
    color: var(--error, #f38ba8);
  }
</style>
