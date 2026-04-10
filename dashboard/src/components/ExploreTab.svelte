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
  import { selectedProject, refreshTick, pinEntry, workingSet, unpinEntry, clearWorkingSet, reorderEntries } from "$lib/stores";
  import SearchBar from "./SearchBar.svelte";
  import ResultsList from "./ResultsList.svelte";
  import EntryDetail from "./EntryDetail.svelte";
  import InvestigateMode from "./InvestigateMode.svelte";
  import WorkingSet from "./WorkingSet.svelte";

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

  /** Whether the detail panel is visible (used for responsive slide-over). */
  let detailPanelOpen = $state(false);

  /** Whether the user has triggered investigate mode. */
  let investigateMode = $state(false);

  /** Seed entry data for investigation mode. */
  let investigateSeed = $state<{ id: string; title: string; content: string } | null>(null);

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
    detailPanelOpen = false;
  }

  function handleEntrySelect(entryId: string) {
    selectedEntryId = entryId;
    detailPanelOpen = true;
  }

  function handleTagClick(tag: string) {
    // Add tag as a search filter by prepending "tag:" to the query.
    draftQuery = `tag:${tag}`;
    submitSearch();
  }

  function handleInvestigate(entryId: string) {
    investigateSeed = {
      id: entryId,
      title: currentQuery || "Entry " + entryId.slice(0, 8),
      content: currentQuery || entryId,
    };
    investigateMode = true;
  }

  function exitInvestigateMode() {
    investigateMode = false;
    investigateSeed = null;
  }

  function handleInvestigatePin(entry: { id: string; title: string; type: string; content: string }) {
    pinEntry({
      id: entry.id,
      title: entry.title,
      type: entry.type,
      content: entry.content,
      pinnedAt: new Date().toISOString(),
    });
  }

  function closeDetailPanel() {
    detailPanelOpen = false;
  }

  // ---------------------------------------------------------------------------
  // Export helpers
  // ---------------------------------------------------------------------------

  /** Generate a markdown string from the current working set. */
  function generateMarkdown(): string {
    const entries = $workingSet;
    if (entries.length === 0) return "";

    const lines: string[] = [];
    lines.push("# Working Set Export\n");
    lines.push(`_Exported ${new Date().toISOString()}_\n`);

    for (const entry of entries) {
      lines.push(`## ${entry.title}`);
      lines.push(`**Type:** ${entry.type}`);
      lines.push("");
      lines.push(entry.content);
      lines.push("");
      lines.push("---\n");
    }

    return lines.join("\n");
  }

  async function handleExport(): Promise<void> {
    const md = generateMarkdown();
    if (!md) return;

    // Show a simple modal-like options via the export sub-state.
    exportMarkdown = md;
    exportOpen = true;
  }

  async function copyToClipboard(): Promise<void> {
    if (!exportMarkdown) return;
    try {
      await navigator.clipboard.writeText(exportMarkdown);
      exportCopied = true;
      setTimeout(() => { exportCopied = false; }, 2000);
    } catch {
      // fallback: do nothing — clipboard API may be unavailable in some contexts
    }
  }

  function downloadMarkdown(): void {
    if (!exportMarkdown) return;
    const blob = new Blob([exportMarkdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "working-set.md";
    a.click();
    URL.revokeObjectURL(url);
  }

  function closeExport(): void {
    exportOpen = false;
    exportMarkdown = "";
  }

  /** Whether the export dialog is open. */
  let exportOpen = $state(false);
  /** Generated markdown for the current export. */
  let exportMarkdown = $state("");
  /** Whether the clipboard copy succeeded recently. */
  let exportCopied = $state(false);
</script>

<section id="explore" class="explore-section" aria-label="Explore knowledge base">
  <div class="explore-grid">
    <!-- Left panel: search input + results OR investigation mode -->
    <div class="left-panel">
      {#if investigateMode && investigateSeed}
        <InvestigateMode
          {bridge}
          seedEntryId={investigateSeed.id}
          seedTitle={investigateSeed.title}
          seedContent={investigateSeed.content}
          onExit={exitInvestigateMode}
          onPin={handleInvestigatePin}
        />
      {:else}
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
          <ResultsList {bridge} query={currentQuery} onRowClick={handleEntrySelect} />
        </div>
      {/if}
    </div>

    <!-- Right panel: entry detail -->
    <aside
      class="right-panel"
      class:right-panel--open={detailPanelOpen}
      aria-label="Entry detail"
    >
      <!-- Slide-over close button (visible only on narrow viewports) -->
      {#if detailPanelOpen}
        <button
          class="panel-close-btn"
          onclick={closeDetailPanel}
          aria-label="Close detail panel"
        >
          &times;
        </button>
      {/if}

      <EntryDetail
        {bridge}
        entryId={selectedEntryId}
        onTagClick={handleTagClick}
        onInvestigate={handleInvestigate}
        onNavigate={handleEntrySelect}
      />

    </aside>
  </div>

  <!-- Working Set panel — spans full width below both panels -->
  <WorkingSet
    entries={$workingSet}
    onRemove={unpinEntry}
    onReorder={reorderEntries}
    onExport={handleExport}
    onClear={clearWorkingSet}
  />

  <!-- Export dialog -->
  {#if exportOpen}
    <div class="export-overlay" role="dialog" aria-modal="true" aria-label="Export working set">
      <div class="export-dialog">
        <div class="export-header">
          <h3 class="export-title">Export Working Set</h3>
          <button class="export-close-btn" onclick={closeExport} aria-label="Close export dialog">
            &times;
          </button>
        </div>
        <pre class="export-preview">{exportMarkdown}</pre>
        <div class="export-actions">
          <button class="export-action-btn" onclick={copyToClipboard} aria-label="Copy to clipboard">
            {exportCopied ? "Copied!" : "Copy to Clipboard"}
          </button>
          <button class="export-action-btn" onclick={downloadMarkdown} aria-label="Download as markdown">
            Download .md
          </button>
        </div>
      </div>
    </div>
  {/if}
</section>

<style>
  .explore-section {
    height: 100%;
  }

  /* Two-panel responsive grid */
  .explore-grid {
    display: grid;
    grid-template-columns: 1fr 360px;
    gap: 1.25rem;
    align-items: start;
    position: relative;
  }

  /* At < 1024px, right panel becomes a slide-over overlay */
  @media (max-width: 1023px) {
    .explore-grid {
      grid-template-columns: 1fr;
    }

    .right-panel {
      position: fixed;
      top: 0;
      right: 0;
      height: 100%;
      width: min(400px, 90vw);
      z-index: 200;
      overflow-y: auto;
      transform: translateX(100%);
      transition: transform 0.25s ease;
      box-shadow: -4px 0 24px rgba(0, 0, 0, 0.4);
    }

    .right-panel--open {
      transform: translateX(0);
    }
  }

  @media (min-width: 1024px) {
    .panel-close-btn {
      display: none;
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

  /* Slide-over close button */
  .panel-close-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    background: none;
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    color: var(--fg-muted, #a6adc8);
    font-size: 1.25rem;
    cursor: pointer;
    margin-bottom: 0.75rem;
  }

  .panel-close-btn:hover {
    color: var(--fg, #cdd6f4);
    border-color: var(--fg-muted, #a6adc8);
  }

  /* Export dialog overlay */
  .export-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    z-index: 300;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }

  .export-dialog {
    background: var(--bg-surface, #1e1e2e);
    border: 1px solid var(--border, #45475a);
    border-radius: 8px;
    width: min(700px, 90vw);
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .export-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border, #45475a);
  }

  .export-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .export-close-btn {
    background: none;
    border: none;
    color: var(--fg-muted, #a6adc8);
    font-size: 1.25rem;
    cursor: pointer;
    padding: 0 0.25rem;
    line-height: 1;
  }

  .export-close-btn:hover {
    color: var(--fg, #cdd6f4);
  }

  .export-preview {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
    line-height: 1.5;
    color: var(--fg, #cdd6f4);
    white-space: pre-wrap;
    word-break: break-word;
    background: var(--code-bg, #11111b);
    margin: 0;
  }

  .export-actions {
    display: flex;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    border-top: 1px solid var(--border, #45475a);
    justify-content: flex-end;
  }

  .export-action-btn {
    padding: 0.4rem 0.9rem;
    font-size: 0.875rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border: 1px solid color-mix(in srgb, var(--accent, #89b4fa) 40%, transparent);
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
  }

  .export-action-btn:hover {
    background: color-mix(in srgb, var(--accent, #89b4fa) 30%, transparent);
  }

</style>
