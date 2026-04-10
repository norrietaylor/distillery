<script lang="ts">
  /**
   * InboxTriage — triage untyped inbox entries individually or in batch.
   *
   * Displays a DataTable of inbox entries (entry_type="inbox", status="active")
   * with per-row actions: Classify, Investigate, Archive.
   * Supports batch classification with progress indicator.
   */

  import { selectedProject, refreshTick, currentUser, activeTab } from "$lib/stores";
  import type { McpBridge } from "$lib/mcp-bridge";
  import { ENTRY_TYPES } from "$lib/entry-types";
  import LoadingSkeleton from "./LoadingSkeleton.svelte";

  interface Props {
    bridge: McpBridge;
  }

  let { bridge }: Props = $props();


  /** A single inbox entry as returned by the list tool. */
  interface InboxEntry {
    id: string;
    content: string;
    source: string;
    created_at: string;
    tags: string[];
    [key: string]: unknown;
  }

  /** State for the inline classify form. */
  interface ClassifyForm {
    entryId: string;
    entryType: string;
    confidence: number;
    reasoning: string;
  }

  let entries = $state<InboxEntry[]>([]);
  let loading = $state(false);
  let loadError = $state<string | null>(null);

  // Inline classify form — only one open at a time
  let classifyForm = $state<ClassifyForm | null>(null);
  let classifyLoading = $state(false);

  // Batch mode
  let selectedIds = $state<Set<string>>(new Set());
  let batchType = $state<string>("");
  let batchProcessing = $state(false);
  let batchProgress = $state<{ current: number; total: number } | null>(null);

  // Toast
  let toastMessage = $state<string | null>(null);
  let toastTimeout: ReturnType<typeof setTimeout> | null = null;

  // Archive confirmation
  let archiveConfirmId = $state<string | null>(null);
  let archiveLoading = $state(false);

  function showToast(message: string) {
    if (toastTimeout) clearTimeout(toastTimeout);
    toastMessage = message;
    toastTimeout = setTimeout(() => {
      toastMessage = null;
    }, 4000);
  }

  /** Content preview: first 80 chars. */
  function contentPreview(content: string): string {
    const first = content.split("\n")[0] ?? content;
    return first.length > 80 ? first.slice(0, 80) + "..." : first;
  }

  /** Format an ISO date string to a human-readable date. */
  function formatDate(iso: string): string {
    if (!iso) return "--";
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

  /** Parse JSON response text into InboxEntry array. */
  function parseEntries(text: string): InboxEntry[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed.map(normalizeEntry);
      }
      if (parsed && typeof parsed === "object") {
        return [normalizeEntry(parsed as Record<string, unknown>)];
      }
    } catch {
      // fall through to line-by-line
    }

    const results: InboxEntry[] = [];
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

  function normalizeEntry(obj: Record<string, unknown>): InboxEntry {
    const raw = obj as Partial<InboxEntry>;
    return {
      ...obj,
      id: String(raw.id ?? crypto.randomUUID()),
      content: String(raw.content ?? ""),
      source: String(raw.source ?? ""),
      created_at: String(raw.created_at ?? ""),
      tags: Array.isArray(raw.tags) ? (raw.tags as string[]) : [],
    };
  }

  async function loadEntries() {
    if (!bridge?.isConnected) return;
    loading = true;
    loadError = null;
    try {
      const args: Record<string, unknown> = {
        entry_type: "inbox",
        status: "active",
        limit: 50,
      };
      if ($selectedProject) {
        args["project"] = $selectedProject;
      }
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        loadError = result.text || "Failed to load inbox entries";
        entries = [];
        return;
      }
      entries = parseEntries(result.text);
      // Reset selection on reload
      selectedIds = new Set();
    } catch (err) {
      loadError = err instanceof Error ? err.message : "Failed to load inbox entries";
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

  // --- Classify actions ---

  function openClassifyForm(entryId: string) {
    classifyForm = {
      entryId,
      entryType: ENTRY_TYPES[0],
      confidence: 0.7,
      reasoning: "",
    };
  }

  function closeClassifyForm() {
    classifyForm = null;
  }

  async function applyClassify() {
    if (!classifyForm || classifyLoading) return;
    classifyLoading = true;
    try {
      const result = await bridge.callTool("distillery_classify", {
        entry_id: classifyForm.entryId,
        entry_type: classifyForm.entryType,
        confidence: classifyForm.confidence,
        reasoning: classifyForm.reasoning || undefined,
      });
      if (result.isError) {
        showToast(`Classification failed: ${result.text}`);
        return;
      }
      // Determine status from confidence
      const status = classifyForm.confidence >= 0.6 ? "active" : "pending_review";
      showToast(
        `Classified as ${classifyForm.entryType} (${status})`
      );
      // Remove classified entry from the table
      entries = entries.filter((e) => e.id !== classifyForm!.entryId);
      selectedIds.delete(classifyForm.entryId);
      selectedIds = new Set(selectedIds);
      closeClassifyForm();
    } catch (err) {
      showToast(`Classification failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      classifyLoading = false;
    }
  }

  // --- Investigate action ---

  function handleInvestigate(_entryId: string) {
    // Navigate to Explore tab
    activeTab.set("explore");
  }

  // --- Archive action ---

  function confirmArchive(entryId: string) {
    archiveConfirmId = entryId;
  }

  function cancelArchive() {
    archiveConfirmId = null;
  }

  async function executeArchive(entryId: string) {
    archiveLoading = true;
    try {
      const reviewer = $currentUser?.login ?? "user";
      const result = await bridge.callTool("distillery_resolve_review", {
        entry_id: entryId,
        action: "archive",
        reviewer,
      });
      if (result.isError) {
        showToast(`Archive failed: ${result.text}`);
        return;
      }
      showToast("Entry archived");
      entries = entries.filter((e) => e.id !== entryId);
      selectedIds.delete(entryId);
      selectedIds = new Set(selectedIds);
    } catch (err) {
      showToast(`Archive failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      archiveLoading = false;
      archiveConfirmId = null;
    }
  }

  // --- Batch mode ---

  function toggleSelect(entryId: string) {
    const next = new Set(selectedIds);
    if (next.has(entryId)) {
      next.delete(entryId);
    } else {
      next.add(entryId);
    }
    selectedIds = next;
  }

  function toggleSelectAll() {
    if (selectedIds.size === entries.length) {
      selectedIds = new Set();
    } else {
      selectedIds = new Set(entries.map((e) => e.id));
    }
  }

  let allSelected = $derived(entries.length > 0 && selectedIds.size === entries.length);

  async function batchClassify() {
    if (!batchType || selectedIds.size === 0 || batchProcessing) return;
    batchProcessing = true;
    const ids = Array.from(selectedIds);
    const total = ids.length;
    let failures = 0;

    for (let i = 0; i < ids.length; i++) {
      batchProgress = { current: i + 1, total };
      try {
        const result = await bridge.callTool("distillery_classify", {
          entry_id: ids[i],
          entry_type: batchType,
          confidence: 0.7,
        });
        if (result.isError) {
          failures++;
          continue;
        }
        entries = entries.filter((e) => e.id !== ids[i]);
      } catch {
        failures++;
      }
    }

    selectedIds = new Set();
    batchProgress = null;
    batchProcessing = false;

    if (failures > 0) {
      showToast(`Batch complete: ${total - failures} classified, ${failures} failed`);
    } else {
      showToast(`Batch complete: ${total} entries classified as ${batchType}`);
    }
  }
</script>

<section class="inbox-triage" aria-labelledby="inbox-triage-heading">
  <div class="section-header">
    <h2 id="inbox-triage-heading" class="section-title">Inbox Triage</h2>
  </div>

  {#if toastMessage}
    <div class="toast" role="status" aria-live="polite">
      {toastMessage}
    </div>
  {/if}

  {#if loading}
    <LoadingSkeleton rows={5} label="Loading inbox entries..." />
  {:else if loadError}
    <div class="error-banner" role="alert">
      <strong>Error:</strong> {loadError}
    </div>
  {:else if entries.length === 0}
    <p class="empty-state">
      Inbox is empty. New feed items and imports will appear here.
    </p>
  {:else}
    <!-- Batch controls -->
    <div class="batch-controls">
      <label class="batch-label">
        Classify all as...
        <select
          class="batch-select"
          bind:value={batchType}
          disabled={batchProcessing}
          aria-label="Batch classify type"
        >
          <option value="">-- Select type --</option>
          {#each ENTRY_TYPES as t (t)}
            <option value={t}>{t}</option>
          {/each}
        </select>
      </label>
      <button
        class="action-btn action-btn--primary"
        disabled={!batchType || selectedIds.size === 0 || batchProcessing}
        onclick={batchClassify}
      >
        {#if batchProcessing && batchProgress}
          Classifying {batchProgress.current} of {batchProgress.total}...
        {:else}
          Apply to {selectedIds.size} selected
        {/if}
      </button>
    </div>

    <!-- Data table -->
    <div class="datatable-scroll">
      <table class="datatable" role="grid" aria-label="Inbox entries">
        <thead>
          <tr>
            <th class="datatable-th datatable-th--checkbox">
              <input
                type="checkbox"
                checked={allSelected}
                onchange={toggleSelectAll}
                aria-label="Select all entries"
                disabled={batchProcessing}
              />
            </th>
            <th class="datatable-th">Preview</th>
            <th class="datatable-th">Source</th>
            <th class="datatable-th">Created Date</th>
            <th class="datatable-th">Tags</th>
            <th class="datatable-th">Actions</th>
          </tr>
        </thead>
        <tbody>
          {#each entries as entry (entry.id)}
            <tr class="datatable-row" data-entry-id={entry.id}>
              <td class="datatable-td datatable-td--checkbox">
                <input
                  type="checkbox"
                  checked={selectedIds.has(entry.id)}
                  onchange={() => toggleSelect(entry.id)}
                  aria-label="Select entry {entry.id}"
                  disabled={batchProcessing}
                />
              </td>
              <td class="datatable-td datatable-td--preview">
                {contentPreview(entry.content)}
              </td>
              <td class="datatable-td">{entry.source || "--"}</td>
              <td class="datatable-td">{formatDate(entry.created_at)}</td>
              <td class="datatable-td">{entry.tags.join(", ") || "--"}</td>
              <td class="datatable-td datatable-td--actions">
                <button
                  class="action-btn"
                  onclick={() => openClassifyForm(entry.id)}
                  disabled={batchProcessing}
                  aria-label="Classify entry"
                >
                  Classify
                </button>
                <button
                  class="action-btn"
                  onclick={() => handleInvestigate(entry.id)}
                  disabled={batchProcessing}
                  aria-label="Investigate entry"
                >
                  Investigate
                </button>
                {#if archiveConfirmId === entry.id}
                  <span class="confirm-prompt">
                    Archive?
                    <button
                      class="action-btn action-btn--danger"
                      onclick={() => executeArchive(entry.id)}
                      disabled={archiveLoading}
                      aria-label="Confirm archive"
                    >
                      Yes
                    </button>
                    <button
                      class="action-btn"
                      onclick={cancelArchive}
                      disabled={archiveLoading}
                      aria-label="Cancel archive"
                    >
                      No
                    </button>
                  </span>
                {:else}
                  <button
                    class="action-btn"
                    onclick={() => confirmArchive(entry.id)}
                    disabled={batchProcessing}
                    aria-label="Archive entry"
                  >
                    Archive
                  </button>
                {/if}
              </td>
            </tr>

            <!-- Inline classify form (expands below the row) -->
            {#if classifyForm && classifyForm.entryId === entry.id}
              <tr class="classify-form-row">
                <td colspan="6">
                  <div class="classify-form" aria-label="Classify form">
                    <label class="form-field">
                      Type
                      <select
                        class="form-select"
                        bind:value={classifyForm.entryType}
                        disabled={classifyLoading}
                        aria-label="Entry type"
                      >
                        {#each ENTRY_TYPES as t (t)}
                          <option value={t}>{t}</option>
                        {/each}
                      </select>
                    </label>
                    <label class="form-field">
                      Confidence
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        bind:value={classifyForm.confidence}
                        disabled={classifyLoading}
                        aria-label="Confidence"
                        class="confidence-slider"
                      />
                      <span class="confidence-value">
                        {classifyForm.confidence.toFixed(2)}
                      </span>
                    </label>
                    <label class="form-field form-field--wide">
                      Reasoning
                      <input
                        type="text"
                        class="form-input"
                        bind:value={classifyForm.reasoning}
                        disabled={classifyLoading}
                        placeholder="Optional reasoning..."
                        aria-label="Reasoning"
                      />
                    </label>
                    <div class="form-actions">
                      <button
                        class="action-btn action-btn--primary"
                        onclick={applyClassify}
                        disabled={classifyLoading}
                        aria-label="Apply classification"
                      >
                        {classifyLoading ? "Applying..." : "Apply"}
                      </button>
                      <button
                        class="action-btn"
                        onclick={closeClassifyForm}
                        disabled={classifyLoading}
                        aria-label="Cancel classification"
                      >
                        Cancel
                      </button>
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
  .inbox-triage {
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

  .empty-state {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
    font-style: italic;
    text-align: center;
    padding: 1.5rem 0;
  }

  .batch-controls {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .batch-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
    color: var(--fg-muted, #a6adc8);
  }

  .batch-select {
    padding: 0.3rem 0.5rem;
    font-size: 0.85rem;
    background: var(--input-bg, #313244);
    color: var(--fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
  }

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

  .datatable-th--checkbox {
    width: 2rem;
    text-align: center;
  }

  .datatable-row {
    border-bottom: 1px solid var(--border, #313244);
    transition: background 0.1s;
  }

  .datatable-row:hover {
    background: var(--row-hover, #313244);
  }

  .datatable-td {
    padding: 0.55rem 0.75rem;
    vertical-align: middle;
    color: var(--fg, #cdd6f4);
  }

  .datatable-td--checkbox {
    text-align: center;
    width: 2rem;
  }

  .datatable-td--preview {
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .datatable-td--actions {
    white-space: nowrap;
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }

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

  .action-btn--primary {
    background: color-mix(in srgb, var(--accent, #89b4fa) 20%, transparent);
    border-color: color-mix(in srgb, var(--accent, #89b4fa) 50%, transparent);
    color: var(--accent, #89b4fa);
  }

  .action-btn--primary:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent, #89b4fa) 35%, transparent);
  }

  .action-btn--danger {
    background: color-mix(in srgb, var(--error, #f38ba8) 20%, transparent);
    border-color: color-mix(in srgb, var(--error, #f38ba8) 50%, transparent);
    color: var(--error, #f38ba8);
  }

  .confirm-prompt {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.75rem;
    color: var(--fg-muted, #a6adc8);
  }

  /* Inline classify form */
  .classify-form-row {
    background: color-mix(in srgb, var(--accent, #89b4fa) 5%, transparent);
  }

  .classify-form {
    display: flex;
    align-items: flex-end;
    gap: 1rem;
    padding: 0.75rem;
    flex-wrap: wrap;
  }

  .form-field {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
  }

  .form-field--wide {
    flex: 1;
    min-width: 150px;
  }

  .form-select {
    padding: 0.3rem 0.5rem;
    font-size: 0.8rem;
    background: var(--input-bg, #313244);
    color: var(--fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
  }

  .form-input {
    padding: 0.3rem 0.5rem;
    font-size: 0.8rem;
    background: var(--input-bg, #313244);
    color: var(--fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    width: 100%;
  }

  .form-input::placeholder {
    color: var(--fg-muted, #a6adc8);
  }

  .confidence-slider {
    width: 120px;
    accent-color: var(--accent, #89b4fa);
  }

  .confidence-value {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    min-width: 2.5rem;
    text-align: right;
  }

  .form-actions {
    display: flex;
    gap: 0.5rem;
    align-items: flex-end;
  }
</style>
