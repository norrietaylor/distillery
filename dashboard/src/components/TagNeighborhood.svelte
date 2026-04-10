<script lang="ts">
  /**
   * TagNeighborhood — Phase 3 sidebar for investigation mode.
   *
   * Fetches tag clusters from seed tags using distillery_list(group_by="tags").
   * Displays tag clusters with entry counts in a sidebar layout.
   * Click a tag cluster → runs distillery_search scoped to that tag and shows results inline.
   */

  import type { McpBridge } from "$lib/mcp-bridge";
  import LoadingSkeleton from "./LoadingSkeleton.svelte";
  import ScoreBadge from "./ScoreBadge.svelte";

  // ---------------------------------------------------------------------------
  // Types
  // ---------------------------------------------------------------------------

  /** A tag cluster with its entry count. */
  interface TagCluster {
    tag: string;
    count: number;
  }

  /** A single search result entry. */
  interface TagSearchResult {
    id: string;
    content: string;
    entry_type: string;
    source: string;
    score: number;
    tags: string[];
    created_at: string;
    [key: string]: unknown;
  }

  /** Response shape from distillery_list(group_by="tags"). */
  interface GroupByResponse {
    groups: Array<{ value: string; count: number }>;
    total_groups?: number;
    total_entries?: number;
  }

  /** Response shape from distillery_search. */
  interface SearchResponse {
    results: Array<{ score: number; entry: Record<string, unknown> }>;
    count?: number;
  }

  // ---------------------------------------------------------------------------
  // Props
  // ---------------------------------------------------------------------------

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge?: McpBridge | null;
    /** Tags from the seed entry that started the investigation. */
    seedTags?: string[];
    /** Optional project scope for filtering. */
    project?: string | null;
    /** The investigation topic used as query for scoped search. */
    investigationTopic: string;
    /** Callback when search results are produced (notifies parent). */
    onResults?: (results: TagSearchResult[]) => void;
    /** Callback to pin an entry to the working set. */
    onPin?: (entry: TagSearchResult) => void;
  }

  let {
    bridge = null,
    seedTags = [],
    project = null,
    investigationTopic,
    onResults,
    onPin,
  }: Props = $props();

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  /** Tag clusters fetched on mount. */
  let clusters = $state<TagCluster[]>([]);
  let clustersLoading = $state(false);
  let clustersError = $state<string | null>(null);

  /** Currently expanded tag cluster — holds the clicked tag or null. */
  let expandedTag = $state<string | null>(null);

  /** Results for the currently expanded tag. */
  let tagResults = $state<TagSearchResult[]>([]);
  let tagResultsLoading = $state(false);
  let tagResultsError = $state<string | null>(null);

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /** Extract unique namespace prefixes from a list of tags. */
  function extractNamespacePrefixes(tags: string[]): string[] {
    const prefixes = new Set<string>();
    for (const tag of tags) {
      const slashIdx = tag.indexOf("/");
      if (slashIdx > 0) {
        prefixes.add(tag.slice(0, slashIdx));
      }
    }
    return Array.from(prefixes);
  }

  /** Content preview: first line up to 100 chars. */
  function contentPreview(content: string): string {
    const first = content.split("\n")[0] ?? content;
    return first.length > 100 ? first.slice(0, 100) + "..." : first;
  }

  /** Parse tool text response into a GroupByResponse. */
  function parseGroupByResponse(text: string): GroupByResponse | null {
    if (!text.trim()) return null;
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object" && "groups" in parsed) {
        return parsed as GroupByResponse;
      }
    } catch {
      // not parseable
    }
    return null;
  }

  /** Parse tool text response into search results. */
  function parseSearchResponse(text: string): TagSearchResult[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      // distillery_search returns {results: [{score, entry}], count}
      if (parsed && typeof parsed === "object" && "results" in parsed) {
        const resp = parsed as SearchResponse;
        return resp.results.map((r) => normalizeResult(r.entry, r.score));
      }
      // fallback: JSON array of entries
      if (Array.isArray(parsed)) {
        return parsed.map((e: Record<string, unknown>) => normalizeResult(e, 0));
      }
    } catch {
      // fall through to line-by-line
    }
    const list: TagSearchResult[] = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const obj: unknown = JSON.parse(trimmed);
        if (obj && typeof obj === "object") {
          list.push(normalizeResult(obj as Record<string, unknown>, 0));
        }
      } catch {
        // skip
      }
    }
    return list;
  }

  function normalizeResult(obj: Record<string, unknown>, defaultScore: number): TagSearchResult {
    const raw = obj as Partial<TagSearchResult>;
    return {
      ...obj,
      id: String(raw.id ?? crypto.randomUUID()),
      content: String(raw.content ?? ""),
      entry_type: String(raw.entry_type ?? raw.type ?? ""),
      source: String(raw.source ?? ""),
      score: typeof raw.score === "number" ? raw.score : defaultScore,
      tags: Array.isArray(raw.tags) ? (raw.tags as string[]) : [],
      created_at: String(raw.created_at ?? ""),
    };
  }

  // ---------------------------------------------------------------------------
  // Fetch tag clusters on mount
  // ---------------------------------------------------------------------------

  async function fetchTagClusters() {
    if (!bridge?.isConnected) {
      clustersError = "Not connected to MCP server";
      return;
    }

    const prefixes = extractNamespacePrefixes(seedTags);
    if (prefixes.length === 0 && seedTags.length === 0) {
      clusters = [];
      return;
    }

    clustersLoading = true;
    clustersError = null;

    try {
      // If we have namespace prefixes, fetch one cluster per prefix.
      // If no namespaced tags, fall back to fetching all tag clusters.
      if (prefixes.length > 0) {
        const allClusters: TagCluster[] = [];
        const seen = new Set<string>();

        for (const prefix of prefixes) {
          const args: Record<string, unknown> = {
            group_by: "tags",
            tag_prefix: prefix,
            limit: 50,
          };
          if (project) args["project"] = project;

          const result = await bridge.callTool("distillery_list", args);
          if (result.isError) {
            clustersError = result.text || "Failed to load tag clusters";
            clusters = [];
            return;
          }

          const parsed = parseGroupByResponse(result.text);
          if (parsed?.groups) {
            for (const group of parsed.groups) {
              if (group.value && !seen.has(group.value)) {
                seen.add(group.value);
                allClusters.push({ tag: group.value, count: group.count });
              }
            }
          }
        }

        // Sort by count descending
        allClusters.sort((a, b) => b.count - a.count);
        clusters = allClusters;
      } else {
        // No namespace prefixes — fetch without tag_prefix
        const args: Record<string, unknown> = { group_by: "tags", limit: 50 };
        if (project) args["project"] = project;

        const result = await bridge.callTool("distillery_list", args);
        if (result.isError) {
          clustersError = result.text || "Failed to load tag clusters";
          clusters = [];
          return;
        }

        const parsed = parseGroupByResponse(result.text);
        if (parsed?.groups) {
          clusters = parsed.groups
            .filter((g) => g.value)
            .map((g) => ({ tag: g.value, count: g.count }));
        } else {
          clusters = [];
        }
      }
    } catch (err) {
      clustersError = err instanceof Error ? err.message : "Failed to load tag clusters";
      clusters = [];
    } finally {
      clustersLoading = false;
    }
  }

  // Kick off on mount and when seedTags change
  $effect(() => {
    // Track seedTags so this effect re-runs if they change
    const _tags = seedTags;
    const _project = project;
    void fetchTagClusters();
  });

  // ---------------------------------------------------------------------------
  // Click a tag cluster → scoped search
  // ---------------------------------------------------------------------------

  let activeTagRequest = 0;

  async function handleTagClick(tag: string) {
    if (expandedTag === tag) {
      // Toggle closed
      expandedTag = null;
      tagResults = [];
      return;
    }

    if (!bridge?.isConnected) {
      tagResultsError = "Not connected to MCP server";
      return;
    }

    const requestId = ++activeTagRequest;
    expandedTag = tag;
    tagResults = [];
    tagResultsLoading = true;
    tagResultsError = null;

    try {
      const args: Record<string, unknown> = {
        query: investigationTopic,
        tags: [tag],
        limit: 10,
      };
      if (project) args["project"] = project;

      const result = await bridge.callTool("distillery_search", args);
      if (requestId !== activeTagRequest) return;
      if (result.isError) {
        tagResultsError = result.text || "Search failed";
        tagResults = [];
        return;
      }

      const results = parseSearchResponse(result.text);
      tagResults = results;
      onResults?.(results);
    } catch (err) {
      if (requestId !== activeTagRequest) return;
      tagResultsError = err instanceof Error ? err.message : "Search failed";
      tagResults = [];
    } finally {
      if (requestId === activeTagRequest) {
        tagResultsLoading = false;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Pin entry
  // ---------------------------------------------------------------------------

  function handlePin(result: TagSearchResult) {
    onPin?.(result);
  }
</script>

<aside class="tag-neighborhood" aria-label="Tag neighborhood">
  <h3 class="tag-neighborhood-title">Tag Neighborhood</h3>

  {#if clustersLoading}
    <LoadingSkeleton rows={4} label="Loading tag clusters..." />
  {:else if clustersError}
    <div class="error-banner" role="alert">
      <strong>Error:</strong> {clustersError}
    </div>
  {:else if clusters.length === 0}
    <p class="empty-state">No related tags found.</p>
  {:else}
    <p class="neighborhood-hint">Tags related to investigation:</p>
    <ul class="tag-cluster-list" aria-label="Tag clusters">
      {#each clusters as cluster (cluster.tag)}
        {@const isExpanded = expandedTag === cluster.tag}
        <li class="tag-cluster-item">
          <button
            class="tag-cluster-btn"
            class:tag-cluster-btn--expanded={isExpanded}
            onclick={() => handleTagClick(cluster.tag)}
            aria-expanded={isExpanded}
            aria-label="Tag cluster: {cluster.tag}, {cluster.count} entries"
          >
            <span class="tag-cluster-name">{cluster.tag}</span>
            <span class="tag-cluster-count">({cluster.count} {cluster.count === 1 ? "entry" : "entries"})</span>
          </button>

          {#if isExpanded}
            <div class="tag-results" aria-label="Results for {cluster.tag}">
              {#if tagResultsLoading}
                <LoadingSkeleton rows={3} showHeader={false} label="Searching tag entries..." />
              {:else if tagResultsError}
                <div class="error-banner" role="alert">
                  <strong>Error:</strong> {tagResultsError}
                </div>
              {:else if tagResults.length === 0}
                <p class="empty-state">No results found for this tag.</p>
              {:else}
                <ul class="result-cards" aria-label="Tag search results">
                  {#each tagResults as result (result.id)}
                    <li class="result-card">
                      <div class="card-body">
                        <div class="card-header">
                          <span class="card-type">{result.entry_type || "entry"}</span>
                          <ScoreBadge score={result.score} />
                        </div>
                        <p class="card-preview">{contentPreview(result.content)}</p>
                        {#if result.tags.length > 0}
                          <div class="card-tags">
                            {#each result.tags as tag (tag)}
                              <span class="card-tag">{tag}</span>
                            {/each}
                          </div>
                        {/if}
                      </div>
                      <button
                        class="pin-btn"
                        onclick={() => handlePin(result)}
                        aria-label="Pin entry"
                        title="Pin to working set"
                      >
                        Pin
                      </button>
                    </li>
                  {/each}
                </ul>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</aside>

<style>
  .tag-neighborhood {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .tag-neighborhood-title {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .neighborhood-hint {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    margin: 0;
    font-style: italic;
  }

  /* Tag cluster list */
  .tag-cluster-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .tag-cluster-item {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .tag-cluster-btn {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    width: 100%;
    padding: 0.45rem 0.65rem;
    background: color-mix(in srgb, var(--bg-highlight, #313244) 30%, transparent);
    border: 1px solid var(--border, #45475a);
    border-radius: 6px;
    color: var(--fg, #cdd6f4);
    font-size: 0.8rem;
    text-align: left;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .tag-cluster-btn:hover {
    background: color-mix(in srgb, var(--accent, #89b4fa) 12%, transparent);
    border-color: color-mix(in srgb, var(--accent, #89b4fa) 50%, transparent);
  }

  .tag-cluster-btn--expanded {
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    border-color: var(--accent, #89b4fa);
    color: var(--accent, #89b4fa);
  }

  .tag-cluster-name {
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .tag-cluster-count {
    font-size: 0.75rem;
    color: var(--fg-muted, #a6adc8);
    white-space: nowrap;
    flex-shrink: 0;
  }

  .tag-cluster-btn--expanded .tag-cluster-count {
    color: inherit;
    opacity: 0.8;
  }

  /* Tag results area */
  .tag-results {
    padding: 0.35rem 0 0.35rem 0.75rem;
    border-left: 2px solid color-mix(in srgb, var(--accent, #89b4fa) 30%, transparent);
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  /* Result cards */
  .result-cards {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .result-card {
    display: flex;
    gap: 0.5rem;
    align-items: flex-start;
    background: color-mix(in srgb, var(--bg-highlight, #313244) 20%, transparent);
    border: 1px solid var(--border, #45475a);
    border-radius: 6px;
    overflow: hidden;
  }

  .card-body {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    padding: 0.6rem;
    min-width: 0;
    font-size: 0.8rem;
    color: var(--fg, #cdd6f4);
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .card-type {
    font-size: 0.65rem;
    font-weight: 600;
    padding: 0.1rem 0.3rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border-radius: 8px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .card-preview {
    margin: 0;
    color: var(--fg, #cdd6f4);
    line-height: 1.4;
    word-break: break-word;
  }

  .card-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.2rem;
  }

  .card-tag {
    display: inline-block;
    padding: 0.08rem 0.3rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 12%, transparent);
    color: var(--accent, #89b4fa);
    border-radius: 8px;
    font-size: 0.6rem;
    font-weight: 500;
  }

  .pin-btn {
    align-self: center;
    padding: 0.25rem 0.5rem;
    font-size: 0.7rem;
    font-weight: 500;
    background: none;
    color: var(--fg-muted, #a6adc8);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    cursor: pointer;
    white-space: nowrap;
    margin-right: 0.4rem;
    flex-shrink: 0;
  }

  .pin-btn:hover {
    color: var(--accent, #89b4fa);
    border-color: var(--accent, #89b4fa);
  }

  /* Error and empty states */
  .error-banner {
    padding: 0.6rem 0.85rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    border: 1px solid var(--error, #f38ba8);
    border-radius: 6px;
    color: var(--error, #f38ba8);
    font-size: 0.8rem;
  }

  .empty-state {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.8rem;
    font-style: italic;
    padding: 0.5rem 0;
  }
</style>
