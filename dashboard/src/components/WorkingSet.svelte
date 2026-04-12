<script lang="ts">
  /**
   * WorkingSet — collapsible bottom panel showing pinned entries.
   *
   * Renders a compact list of pinned knowledge entries with support for:
   *  - Collapsing and expanding the panel
   *  - Drag-to-reorder via HTML5 drag-and-drop
   *  - Removing individual entries
   *  - Clearing all entries with a confirmation step
   *  - Exporting (delegated to parent via onExport callback)
   *
   * The panel header always shows the current count badge.
   * When entries is empty the panel auto-collapses.
   */

  import type { PinnedEntry } from "$lib/stores";

  interface Props {
    /** Current pinned entries (passed from parent subscribing to workingSet store). */
    entries: PinnedEntry[];
    /** Called when the user removes a single entry by id. */
    onRemove: (id: string) => void;
    /** Called when the user drags an entry to a new position. */
    onReorder: (fromIndex: number, toIndex: number) => void;
    /** Called when the user clicks Export. */
    onExport: () => void;
    /** Called when the user confirms Clear all. */
    onClear: () => void;
  }

  let { entries, onRemove, onReorder, onExport, onClear }: Props = $props();

  /** Whether the panel body is visible. */
  let expanded = $state(false);

  /** Whether we've done the initial auto-expand based on props. */
  let initialized = $state(false);

  // Auto-expand on first render if entries are already present.
  $effect(() => {
    if (!initialized) {
      initialized = true;
      if (entries.length > 0) {
        expanded = true;
      }
    }
  });

  /** Whether the "Confirm clear?" prompt is showing. */
  let confirmingClear = $state(false);

  /** Index of the card being dragged, or null. */
  let dragFromIndex = $state<number | null>(null);

  /** Index of the card currently being dragged over. */
  let dragOverIndex = $state<number | null>(null);

  // When entries become empty, collapse and reset confirmation state.
  $effect(() => {
    if (entries.length === 0) {
      expanded = false;
      confirmingClear = false;
    }
  });

  function toggleExpanded() {
    if (entries.length === 0) return; // nothing to expand
    expanded = !expanded;
    if (!expanded) confirmingClear = false;
  }

  function handleRemove(id: string) {
    onRemove(id);
  }

  function requestClear() {
    confirmingClear = true;
  }

  function cancelClear() {
    confirmingClear = false;
  }

  function confirmClear() {
    confirmingClear = false;
    onClear();
  }

  // ---------------------------------------------------------------------------
  // Drag-and-drop handlers
  // ---------------------------------------------------------------------------

  function handleDragStart(event: DragEvent, index: number) {
    dragFromIndex = index;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(index));
    }
  }

  function handleDragOver(event: DragEvent, index: number) {
    event.preventDefault();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = "move";
    }
    dragOverIndex = index;
  }

  function handleDragLeave() {
    dragOverIndex = null;
  }

  function handleDrop(event: DragEvent, toIndex: number) {
    event.preventDefault();
    if (dragFromIndex !== null && dragFromIndex !== toIndex) {
      onReorder(dragFromIndex, toIndex);
    }
    dragFromIndex = null;
    dragOverIndex = null;
  }

  function handleDragEnd() {
    dragFromIndex = null;
    dragOverIndex = null;
  }

  /** Return first 80 chars of title for compact display. */
  function truncateTitle(title: string): string {
    return title.length > 80 ? title.slice(0, 80) + "…" : title;
  }
</script>

<div class="working-set" class:expanded aria-label="Working set panel">
  <!-- Panel header / toggle -->
  <div class="ws-header">
    <button
      class="ws-toggle"
      type="button"
      onclick={toggleExpanded}
      aria-expanded={expanded}
      aria-controls="working-set-body"
      aria-label={`Working Set (${entries.length})`}
      disabled={entries.length === 0}
    >
      <span class="ws-title">Working Set</span>
      <span class="ws-badge" aria-label={`${entries.length} entries`}>{entries.length}</span>
      {#if entries.length > 0}
        <span class="ws-chevron" aria-hidden="true">{expanded ? "▲" : "▼"}</span>
      {/if}
    </button>

    {#if expanded && entries.length > 0}
      <div class="ws-actions" role="group" aria-label="Working set actions">
        <button
          class="ws-action-btn ws-export-btn"
          type="button"
          onclick={onExport}
          aria-label="Export working set"
        >
          Export
        </button>

        {#if confirmingClear}
          <span class="ws-confirm-text" aria-live="polite">Clear all?</span>
          <button
            class="ws-action-btn ws-confirm-btn"
            type="button"
            onclick={confirmClear}
            aria-label="Confirm clear all"
          >
            Yes
          </button>
          <button
            class="ws-action-btn ws-cancel-btn"
            type="button"
            onclick={cancelClear}
            aria-label="Cancel clear"
          >
            No
          </button>
        {:else}
          <button
            class="ws-action-btn ws-clear-btn"
            type="button"
            onclick={requestClear}
            aria-label="Clear all entries"
          >
            Clear all
          </button>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Panel body -->
  {#if expanded && entries.length > 0}
    <div id="working-set-body" class="ws-body" role="list" aria-label="Pinned entries">
      {#each entries as entry, index (entry.id)}
        <div
          class="ws-card"
          class:drag-over={dragOverIndex === index}
          class:dragging={dragFromIndex === index}
          role="listitem"
          draggable="true"
          aria-label={`Pinned entry: ${entry.title}`}
          ondragstart={(e) => handleDragStart(e, index)}
          ondragover={(e) => handleDragOver(e, index)}
          ondragleave={handleDragLeave}
          ondrop={(e) => handleDrop(e, index)}
          ondragend={handleDragEnd}
        >
          <span class="ws-card-grip" aria-hidden="true">⠿</span>

          <span class="ws-card-type">{entry.type}</span>

          <span class="ws-card-title" title={entry.title}>
            {truncateTitle(entry.title)}
          </span>

          <button
            class="ws-card-remove"
            type="button"
            onclick={() => handleRemove(entry.id)}
            aria-label={`Remove ${entry.title} from working set`}
          >
            ✕
          </button>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .working-set {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 100;
    background: var(--bg-surface, #1e1e2e);
    border-top: 1px solid var(--border, #45475a);
    box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.3);
    transition: box-shadow 0.15s;
  }

  .working-set.expanded {
    box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.4);
  }

  /* Header row */
  .ws-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 1rem;
    min-height: 2.25rem;
  }

  .ws-toggle {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    background: none;
    border: none;
    cursor: pointer;
    padding: 0.2rem 0.4rem;
    border-radius: 4px;
    color: var(--fg, #cdd6f4);
    font-size: 0.875rem;
    font-weight: 600;
    transition: background 0.1s;
  }

  .ws-toggle:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent, #89b4fa) 10%, transparent);
  }

  .ws-toggle:disabled {
    cursor: default;
    opacity: 0.6;
  }

  .ws-title {
    white-space: nowrap;
  }

  .ws-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.25rem;
    height: 1.25rem;
    padding: 0 0.3rem;
    background: var(--accent, #89b4fa);
    color: var(--bg, #1e1e2e);
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 700;
    line-height: 1;
  }

  .ws-chevron {
    font-size: 0.65rem;
    color: var(--fg-muted, #a6adc8);
  }

  /* Action buttons */
  .ws-actions {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-left: auto;
  }

  .ws-action-btn {
    padding: 0.2rem 0.6rem;
    font-size: 0.8rem;
    border-radius: 4px;
    border: 1px solid var(--border, #45475a);
    cursor: pointer;
    transition: background 0.1s;
    white-space: nowrap;
  }

  .ws-export-btn {
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border-color: color-mix(in srgb, var(--accent, #89b4fa) 40%, transparent);
  }

  .ws-export-btn:hover {
    background: color-mix(in srgb, var(--accent, #89b4fa) 30%, transparent);
  }

  .ws-clear-btn {
    background: none;
    color: var(--fg-muted, #a6adc8);
  }

  .ws-clear-btn:hover {
    color: var(--error, #f38ba8);
    border-color: var(--error, #f38ba8);
  }

  .ws-confirm-text {
    font-size: 0.8rem;
    color: var(--error, #f38ba8);
    white-space: nowrap;
  }

  .ws-confirm-btn {
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    color: var(--error, #f38ba8);
    border-color: color-mix(in srgb, var(--error, #f38ba8) 40%, transparent);
  }

  .ws-confirm-btn:hover {
    background: color-mix(in srgb, var(--error, #f38ba8) 30%, transparent);
  }

  .ws-cancel-btn {
    background: none;
    color: var(--fg-muted, #a6adc8);
  }

  .ws-cancel-btn:hover {
    color: var(--fg, #cdd6f4);
  }

  /* Panel body */
  .ws-body {
    display: flex;
    flex-direction: row;
    flex-wrap: wrap;
    gap: 0.4rem;
    padding: 0.5rem 1rem 0.75rem;
    max-height: 12rem;
    overflow-y: auto;
    border-top: 1px solid var(--border, #45475a);
  }

  /* Compact entry card */
  .ws-card {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.3rem 0.5rem;
    background: color-mix(in srgb, var(--bg-highlight, #313244) 60%, transparent);
    border: 1px solid var(--border, #45475a);
    border-radius: 5px;
    cursor: grab;
    user-select: none;
    transition:
      background 0.1s,
      border-color 0.1s,
      opacity 0.1s;
    max-width: 280px;
  }

  .ws-card:active {
    cursor: grabbing;
  }

  .ws-card.dragging {
    opacity: 0.45;
  }

  .ws-card.drag-over {
    border-color: var(--accent, #89b4fa);
    background: color-mix(in srgb, var(--accent, #89b4fa) 10%, transparent);
  }

  .ws-card-grip {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    cursor: grab;
    flex-shrink: 0;
  }

  .ws-card-type {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--accent, #89b4fa);
    background: color-mix(in srgb, var(--accent, #89b4fa) 12%, transparent);
    border-radius: 3px;
    padding: 0.1rem 0.3rem;
    flex-shrink: 0;
  }

  .ws-card-title {
    font-size: 0.8rem;
    color: var(--fg, #cdd6f4);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    min-width: 0;
  }

  .ws-card-remove {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--fg-muted, #a6adc8);
    font-size: 0.75rem;
    padding: 0.1rem 0.2rem;
    border-radius: 3px;
    line-height: 1;
    flex-shrink: 0;
    transition: color 0.1s;
  }

  .ws-card-remove:hover {
    color: var(--error, #f38ba8);
  }
</style>
