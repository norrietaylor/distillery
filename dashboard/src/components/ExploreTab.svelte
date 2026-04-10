<script lang="ts">
  /**
   * ExploreTab — two-panel search and exploration view.
   *
   * Layout:
   *   Left panel  — SearchBar (query input) + ResultsList (paginated table)
   *   Right panel — Entry detail placeholder (or selected-entry detail)
   *
   * State managed here:
   *   currentQuery    — submitted search query string
   *   isSearchMode    — true once a search has been submitted
   *   selectedEntryId — id of the row the user clicked; drives detail panel
   *   $refreshTick    — any change triggers a re-submit of the current query
   *   $selectedProject — forwarded to ResultsList for project-scoped recall
   */

  import type { McpBridge } from "$lib/mcp-bridge";
  import { selectedProject, refreshTick } from "$lib/stores";
  import SearchBar from "./SearchBar.svelte";
  import ResultsList from "./ResultsList.svelte";

  interface Props {
    bridge?: McpBridge | null;
  }

  let { bridge = null }: Props = $props();

  /** The query string that has been submitted and is active for ResultsList. */
  let currentQuery = $state("");

  /** Whether the user has submitted at least one search. */
  let isSearchMode = $state(false);

  /** ID of the entry selected from the results table. */
  let selectedEntryId = $state<string | null>(null);

  /** Draft query the user is typing (bound to the input). */
  let draftQuery = $state("");

  /** Track refresh ticks so we can re-submit the current query when it fires. */
  let lastRefreshTick = $state(0);

  // When refreshTick changes (auto-refresh or manual trigger), resubmit the
  // active query so results stay current.
  $effect(() => {
    const tick = $refreshTick;
    if (tick > lastRefreshTick && isSearchMode && currentQuery) {
      lastRefreshTick = tick;
      // Force ResultsList to re-fetch by toggling query off/on.
      // We reassign to trigger Svelte reactivity.
      const q = currentQuery;
      currentQuery = "";
      // Use a microtask to let Svelte process the empty assignment first.
      void Promise.resolve().then(() => {
        currentQuery = q;
      });
    } else {
      lastRefreshTick = tick;
    }
  });

  function submitSearch() {
    const trimmed = draftQuery.trim();
    if (!trimmed) return;
    currentQuery = trimmed;
    isSearchMode = true;
    selectedEntryId = null;
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Enter") {
      submitSearch();
    }
  }

  function handleFormSubmit(event: SubmitEvent) {
    event.preventDefault();
    submitSearch();
  }

  function clearSearch() {
    draftQuery = "";
    currentQuery = "";
    isSearchMode = false;
    selectedEntryId = null;
  }
</script>

<section id="explore" class="explore-section" aria-label="Explore knowledge base">
  <div class="explore-grid">
    <!-- Left panel: search input + results -->
    <div class="left-panel">
      <div class="search-panel" aria-labelledby="explore-search-heading">
        <h2 id="explore-search-heading" class="panel-title">Search Knowledge Base</h2>

        <form
          class="search-form"
          onsubmit={handleFormSubmit}
          role="search"
          aria-label="Explore search"
        >
          <input
            class="search-input"
            type="search"
            placeholder="Search entries…"
            bind:value={draftQuery}
            onkeydown={handleKeydown}
            aria-label="Search query"
          />
          <button
            class="search-btn"
            type="submit"
            disabled={!draftQuery.trim()}
            aria-label="Submit search"
          >
            Search
          </button>
          {#if isSearchMode}
            <button
              class="clear-btn"
              type="button"
              onclick={clearSearch}
              aria-label="Clear search"
            >
              Clear
            </button>
          {/if}
        </form>

        {#if $selectedProject}
          <p class="project-filter-note" aria-live="polite">
            Filtering by project: <strong>{$selectedProject}</strong>
          </p>
        {/if}
      </div>

      <div class="results-panel">
        <ResultsList {bridge} query={currentQuery} />
      </div>
    </div>

    <!-- Right panel: entry detail or placeholder -->
    <aside class="right-panel" aria-label="Entry detail">
      {#if selectedEntryId}
        <div class="detail-placeholder">
          <p class="detail-hint">Entry <code>{selectedEntryId}</code> selected.</p>
          <p class="detail-hint-sub">Detail view coming soon.</p>
        </div>
      {:else if isSearchMode}
        <div class="detail-placeholder">
          <p class="detail-hint">Select an entry from the results to view details.</p>
        </div>
      {:else}
        <div class="detail-placeholder">
          <h3 class="detail-placeholder-title">Entry Detail</h3>
          <p class="detail-hint">Run a search to explore the knowledge base.</p>
        </div>
      {/if}
    </aside>
  </div>
</section>

<style>
  .explore-section {
    height: 100%;
  }

  /* Two-panel responsive grid */
  .explore-grid {
    display: grid;
    grid-template-columns: 1fr 320px;
    gap: 1.25rem;
    align-items: start;
  }

  @media (max-width: 768px) {
    .explore-grid {
      grid-template-columns: 1fr;
    }

    .right-panel {
      order: -1;
    }
  }

  /* Left panel */
  .left-panel {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    min-width: 0;
  }

  /* Search input area */
  .search-panel {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 1rem;
    background: color-mix(in srgb, var(--bg-highlight, #313244) 30%, transparent);
    border: 1px solid var(--border, #45475a);
    border-radius: 8px;
  }

  .panel-title {
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

  .search-btn {
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

  .search-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent, #89b4fa) 35%, transparent);
  }

  .search-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .clear-btn {
    padding: 0.45rem 0.75rem;
    font-size: 0.875rem;
    background: none;
    color: var(--fg-muted, #a6adc8);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    cursor: pointer;
    white-space: nowrap;
  }

  .clear-btn:hover {
    color: var(--fg, #cdd6f4);
    border-color: var(--fg-muted, #a6adc8);
  }

  .project-filter-note {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    margin: 0;
  }

  .project-filter-note strong {
    color: var(--accent, #89b4fa);
  }

  /* Results panel */
  .results-panel {
    min-width: 0;
  }

  /* Right panel */
  .right-panel {
    position: sticky;
    top: 1rem;
    background: color-mix(in srgb, var(--bg-highlight, #313244) 20%, transparent);
    border: 1px solid var(--border, #45475a);
    border-radius: 8px;
    padding: 1.25rem;
    min-height: 200px;
  }

  .detail-placeholder {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    align-items: center;
    justify-content: center;
    min-height: 160px;
    text-align: center;
  }

  .detail-placeholder-title {
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0 0 0.25rem;
  }

  .detail-hint {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
    margin: 0;
  }

  .detail-hint code {
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 10%, transparent);
    color: var(--accent, #89b4fa);
    padding: 0.1rem 0.35rem;
    border-radius: 3px;
  }

  .detail-hint-sub {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.8rem;
    font-style: italic;
    margin: 0;
  }
</style>
