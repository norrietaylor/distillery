<script lang="ts">
  /**
   * ReviewQueue — manages entries flagged as pending_review.
   *
   * Displays a DataTable of pending_review entries with columns:
   *   - Preview (first 80 chars of content)
   *   - Type (current assigned type)
   *   - Confidence (color-coded badge: red <0.4, yellow 0.4-0.7, green >0.7)
   *   - Classified At
   *   - Actions (Approve, Reclassify, Archive)
   *
   * Row expansion shows classification metadata: confidence, reasoning,
   * classified_at, and suggested_project.
   *
   * Supports batch approve with checkbox selection and sequential processing
   * with a progress indicator.
   */

  import type { McpBridge } from "$lib/mcp-bridge";
  import { selectedProject, refreshTick, currentUser } from "$lib/stores";
  import { ENTRY_TYPES } from "$lib/entry-types";
  import LoadingSkeleton from "./LoadingSkeleton.svelte";

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge?: McpBridge | null;
  }

  let { bridge = null }: Props = $props();

  /** A single review queue entry as returned by the list tool. */
  interface ReviewEntry {
    id: string;
    content: string;
    entry_type: string;
    confidence: number;
    classified_at: string;
    reasoning: string;
    suggested_project: string | null;
    [key: string]: unknown;
  }


  let entries = $state<ReviewEntry[]>([]);
  let loading = $state(false);
  let loadError = $state<string | null>(null);

  /** Which row is currently expanded (showing metadata). */
  let expandedId = $state<string | null>(null);

  /** Which row has reclassify form open. Only one at a time. */
  let reclassifyId = $state<string | null>(null);

  /** Selected type for reclassify inline form. */
  let reclassifyType = $state<string>("");

  /** Per-row action status. */
  type ActionStatus = "idle" | "loading" | "success" | "error";
  let actionStatus = $state<Record<string, ActionStatus>>({});

  /** Per-row toast message. */
  let toastMsg = $state<Record<string, string>>({});

  /** Archive confirmation: id of entry awaiting confirmation, or null. */
  let archiveConfirmId = $state<string | null>(null);

  /** Batch selection: set of selected entry ids. */
  let selectedIds = $state<Set<string>>(new Set());

  /** Batch processing state. */
  let batchProcessing = $state(false);
  let batchProgress = $state<{ current: number; total: number } | null>(null);
  let batchErrors = $state<string[]>([]);

  /** Content preview: first 80 chars. */
  function contentPreview(content: string): string {
    const first = content.split("\n")[0] ?? content;
    return first.length > 80 ? first.slice(0, 80) + "\u2026" : first;
  }

  /** Format an ISO date string to a readable date. */
  function formatDate(iso: string): string {
    if (!iso) return "\u2014";
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

  /** Confidence badge tier for color-coding. */
  function confidenceTier(conf: number): "red" | "yellow" | "green" {
    if (conf < 0.4) return "red";
    if (conf <= 0.7) return "yellow";
    return "green";
  }

  /** Parse list tool output (newline-delimited JSON or JSON array). */
  function parseEntries(text: string): ReviewEntry[] {
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
      // fall through to line-by-line parsing
    }
    const results: ReviewEntry[] = [];
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

  function normalizeEntry(obj: Record<string, unknown>): ReviewEntry {
    const raw = obj as Partial<ReviewEntry>;
    return {
      ...obj,
      id: String(raw.id ?? crypto.randomUUID()),
      content: String(raw.content ?? ""),
      entry_type: String(raw.entry_type ?? ""),
      confidence: typeof raw.confidence === "number" ? raw.confidence : 0,
      classified_at: String(raw.classified_at ?? ""),
      reasoning: String(raw.reasoning ?? ""),
      suggested_project: typeof raw.suggested_project === "string"
        ? raw.suggested_project
        : null,
    };
  }

  async function loadEntries() {
    if (!bridge?.isConnected) return;
    loading = true;
    loadError = null;
    try {
      const args: Record<string, unknown> = {
        status: "pending_review",
        limit: 50,
      };
      if ($selectedProject) {
        args["project"] = $selectedProject;
      }
      const result = await bridge.callTool("distillery_list", args);
      if (result.isError) {
        loadError = result.text || "Failed to load review queue";
        entries = [];
        return;
      }
      entries = parseEntries(result.text);
    } catch (err) {
      loadError = err instanceof Error ? err.message : "Failed to load review queue";
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

  /** Reviewer identity from OAuth context. */
  let reviewer = $derived($currentUser?.login ?? "user");

  /** Remove a row from entries after a successful action. */
  function removeEntry(id: string) {
    entries = entries.filter((e) => e.id !== id);
    selectedIds = new Set([...selectedIds].filter((sid) => sid !== id));
  }

  async function handleApprove(entry: ReviewEntry) {
    if (!bridge?.isConnected) return;
    actionStatus = { ...actionStatus, [entry.id]: "loading" };
    try {
      const result = await bridge.callTool("distillery_resolve_review", {
        entry_id: entry.id,
        action: "approve",
        reviewer,
      });
      if (result.isError) {
        actionStatus = { ...actionStatus, [entry.id]: "error" };
        toastMsg = { ...toastMsg, [entry.id]: result.text || "Approve failed" };
      } else {
        actionStatus = { ...actionStatus, [entry.id]: "success" };
        toastMsg = { ...toastMsg, [entry.id]: "Approved" };
        removeEntry(entry.id);
      }
    } catch (err) {
      actionStatus = { ...actionStatus, [entry.id]: "error" };
      toastMsg = {
        ...toastMsg,
        [entry.id]: err instanceof Error ? err.message : "Approve failed",
      };
    }
  }

  function handleReclassifyOpen(entry: ReviewEntry) {
    reclassifyId = entry.id;
    reclassifyType = entry.entry_type || ENTRY_TYPES[0] || "";
    expandedId = null; // close expansion when reclassify opens
  }

  function handleReclassifyCancel() {
    reclassifyId = null;
    reclassifyType = "";
  }

  async function handleReclassifySubmit(entry: ReviewEntry) {
    if (!bridge?.isConnected) return;
    actionStatus = { ...actionStatus, [entry.id]: "loading" };
    try {
      const result = await bridge.callTool("distillery_resolve_review", {
        entry_id: entry.id,
        action: "reclassify",
        new_entry_type: reclassifyType,
        reviewer,
      });
      if (result.isError) {
        actionStatus = { ...actionStatus, [entry.id]: "error" };
        toastMsg = { ...toastMsg, [entry.id]: result.text || "Reclassify failed" };
      } else {
        actionStatus = { ...actionStatus, [entry.id]: "success" };
        toastMsg = { ...toastMsg, [entry.id]: `Reclassified as ${reclassifyType}` };
        reclassifyId = null;
        removeEntry(entry.id);
      }
    } catch (err) {
      actionStatus = { ...actionStatus, [entry.id]: "error" };
      toastMsg = {
        ...toastMsg,
        [entry.id]: err instanceof Error ? err.message : "Reclassify failed",
      };
    }
  }

  function handleArchiveConfirm(entry: ReviewEntry) {
    archiveConfirmId = entry.id;
  }

  function handleArchiveCancel() {
    archiveConfirmId = null;
  }

  async function handleArchive(entry: ReviewEntry) {
    if (!bridge?.isConnected) return;
    archiveConfirmId = null;
    actionStatus = { ...actionStatus, [entry.id]: "loading" };
    try {
      const result = await bridge.callTool("distillery_resolve_review", {
        entry_id: entry.id,
        action: "archive",
        reviewer,
      });
      if (result.isError) {
        actionStatus = { ...actionStatus, [entry.id]: "error" };
        toastMsg = { ...toastMsg, [entry.id]: result.text || "Archive failed" };
      } else {
        actionStatus = { ...actionStatus, [entry.id]: "success" };
        toastMsg = { ...toastMsg, [entry.id]: "Archived" };
        removeEntry(entry.id);
      }
    } catch (err) {
      actionStatus = { ...actionStatus, [entry.id]: "error" };
      toastMsg = {
        ...toastMsg,
        [entry.id]: err instanceof Error ? err.message : "Archive failed",
      };
    }
  }

  function toggleRowExpand(id: string) {
    if (reclassifyId === id) {
      // Don't toggle expand when reclassify form is open
      return;
    }
    expandedId = expandedId === id ? null : id;
  }

  function toggleSelectAll() {
    if (selectedIds.size === entries.length && entries.length > 0) {
      selectedIds = new Set();
    } else {
      selectedIds = new Set(entries.map((e) => e.id));
    }
  }

  function toggleSelect(id: string) {
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    selectedIds = next;
  }

  async function handleBatchApprove() {
    if (!bridge?.isConnected || selectedIds.size === 0) return;
    const ids = [...selectedIds];
    const entriesToApprove = entries.filter((e) => ids.includes(e.id));
    batchProcessing = true;
    batchProgress = { current: 0, total: entriesToApprove.length };
    batchErrors = [];
    selectedIds = new Set();

    for (let i = 0; i < entriesToApprove.length; i++) {
      const entry = entriesToApprove[i]!;
      batchProgress = { current: i + 1, total: entriesToApprove.length };
      try {
        const result = await bridge.callTool("distillery_resolve_review", {
          entry_id: entry.id,
          action: "approve",
          reviewer,
        });
        if (result.isError) {
          batchErrors = [...batchErrors, `${entry.id}: ${result.text || "failed"}`];
        } else {
          removeEntry(entry.id);
        }
      } catch (err) {
        batchErrors = [
          ...batchErrors,
          `${entry.id}: ${err instanceof Error ? err.message : "failed"}`,
        ];
      }
    }

    batchProcessing = false;
    batchProgress = null;
  }
</script>

<section class="review-queue" aria-labelledby="review-queue-heading">
  <div class="section-header">
    <h2 id="review-queue-heading" class="section-title">Review Queue</h2>
  </div>

  {#if loading}
    <LoadingSkeleton rows={5} label="Loading review queue..." />
  {:else if loadError}
    <div class="error-banner" role="alert">
      <strong>Error:</strong> {loadError}
    </div>
  {:else if entries.length === 0}
    <p class="empty-state" data-testid="empty-state">No entries pending review.</p>
  {:else}
    <!-- Batch controls -->
    <div class="batch-controls">
      <label class="select-all-label">
        <input
          type="checkbox"
          aria-label="Select all entries"
          checked={selectedIds.size === entries.length && entries.length > 0}
          indeterminate={selectedIds.size > 0 && selectedIds.size < entries.length}
          onchange={toggleSelectAll}
        />
        Select all
      </label>

      {#if selectedIds.size > 0}
        <button
          class="action-btn action-btn--primary"
          onclick={handleBatchApprove}
          disabled={batchProcessing}
          aria-label="Approve all selected entries"
        >
          Approve all selected ({selectedIds.size})
        </button>
      {/if}
    </div>

    {#if batchProcessing && batchProgress}
      <div class="batch-progress" role="status" aria-live="polite">
        Approving {batchProgress.current} of {batchProgress.total}\u2026
        <div class="progress-bar">
          <div
            class="progress-bar__fill"
            style="width: {(batchProgress.current / batchProgress.total) * 100}%"
          ></div>
        </div>
      </div>
    {/if}

    {#if batchErrors.length > 0}
      <div class="error-banner" role="alert">
        <strong>Batch approve: {batchErrors.length} failed.</strong>
        <ul class="batch-error-list">
          {#each batchErrors as err (err)}
            <li>{err}</li>
          {/each}
        </ul>
      </div>
    {/if}

    <!-- DataTable -->
    <div class="datatable-wrapper">
      <div class="datatable-scroll">
        <table class="datatable" aria-label="Review queue entries">
          <thead>
            <tr>
              <th class="datatable-th datatable-th--check"></th>
              <th class="datatable-th">Preview</th>
              <th class="datatable-th">Type</th>
              <th class="datatable-th">Confidence</th>
              <th class="datatable-th">Classified At</th>
              <th class="datatable-th">Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each entries as entry (entry.id)}
              {@const isExpanded = expandedId === entry.id}
              {@const isReclassify = reclassifyId === entry.id}
              {@const isArchiveConfirm = archiveConfirmId === entry.id}
              {@const status = actionStatus[entry.id] ?? "idle"}
              {@const tier = confidenceTier(entry.confidence)}

              <!-- Main row -->
              <tr
                class="datatable-row"
                class:expanded={isExpanded}
                aria-expanded={isExpanded}
              >
                <td class="datatable-td datatable-td--check">
                  <input
                    type="checkbox"
                    aria-label="Select entry {entry.id}"
                    checked={selectedIds.has(entry.id)}
                    onchange={() => toggleSelect(entry.id)}
                  />
                </td>
                <td class="datatable-td datatable-td--preview">
                  <button
                    class="expand-btn"
                    onclick={() => toggleRowExpand(entry.id)}
                    aria-label="Toggle detail for entry {entry.id}"
                  >
                    {contentPreview(entry.content)}
                  </button>
                </td>
                <td class="datatable-td">
                  <span class="type-badge">{entry.entry_type || "\u2014"}</span>
                </td>
                <td class="datatable-td">
                  <span
                    class="confidence-badge confidence-badge--{tier}"
                    aria-label="Confidence {entry.confidence.toFixed(2)}"
                    data-tier={tier}
                  >
                    {entry.confidence.toFixed(2)}
                  </span>
                </td>
                <td class="datatable-td">
                  {formatDate(entry.classified_at)}
                </td>
                <td class="datatable-td datatable-td--actions">
                  {#if toastMsg[entry.id] && status === "success"}
                    <span class="toast-success" role="status">{toastMsg[entry.id]}</span>
                  {:else if toastMsg[entry.id] && status === "error"}
                    <span class="toast-error" role="alert">{toastMsg[entry.id]}</span>
                  {/if}
                  <button
                    class="action-btn action-btn--approve"
                    onclick={() => handleApprove(entry)}
                    disabled={status === "loading" || batchProcessing}
                    aria-label="Approve entry {entry.id}"
                  >
                    Approve
                  </button>
                  <button
                    class="action-btn action-btn--reclassify"
                    onclick={() => isReclassify ? handleReclassifyCancel() : handleReclassifyOpen(entry)}
                    disabled={status === "loading" || batchProcessing}
                    aria-label="Reclassify entry {entry.id}"
                  >
                    Reclassify
                  </button>
                  <button
                    class="action-btn action-btn--archive"
                    onclick={() => handleArchiveConfirm(entry)}
                    disabled={status === "loading" || batchProcessing}
                    aria-label="Archive entry {entry.id}"
                  >
                    Archive
                  </button>
                </td>
              </tr>

              <!-- Expanded metadata row -->
              {#if isExpanded}
                <tr class="expanded-row" aria-label="Metadata for entry {entry.id}">
                  <td colspan="6" class="expanded-td">
                    <div class="metadata-panel" data-testid="metadata-panel-{entry.id}">
                      <dl class="metadata-list">
                        <dt>Confidence</dt>
                        <dd>
                          <span
                            class="confidence-badge confidence-badge--{tier}"
                            data-tier={tier}
                          >
                            {entry.confidence.toFixed(2)}
                          </span>
                        </dd>
                        <dt>Reasoning</dt>
                        <dd class="metadata-reasoning">{entry.reasoning || "\u2014"}</dd>
                        <dt>Classified At</dt>
                        <dd>{entry.classified_at || "\u2014"}</dd>
                        <dt>Suggested Project</dt>
                        <dd>{entry.suggested_project ?? "\u2014"}</dd>
                      </dl>
                    </div>
                  </td>
                </tr>
              {/if}

              <!-- Reclassify inline form row -->
              {#if isReclassify}
                <tr class="reclassify-row">
                  <td colspan="6" class="reclassify-td">
                    <form
                      class="reclassify-form"
                      aria-label="Reclassify entry {entry.id}"
                      onsubmit={(e) => { e.preventDefault(); void handleReclassifySubmit(entry); }}
                    >
                      <label for="reclassify-type-{entry.id}" class="form-label">
                        New type:
                      </label>
                      <select
                        id="reclassify-type-{entry.id}"
                        class="type-selector"
                        bind:value={reclassifyType}
                        aria-label="Select new type for entry {entry.id}"
                      >
                        {#each ENTRY_TYPES as type (type)}
                          <option value={type}>{type}</option>
                        {/each}
                      </select>
                      <button
                        type="submit"
                        class="action-btn action-btn--primary"
                        disabled={status === "loading" || !reclassifyType}
                        aria-label="Submit reclassify for entry {entry.id}"
                      >
                        {status === "loading" ? "Saving\u2026" : "Apply"}
                      </button>
                      <button
                        type="button"
                        class="action-btn"
                        onclick={handleReclassifyCancel}
                        aria-label="Cancel reclassify for entry {entry.id}"
                      >
                        Cancel
                      </button>
                    </form>
                  </td>
                </tr>
              {/if}

              <!-- Archive confirmation row -->
              {#if isArchiveConfirm}
                <tr class="archive-confirm-row">
                  <td colspan="6" class="archive-confirm-td">
                    <div class="archive-confirm" role="alertdialog" aria-label="Archive confirmation for entry {entry.id}">
                      <span class="confirm-text">Archive this entry? This cannot be undone.</span>
                      <button
                        class="action-btn action-btn--archive"
                        onclick={() => void handleArchive(entry)}
                        aria-label="Confirm archive entry {entry.id}"
                      >
                        Confirm Archive
                      </button>
                      <button
                        class="action-btn"
                        onclick={handleArchiveCancel}
                        aria-label="Cancel archive entry {entry.id}"
                      >
                        Cancel
                      </button>
                    </div>
                  </td>
                </tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</section>

<style>
  .review-queue {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .section-header {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .section-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .empty-state {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
    font-style: italic;
    text-align: center;
    padding: 1.5rem 0;
  }

  .error-banner {
    padding: 0.75rem 1rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    border: 1px solid var(--error, #f38ba8);
    border-radius: 6px;
    color: var(--error, #f38ba8);
    font-size: 0.875rem;
  }

  .batch-error-list {
    margin: 0.5rem 0 0;
    padding-left: 1.25rem;
    font-size: 0.8rem;
  }

  /* Batch controls */
  .batch-controls {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .select-all-label {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.85rem;
    color: var(--fg-muted, #a6adc8);
    cursor: pointer;
  }

  /* Batch progress */
  .batch-progress {
    font-size: 0.85rem;
    color: var(--fg-muted, #a6adc8);
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .progress-bar {
    height: 4px;
    background: var(--border, #313244);
    border-radius: 2px;
    overflow: hidden;
    width: 200px;
  }

  .progress-bar__fill {
    height: 100%;
    background: var(--accent, #cba6f7);
    border-radius: 2px;
    transition: width 0.2s;
  }

  /* DataTable */
  .datatable-wrapper {
    overflow-x: auto;
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

  .datatable-th--check {
    width: 2.5rem;
    padding: 0.6rem 0.5rem;
  }

  .datatable-row {
    border-bottom: 1px solid var(--border, #313244);
  }

  .datatable-row.expanded {
    background: color-mix(in srgb, var(--accent, #89b4fa) 8%, transparent);
  }

  .datatable-td {
    padding: 0.55rem 0.75rem;
    vertical-align: middle;
    color: var(--fg, #cdd6f4);
  }

  .datatable-td--check {
    width: 2.5rem;
    padding: 0.55rem 0.5rem;
  }

  .datatable-td--preview {
    max-width: 280px;
  }

  .datatable-td--actions {
    white-space: nowrap;
    display: flex;
    align-items: center;
    gap: 0.35rem;
    flex-wrap: wrap;
  }

  /* Expand button (preview text acts as clickable) */
  .expand-btn {
    background: none;
    border: none;
    padding: 0;
    color: var(--fg, #cdd6f4);
    font-size: 0.875rem;
    cursor: pointer;
    text-align: left;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 260px;
    display: block;
  }

  .expand-btn:hover {
    color: var(--accent, #89b4fa);
    text-decoration: underline;
  }

  /* Type badge */
  .type-badge {
    display: inline-block;
    padding: 0.15rem 0.45rem;
    background: color-mix(in srgb, var(--fg-muted, #a6adc8) 15%, transparent);
    color: var(--fg-muted, #a6adc8);
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 500;
  }

  /* Confidence badge */
  .confidence-badge {
    display: inline-block;
    padding: 0.2rem 0.5rem;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .confidence-badge--green {
    background: color-mix(in srgb, #a6e3a1 20%, transparent);
    color: #a6e3a1;
    border: 1px solid color-mix(in srgb, #a6e3a1 40%, transparent);
  }

  .confidence-badge--yellow {
    background: color-mix(in srgb, #f9e2af 20%, transparent);
    color: #f9e2af;
    border: 1px solid color-mix(in srgb, #f9e2af 40%, transparent);
  }

  .confidence-badge--red {
    background: color-mix(in srgb, #f38ba8 20%, transparent);
    color: #f38ba8;
    border: 1px solid color-mix(in srgb, #f38ba8 40%, transparent);
  }

  /* Expanded metadata */
  .expanded-row {
    background: var(--detail-bg, #181825);
  }

  .expanded-td {
    padding: 0;
  }

  .metadata-panel {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border, #313244);
  }

  .metadata-list {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.35rem 1rem;
    margin: 0;
    font-size: 0.85rem;
  }

  .metadata-list dt {
    color: var(--fg-muted, #a6adc8);
    font-weight: 600;
  }

  .metadata-list dd {
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .metadata-reasoning {
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* Reclassify inline form */
  .reclassify-row {
    background: var(--detail-bg, #181825);
  }

  .reclassify-td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border, #313244);
  }

  .reclassify-form {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .form-label {
    font-size: 0.85rem;
    color: var(--fg-muted, #a6adc8);
  }

  .type-selector {
    padding: 0.3rem 0.5rem;
    font-size: 0.85rem;
    background: var(--input-bg, #313244);
    color: var(--fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    cursor: pointer;
  }

  /* Archive confirm */
  .archive-confirm-row {
    background: var(--detail-bg, #181825);
  }

  .archive-confirm-td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border, #313244);
  }

  .archive-confirm {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .confirm-text {
    font-size: 0.875rem;
    color: var(--fg, #cdd6f4);
  }

  /* Action buttons */
  .action-btn {
    padding: 0.3rem 0.7rem;
    font-size: 0.8rem;
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

  .action-btn--approve {
    background: color-mix(in srgb, #a6e3a1 15%, transparent);
    border-color: color-mix(in srgb, #a6e3a1 40%, transparent);
    color: #a6e3a1;
  }

  .action-btn--approve:hover:not(:disabled) {
    background: color-mix(in srgb, #a6e3a1 25%, transparent);
  }

  .action-btn--reclassify {
    background: color-mix(in srgb, #f9e2af 15%, transparent);
    border-color: color-mix(in srgb, #f9e2af 40%, transparent);
    color: #f9e2af;
  }

  .action-btn--reclassify:hover:not(:disabled) {
    background: color-mix(in srgb, #f9e2af 25%, transparent);
  }

  .action-btn--archive {
    background: color-mix(in srgb, #f38ba8 15%, transparent);
    border-color: color-mix(in srgb, #f38ba8 40%, transparent);
    color: #f38ba8;
  }

  .action-btn--archive:hover:not(:disabled) {
    background: color-mix(in srgb, #f38ba8 25%, transparent);
  }

  /* Toasts */
  .toast-success {
    font-size: 0.8rem;
    color: var(--success, #a6e3a1);
    font-weight: 500;
  }

  .toast-error {
    font-size: 0.8rem;
    color: var(--error, #f38ba8);
  }
</style>
