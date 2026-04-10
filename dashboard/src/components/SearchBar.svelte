<script lang="ts">
  /**
   * SearchBar — semantic search input for the Explore tab.
   *
   * Allows the user to run a free-text semantic search against the knowledge
   * base via the distillery_recall MCP tool.  Results are rendered in a simple
   * list with source, type, and relevance score.
   *
   * Behaviour:
   *  - Submitting an empty query is a no-op (shows idle state).
   *  - The project filter from $selectedProject is forwarded to the tool call.
   *  - Loading, error, and empty-results states are all surfaced via ARIA roles.
   */

  import type { McpBridge } from "$lib/mcp-bridge";
  import { selectedProject } from "$lib/stores";

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge?: McpBridge | null;
  }

  let { bridge = null }: Props = $props();

  /** A single search result as returned by distillery_recall. */
  interface SearchResult {
    id: string;
    content: string;
    source: string;
    entry_type: string;
    score: number;
    tags: string[];
    [key: string]: unknown;
  }

  let query = $state("");
  let results = $state<SearchResult[]>([]);
  let loading = $state(false);
  let searchError = $state<string | null>(null);
  /** Whether a search has been attempted at least once. */
  let hasSearched = $state(false);

  /** Parse the text response from distillery_recall into SearchResult objects. */
  function parseResults(text: string): SearchResult[] {
    if (!text.trim()) return [];
    // Try JSON array first, then single object, then newline-delimited JSON.
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

    const out: SearchResult[] = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const obj: unknown = JSON.parse(trimmed);
        if (obj && typeof obj === "object") {
          out.push(normalizeResult(obj as Record<string, unknown>));
        }
      } catch {
        // skip unparseable lines
      }
    }
    return out;
  }

  function normalizeResult(obj: Record<string, unknown>): SearchResult {
    const raw = obj as Partial<SearchResult>;
    return {
      ...obj,
      id: String(raw.id ?? crypto.randomUUID()),
      content: String(raw.content ?? ""),
      source: String(raw.source ?? ""),
      entry_type: String(raw.entry_type ?? ""),
      score: typeof raw.score === "number" ? raw.score : 0,
      tags: Array.isArray(raw.tags) ? (raw.tags as string[]) : [],
    };
  }

  /** First line of content, truncated to 120 chars. */
  function contentPreview(content: string): string {
    const first = content.split("\n")[0] ?? content;
    return first.length > 120 ? first.slice(0, 120) + "…" : first;
  }

  /** Format a relevance score (0–1) as a percentage string. */
  function formatScore(score: number): string {
    return `${Math.round(score * 100)}%`;
  }

  async function runSearch() {
    const trimmedQuery = query.trim();
    if (!trimmedQuery) return;
    if (!bridge?.isConnected) return;

    loading = true;
    searchError = null;
    hasSearched = true;

    try {
      const args: Record<string, unknown> = {
        query: trimmedQuery,
        limit: 20,
      };
      if ($selectedProject) {
        args["project"] = $selectedProject;
      }
      const result = await bridge.callTool("distillery_recall", args);
      if (result.isError) {
        searchError = result.text || "Search failed";
        results = [];
        return;
      }
      results = parseResults(result.text);
    } catch (err) {
      searchError = err instanceof Error ? err.message : "Search failed";
      results = [];
    } finally {
      loading = false;
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Enter") {
      void runSearch();
    }
  }

  function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    void runSearch();
  }
</script>

<section class="search-bar" aria-labelledby="search-bar-heading">
  <h2 id="search-bar-heading" class="section-title">Search Knowledge Base</h2>

  <form class="search-form" onsubmit={handleSubmit} role="search" aria-label="Knowledge base search">
    <input
      class="search-input"
      type="search"
      placeholder="Search entries..."
      bind:value={query}
      onkeydown={handleKeydown}
      aria-label="Search query"
      disabled={loading}
    />
    <button
      class="search-button"
      type="submit"
      disabled={loading || !query.trim()}
      aria-label="Run search"
    >
      {loading ? "Searching…" : "Search"}
    </button>
  </form>

  {#if loading}
    <div class="loading-indicator" role="status" aria-live="polite" aria-label="Searching">
      Searching…
    </div>
  {:else if searchError}
    <div class="error-banner" role="alert">
      <strong>Error:</strong> {searchError}
    </div>
  {:else if hasSearched && results.length === 0}
    <p class="empty-state" role="status">No results found for your query.</p>
  {:else if results.length > 0}
    <ul class="results-list" aria-label="Search results" aria-live="polite">
      {#each results as result (result.id)}
        <li class="result-item">
          <div class="result-header">
            <span class="result-type">{result.entry_type || "entry"}</span>
            {#if result.source}
              <span class="result-source">{result.source}</span>
            {/if}
            <span class="result-score" aria-label={`Relevance: ${formatScore(result.score)}`}>
              {formatScore(result.score)}
            </span>
          </div>
          <p class="result-content">{contentPreview(result.content)}</p>
          {#if result.tags.length > 0}
            <div class="result-tags">
              {#each result.tags as tag (tag)}
                <span class="tag">{tag}</span>
              {/each}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .search-bar {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .section-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .search-form {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }

  .search-input {
    flex: 1;
    padding: 0.45rem 0.75rem;
    font-size: 0.9rem;
    background: var(--input-bg, #313244);
    color: var(--fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    min-width: 0;
  }

  .search-input::placeholder {
    color: var(--fg-muted, #a6adc8);
  }

  .search-input:focus {
    outline: 2px solid var(--accent, #89b4fa);
    outline-offset: 1px;
  }

  .search-input:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .search-button {
    padding: 0.45rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    background: color-mix(in srgb, var(--accent, #89b4fa) 20%, transparent);
    color: var(--accent, #89b4fa);
    border: 1px solid color-mix(in srgb, var(--accent, #89b4fa) 50%, transparent);
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
    white-space: nowrap;
  }

  .search-button:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent, #89b4fa) 35%, transparent);
  }

  .search-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .loading-indicator {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
    font-style: italic;
    padding: 0.5rem 0;
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
    margin: 0;
  }

  .results-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .result-item {
    background: color-mix(in srgb, var(--bg-highlight, #313244) 30%, transparent);
    border: 1px solid var(--border, #45475a);
    border-radius: 6px;
    padding: 0.75rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .result-header {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .result-type {
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--accent, #89b4fa);
    background: color-mix(in srgb, var(--accent, #89b4fa) 12%, transparent);
    border-radius: 3px;
    padding: 0.1rem 0.4rem;
  }

  .result-source {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .result-score {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--success, #a6e3a1);
    margin-left: auto;
  }

  .result-content {
    font-size: 0.875rem;
    color: var(--fg, #cdd6f4);
    line-height: 1.5;
    margin: 0;
    word-break: break-word;
  }

  .result-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
    margin-top: 0.15rem;
  }

  .tag {
    display: inline-block;
    padding: 0.1rem 0.4rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border-radius: 10px;
    font-size: 0.7rem;
    font-weight: 500;
  }
</style>
