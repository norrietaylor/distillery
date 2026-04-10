<script lang="ts">
  /**
   * EntryDetail — right-panel entry display component.
   *
   * Given an entryId, fetches full entry data and relations in parallel via
   * McpBridge, then renders metadata, content, and tags.  While loading it
   * shows a LoadingSkeleton.
   */

  import type { McpBridge } from "$lib/mcp-bridge";
  import LoadingSkeleton from "./LoadingSkeleton.svelte";

  // ---------------------------------------------------------------------------
  // Types
  // ---------------------------------------------------------------------------

  interface EntryData {
    id: string;
    content: string;
    entry_type: string;
    source: string;
    author: string;
    project: string | null;
    status: string;
    tags: string[];
    created_at: string;
    updated_at: string;
    expires_at: string | null;
    metadata: Record<string, unknown>;
    [key: string]: unknown;
  }

  interface Relation {
    id: string;
    related_id: string;
    relation_type: string;
    [key: string]: unknown;
  }

  // ---------------------------------------------------------------------------
  // Props
  // ---------------------------------------------------------------------------

  interface Props {
    bridge?: McpBridge | null;
    entryId?: string | null;
    onTagClick?: (tag: string) => void;
    onInvestigate?: (entryId: string) => void;
    onNavigate?: (entryId: string) => void;
  }

  let {
    bridge = null,
    entryId = null,
    onTagClick,
    onInvestigate,
    onNavigate,
  }: Props = $props();

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  let loading = $state(false);
  let loadError = $state<string | null>(null);
  let entry = $state<EntryData | null>(null);
  let relations = $state<Relation[]>([]);

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /** Parse a single entry from JSON text (may be object or single-element array). */
  function parseEntry(text: string): EntryData | null {
    if (!text.trim()) return null;
    try {
      const parsed: unknown = JSON.parse(text);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return normalizeEntry(parsed[0] as Record<string, unknown>);
      }
      if (parsed && typeof parsed === "object") {
        return normalizeEntry(parsed as Record<string, unknown>);
      }
    } catch {
      // Try newline-delimited JSON — take the first valid object.
      for (const line of text.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const obj: unknown = JSON.parse(trimmed);
          if (obj && typeof obj === "object" && !Array.isArray(obj)) {
            return normalizeEntry(obj as Record<string, unknown>);
          }
        } catch {
          // skip
        }
      }
    }
    return null;
  }

  function normalizeEntry(obj: Record<string, unknown>): EntryData {
    const raw = obj as Partial<EntryData>;
    return {
      ...obj,
      id: String(raw.id ?? ""),
      content: String(raw.content ?? ""),
      entry_type: String(raw.entry_type ?? raw.type ?? ""),
      source: String(raw.source ?? ""),
      author: String(raw.author ?? ""),
      project: typeof raw.project === "string" ? raw.project : null,
      status: String(raw.status ?? "unverified"),
      tags: Array.isArray(raw.tags) ? (raw.tags as string[]) : [],
      created_at: String(raw.created_at ?? ""),
      updated_at: String(raw.updated_at ?? ""),
      expires_at: typeof raw.expires_at === "string" ? raw.expires_at : null,
      metadata: typeof raw.metadata === "object" && raw.metadata !== null
        ? (raw.metadata as Record<string, unknown>)
        : {},
    };
  }

  /** Parse relations from JSON text. */
  function parseRelations(text: string): Relation[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed.map((r) => r as Relation);
      }
    } catch {
      // fall through to line-by-line
    }
    const list: Relation[] = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const obj: unknown = JSON.parse(trimmed);
        if (obj && typeof obj === "object") {
          list.push(obj as Relation);
        }
      } catch {
        // skip
      }
    }
    return list;
  }

  /** Format an ISO date string to a human-readable date. */
  function formatDate(iso: string | null): string {
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

  /** Map a status string to one of three verification badge CSS classes. */
  function badgeClass(status: string): string {
    if (status === "verified") return "badge badge--verified";
    if (status === "testing") return "badge badge--testing";
    return "badge badge--unverified";
  }

  /** Human-readable label for the verification badge. */
  function badgeLabel(status: string): string {
    if (status === "verified") return "Verified";
    if (status === "testing") return "Testing";
    return "Unverified";
  }

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  async function fetchEntry(id: string) {
    if (!bridge?.isConnected) {
      entry = null;
      relations = [];
      return;
    }

    loading = true;
    loadError = null;
    entry = null;
    relations = [];

    try {
      const [entryResult, relationsResult] = await Promise.all([
        bridge.callTool("distillery_get", { entry_id: id }),
        bridge.callTool("distillery_relations", { action: "get", entry_id: id }),
      ]);

      if (entryResult.isError) {
        loadError = entryResult.text || "Failed to load entry";
        return;
      }

      entry = parseEntry(entryResult.text);

      if (!relationsResult.isError) {
        relations = parseRelations(relationsResult.text);
      }
    } catch (err) {
      loadError = err instanceof Error ? err.message : "Failed to load entry";
    } finally {
      loading = false;
    }
  }

  // Re-fetch whenever entryId changes.
  $effect(() => {
    const id = entryId;
    if (id) {
      void fetchEntry(id);
    } else {
      entry = null;
      relations = [];
      loadError = null;
      loading = false;
    }
  });
</script>

<div class="entry-detail" aria-label="Entry detail panel">
  {#if !entryId}
    <div class="empty-state">
      <p class="empty-hint">Select an entry to view its details.</p>
    </div>
  {:else if loading}
    <LoadingSkeleton rows={6} label="Loading entry..." />
  {:else if loadError}
    <div class="error-banner" role="alert">
      <strong>Error:</strong> {loadError}
    </div>
  {:else if entry}
    <div class="entry-content">
      <!-- Header row: type badge + verification badge + actions -->
      <div class="entry-header">
        <span class="type-badge">{entry.entry_type || "entry"}</span>
        <span class={badgeClass(entry.status)} aria-label="Verification status">
          {badgeLabel(entry.status)}
        </span>

        {#if onInvestigate}
          <button
            class="action-btn"
            onclick={() => onInvestigate?.(entry!.id)}
            aria-label="Investigate entry"
          >
            Investigate
          </button>
        {/if}
      </div>

      <!-- Metadata grid -->
      <dl class="meta-grid">
        {#if entry.author}
          <dt>Author</dt>
          <dd>{entry.author}</dd>
        {/if}

        {#if entry.project}
          <dt>Project</dt>
          <dd>{entry.project}</dd>
        {/if}

        {#if entry.source}
          <dt>Source</dt>
          <dd class="source-value">{entry.source}</dd>
        {/if}

        <dt>Created</dt>
        <dd>{formatDate(entry.created_at)}</dd>

        {#if entry.updated_at && entry.updated_at !== entry.created_at}
          <dt>Updated</dt>
          <dd>{formatDate(entry.updated_at)}</dd>
        {/if}

        {#if entry.expires_at}
          <dt>Expires</dt>
          <dd class="expiry-value">{formatDate(entry.expires_at)}</dd>
        {/if}
      </dl>

      <!-- Tags -->
      {#if entry.tags.length > 0}
        <div class="tags-section" aria-label="Tags">
          {#each entry.tags as tag (tag)}
            <button
              class="tag-badge"
              onclick={() => onTagClick?.(tag)}
              aria-label="Filter by tag {tag}"
            >
              {tag}
            </button>
          {/each}
        </div>
      {/if}

      <!-- Full content -->
      <div class="content-block">
        <pre class="content-pre">{entry.content}</pre>
      </div>

      <!-- Relations -->
      {#if relations.length > 0}
        <div class="relations-section">
          <h3 class="relations-title">Relations</h3>
          <ul class="relations-list">
            {#each relations as rel (rel.id ?? rel.related_id)}
              <li class="relation-item">
                <span class="relation-type">{rel.relation_type}</span>
                {#if onNavigate && rel.related_id}
                  <button
                    class="relation-link"
                    onclick={() => onNavigate?.(rel.related_id)}
                    aria-label="View related entry {rel.related_id}"
                  >
                    {rel.related_id}
                  </button>
                {:else}
                  <span class="relation-id">{rel.related_id}</span>
                {/if}
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    </div>
  {:else}
    <div class="empty-state">
      <p class="empty-hint">No data found for this entry.</p>
    </div>
  {/if}
</div>

<style>
  .entry-detail {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  /* Empty / no selection state */
  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 120px;
  }

  .empty-hint {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
    font-style: italic;
    margin: 0;
    text-align: center;
  }

  /* Error banner */
  .error-banner {
    padding: 0.75rem 1rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    border: 1px solid var(--error, #f38ba8);
    border-radius: 6px;
    color: var(--error, #f38ba8);
    font-size: 0.875rem;
  }

  /* Entry content wrapper */
  .entry-content {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  /* Header row */
  .entry-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .type-badge {
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.15rem 0.45rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border-radius: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  /* Verification badges */
  .badge {
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.15rem 0.5rem;
    border-radius: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .badge--verified {
    background: color-mix(in srgb, var(--success, #a6e3a1) 20%, transparent);
    color: var(--success, #a6e3a1);
    border: 1px solid color-mix(in srgb, var(--success, #a6e3a1) 40%, transparent);
  }

  .badge--testing {
    background: color-mix(in srgb, var(--warning, #f9e2af) 20%, transparent);
    color: var(--warning, #f9e2af);
    border: 1px solid color-mix(in srgb, var(--warning, #f9e2af) 40%, transparent);
  }

  .badge--unverified {
    background: color-mix(in srgb, var(--fg-muted, #a6adc8) 15%, transparent);
    color: var(--fg-muted, #a6adc8);
    border: 1px solid color-mix(in srgb, var(--fg-muted, #a6adc8) 30%, transparent);
  }

  /* Action buttons */
  .action-btn {
    margin-left: auto;
    padding: 0.25rem 0.65rem;
    font-size: 0.75rem;
    font-weight: 500;
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border: 1px solid color-mix(in srgb, var(--accent, #89b4fa) 40%, transparent);
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
  }

  .action-btn:hover {
    background: color-mix(in srgb, var(--accent, #89b4fa) 30%, transparent);
  }

  /* Metadata definition list */
  .meta-grid {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.25rem 0.75rem;
    margin: 0;
    font-size: 0.8rem;
  }

  .meta-grid dt {
    color: var(--fg-muted, #a6adc8);
    font-weight: 500;
    white-space: nowrap;
    padding: 0.1rem 0;
  }

  .meta-grid dd {
    color: var(--fg, #cdd6f4);
    margin: 0;
    padding: 0.1rem 0;
    word-break: break-word;
  }

  .source-value {
    font-family: ui-monospace, monospace;
    font-size: 0.75rem;
  }

  .expiry-value {
    color: var(--warning, #f9e2af);
  }

  /* Tags section */
  .tags-section {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }

  .tag-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.15rem 0.5rem;
    font-size: 0.7rem;
    font-weight: 500;
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border: 1px solid color-mix(in srgb, var(--accent, #89b4fa) 30%, transparent);
    border-radius: 10px;
    cursor: pointer;
    transition: background 0.15s;
    line-height: 1.3;
  }

  .tag-badge:hover {
    background: color-mix(in srgb, var(--accent, #89b4fa) 30%, transparent);
  }

  /* Full content block */
  .content-block {
    background: var(--code-bg, #11111b);
    border-radius: 4px;
    padding: 0.75rem;
    overflow-x: auto;
    max-height: 320px;
    overflow-y: auto;
  }

  .content-pre {
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  /* Relations */
  .relations-section {
    border-top: 1px solid var(--border, #45475a);
    padding-top: 0.75rem;
  }

  .relations-title {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--fg-muted, #a6adc8);
    margin: 0 0 0.5rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .relations-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .relation-item {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    font-size: 0.8rem;
  }

  .relation-type {
    font-size: 0.7rem;
    font-weight: 500;
    color: var(--fg-muted, #a6adc8);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    white-space: nowrap;
  }

  .relation-link {
    background: none;
    border: none;
    padding: 0;
    color: var(--accent, #89b4fa);
    font-family: ui-monospace, monospace;
    font-size: 0.75rem;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 2px;
    word-break: break-all;
  }

  .relation-link:hover {
    color: var(--fg, #cdd6f4);
  }

  .relation-id {
    font-family: ui-monospace, monospace;
    font-size: 0.75rem;
    color: var(--fg-muted, #a6adc8);
    word-break: break-all;
  }
</style>
