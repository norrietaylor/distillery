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
    from_id: string;
    to_id: string;
    relation_type: string;
    [key: string]: unknown;
  }

  /** A single breadcrumb entry in the navigation trail. */
  interface BreadcrumbItem {
    id: string;
    title: string;
  }

  /** A relation with computed direction relative to the current entry. */
  interface GroupedRelation {
    id: string;
    related_id: string;
    relation_type: string;
    direction: "OUTGOING" | "INCOMING";
  }

  /** Relations grouped by direction, then by type. */
  interface RelationGroup {
    direction: "OUTGOING" | "INCOMING";
    /** Map from relation_type to list of related entry IDs */
    byType: Map<string, GroupedRelation[]>;
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

  // Action UI state
  let editMode = $state(false);
  let editContent = $state("");
  let editSubmitting = $state(false);
  let editError = $state<string | null>(null);

  let correctMode = $state(false);
  let correctionText = $state("");
  let correctSubmitting = $state(false);
  let correctError = $state<string | null>(null);

  let archiveConfirm = $state(false);
  let archiveSubmitting = $state(false);
  let archiveError = $state<string | null>(null);

  /**
   * Breadcrumb trail for navigating between related entries.
   * Each item holds the id and a display title of a visited entry.
   * The current entry is NOT included — only ancestors.
   */
  let breadcrumbs = $state<BreadcrumbItem[]>([]);

  /**
   * Flag set to the id we are internally navigating to, so the $effect
   * that watches entryId can distinguish our own navigations from external
   * changes driven by the parent.  External changes reset the breadcrumb.
   * This is a plain variable (not $state) to avoid re-triggering the effect.
   */
  let internalNavTarget: string | null = null;

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

  /** Parse relations from JSON text.
   *
   * The MCP response wraps relations inside a top-level object:
   *   { entry_id, direction, relations: [...], count }
   * We accept either that wrapper or a bare array (test helpers use the bare form).
   */
  function parseRelations(text: string): Relation[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        // Unwrap { relations: [...] } wrapper from MCP response.
        const wrapped = parsed as Record<string, unknown>;
        if (Array.isArray(wrapped.relations)) {
          return wrapped.relations.map((r) => normalizeRelation(r as Record<string, unknown>));
        }
      }
      if (Array.isArray(parsed)) {
        return parsed.map((r) => normalizeRelation(r as Record<string, unknown>));
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
          list.push(normalizeRelation(obj as Record<string, unknown>));
        }
      } catch {
        // skip
      }
    }
    return list;
  }

  function normalizeRelation(obj: Record<string, unknown>): Relation {
    const raw = obj as Partial<Relation> & { related_id?: string };
    // Support both legacy { related_id } shape (tests) and canonical { from_id, to_id }.
    const from_id = String(raw.from_id ?? raw.related_id ?? "");
    const to_id = String(raw.to_id ?? raw.related_id ?? "");
    return {
      ...obj,
      id: String(raw.id ?? ""),
      from_id,
      to_id,
      relation_type: String(raw.relation_type ?? ""),
    };
  }

  /**
   * Compute direction-grouped relations for the current entry.
   * Returns at most two groups: OUTGOING then INCOMING.
   * Within each group, relations are further sub-grouped by relation_type.
   */
  function groupRelations(rels: Relation[], currentId: string): RelationGroup[] {
    const outgoing: RelationGroup = { direction: "OUTGOING", byType: new Map() };
    const incoming: RelationGroup = { direction: "INCOMING", byType: new Map() };

    for (const rel of rels) {
      const isOutgoing = rel.from_id === currentId || (rel.from_id === "" && rel.to_id !== currentId);
      const direction: "OUTGOING" | "INCOMING" = isOutgoing ? "OUTGOING" : "INCOMING";
      const related_id = isOutgoing ? rel.to_id : rel.from_id;
      const group = direction === "OUTGOING" ? outgoing : incoming;
      const typed = group.byType.get(rel.relation_type) ?? [];
      typed.push({ id: rel.id, related_id, relation_type: rel.relation_type, direction });
      group.byType.set(rel.relation_type, typed);
    }

    const result: RelationGroup[] = [];
    if (outgoing.byType.size > 0) result.push(outgoing);
    if (incoming.byType.size > 0) result.push(incoming);
    return result;
  }

  /** Derive a short human-readable title from an entry (first 60 chars of content). */
  function entryTitle(e: EntryData | null): string {
    if (!e) return "Entry";
    const raw = e.content.trim().replace(/\n.*/s, ""); // first line only
    return raw.length > 60 ? raw.slice(0, 57) + "…" : raw || e.id;
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
      // If this id change wasn't triggered by our own navigation, it's an
      // external update (e.g. parent selecting a search result) — reset the
      // breadcrumb trail so we start fresh.
      if (internalNavTarget !== id) {
        breadcrumbs = [];
      }
      internalNavTarget = null;
      void fetchEntry(id);
    } else {
      entry = null;
      relations = [];
      loadError = null;
      loading = false;
      breadcrumbs = [];
      internalNavTarget = null;
    }
  });

  /** Grouped relations derived from current entry and relations list. */
  const relationGroups = $derived(
    entry ? groupRelations(relations, entry.id) : []
  );

  // ---------------------------------------------------------------------------
  // Navigation helpers
  // ---------------------------------------------------------------------------

  /** Navigate to a related entry, pushing the current entry onto the breadcrumb. */
  function navigateToRelated(relatedId: string): void {
    if (!onNavigate || !entry) return;
    // Push current entry to breadcrumb trail before navigating away.
    breadcrumbs = [...breadcrumbs, { id: entry.id, title: entryTitle(entry) }];
    internalNavTarget = relatedId;
    onNavigate(relatedId);
  }

  /** Navigate back to a breadcrumb entry, truncating the trail at that point. */
  function navigateToBreadcrumb(crumb: BreadcrumbItem, index: number): void {
    if (!onNavigate) return;
    // Keep only the crumbs that came before this one.
    breadcrumbs = breadcrumbs.slice(0, index);
    internalNavTarget = crumb.id;
    onNavigate(crumb.id);
  }

  // ---------------------------------------------------------------------------
  // Action handlers
  // ---------------------------------------------------------------------------

  function startEdit(): void {
    if (!entry) return;
    editContent = entry.content;
    editError = null;
    editMode = true;
    correctMode = false;
    archiveConfirm = false;
  }

  function cancelEdit(): void {
    editMode = false;
    editError = null;
  }

  async function submitEdit(): Promise<void> {
    if (!bridge || !entry) return;
    editSubmitting = true;
    editError = null;
    try {
      const result = await bridge.callTool("distillery_update", {
        entry_id: entry.id,
        content: editContent,
      });
      if (result.isError) {
        editError = result.text || "Failed to save changes";
        return;
      }
      // Update local state optimistically.
      entry = { ...entry, content: editContent };
      editMode = false;
    } catch (err) {
      editError = err instanceof Error ? err.message : "Failed to save changes";
    } finally {
      editSubmitting = false;
    }
  }

  function startCorrect(): void {
    correctionText = "";
    correctError = null;
    correctMode = true;
    editMode = false;
    archiveConfirm = false;
  }

  function cancelCorrect(): void {
    correctMode = false;
    correctError = null;
  }

  async function submitCorrect(): Promise<void> {
    if (!bridge || !entry) return;
    correctSubmitting = true;
    correctError = null;
    try {
      const result = await bridge.callTool("distillery_correct", {
        entry_id: entry.id,
        correction: correctionText,
      });
      if (result.isError) {
        correctError = result.text || "Failed to submit correction";
        return;
      }
      correctMode = false;
      correctionText = "";
    } catch (err) {
      correctError = err instanceof Error ? err.message : "Failed to submit correction";
    } finally {
      correctSubmitting = false;
    }
  }

  function startArchive(): void {
    archiveError = null;
    archiveConfirm = true;
    editMode = false;
    correctMode = false;
  }

  function cancelArchive(): void {
    archiveConfirm = false;
    archiveError = null;
  }

  async function confirmArchive(): Promise<void> {
    if (!bridge || !entry) return;
    archiveSubmitting = true;
    archiveError = null;
    try {
      const result = await bridge.callTool("distillery_update", {
        entry_id: entry.id,
        status: "archived",
      });
      if (result.isError) {
        archiveError = result.text || "Failed to archive entry";
        return;
      }
      // Update local state so status badge reflects archive.
      entry = { ...entry, status: "archived" };
      archiveConfirm = false;
    } catch (err) {
      archiveError = err instanceof Error ? err.message : "Failed to archive entry";
    } finally {
      archiveSubmitting = false;
    }
  }
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
      <!-- Breadcrumb navigation trail -->
      {#if breadcrumbs.length > 0}
        <nav class="breadcrumb-nav" aria-label="Entry navigation breadcrumbs">
          {#each breadcrumbs as crumb, index (crumb.id)}
            <button
              class="breadcrumb-item"
              onclick={() => navigateToBreadcrumb(crumb, index)}
              aria-label="Navigate back to {crumb.title}"
            >
              {crumb.title}
            </button>
            <span class="breadcrumb-sep" aria-hidden="true">/</span>
          {/each}
          <span class="breadcrumb-current" aria-current="page">
            {entryTitle(entry)}
          </span>
        </nav>
      {/if}

      <!-- Header row: type badge + verification badge + actions -->
      <div class="entry-header">
        <span class="type-badge">{entry.entry_type || "entry"}</span>
        <span class={badgeClass(entry.status)} aria-label="Verification status">
          {badgeLabel(entry.status)}
        </span>

        <div class="action-group" aria-label="Entry actions">
          {#if onInvestigate}
            <button
              class="action-btn"
              onclick={() => onInvestigate?.(entry!.id)}
              aria-label="Investigate entry"
            >
              Investigate
            </button>
          {/if}
          <button
            class="action-btn"
            onclick={startEdit}
            aria-label="Edit entry"
            disabled={editMode}
          >
            Edit
          </button>
          <button
            class="action-btn"
            onclick={startCorrect}
            aria-label="Correct entry"
            disabled={correctMode}
          >
            Correct
          </button>
          <button
            class="action-btn action-btn--danger"
            onclick={startArchive}
            aria-label="Archive entry"
            disabled={archiveConfirm}
          >
            Archive
          </button>
        </div>
      </div>

      <!-- Edit form -->
      {#if editMode}
        <div class="action-form" aria-label="Edit entry form">
          <textarea
            class="action-textarea"
            bind:value={editContent}
            aria-label="Edit content"
            rows={6}
          ></textarea>
          {#if editError}
            <p class="action-error" role="alert">{editError}</p>
          {/if}
          <div class="action-form-btns">
            <button
              class="action-btn action-btn--primary"
              onclick={submitEdit}
              disabled={editSubmitting}
              aria-label="Save edit"
            >
              {editSubmitting ? "Saving…" : "Save"}
            </button>
            <button
              class="action-btn"
              onclick={cancelEdit}
              disabled={editSubmitting}
              aria-label="Cancel edit"
            >
              Cancel
            </button>
          </div>
        </div>
      {/if}

      <!-- Correction form -->
      {#if correctMode}
        <div class="action-form" aria-label="Correct entry form">
          <textarea
            class="action-textarea"
            bind:value={correctionText}
            placeholder="Describe the correction…"
            aria-label="Correction text"
            rows={4}
          ></textarea>
          {#if correctError}
            <p class="action-error" role="alert">{correctError}</p>
          {/if}
          <div class="action-form-btns">
            <button
              class="action-btn action-btn--primary"
              onclick={submitCorrect}
              disabled={correctSubmitting || !correctionText.trim()}
              aria-label="Submit correction"
            >
              {correctSubmitting ? "Submitting…" : "Submit"}
            </button>
            <button
              class="action-btn"
              onclick={cancelCorrect}
              disabled={correctSubmitting}
              aria-label="Cancel correction"
            >
              Cancel
            </button>
          </div>
        </div>
      {/if}

      <!-- Archive confirmation dialog -->
      {#if archiveConfirm}
        <div class="action-form action-form--warning" aria-label="Archive confirmation">
          <p class="action-confirm-msg">Archive this entry? This marks it as archived.</p>
          {#if archiveError}
            <p class="action-error" role="alert">{archiveError}</p>
          {/if}
          <div class="action-form-btns">
            <button
              class="action-btn action-btn--danger"
              onclick={confirmArchive}
              disabled={archiveSubmitting}
              aria-label="Confirm archive"
            >
              {archiveSubmitting ? "Archiving…" : "Confirm"}
            </button>
            <button
              class="action-btn"
              onclick={cancelArchive}
              disabled={archiveSubmitting}
              aria-label="Cancel archive"
            >
              Cancel
            </button>
          </div>
        </div>
      {/if}

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

      <!-- Relations: grouped by direction then by type -->
      {#if relationGroups.length > 0}
        <div class="relations-section">
          <h3 class="relations-title">Relations</h3>
          {#each relationGroups as group (group.direction)}
            <div class="relations-direction-group" aria-label="{group.direction === 'OUTGOING' ? 'Outgoing' : 'Incoming'} relations">
              <span class="direction-label">{group.direction === "OUTGOING" ? "Outgoing" : "Incoming"}</span>
              {#each [...group.byType.entries()] as [relType, rels] (relType)}
                <div class="relation-type-group">
                  <span class="relation-type-label">{relType}</span>
                  <ul class="relations-list">
                    {#each rels as rel (rel.id || rel.related_id)}
                      <li class="relation-item">
                        {#if rel.related_id}
                          <button
                            class="relation-link"
                            onclick={() => navigateToRelated(rel.related_id)}
                            aria-label="View related entry {rel.related_id}"
                          >
                            {rel.related_id}
                          </button>
                        {:else}
                          <span class="relation-id">—</span>
                        {/if}
                      </li>
                    {/each}
                  </ul>
                </div>
              {/each}
            </div>
          {/each}
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

  /* Action button group */
  .action-group {
    display: flex;
    gap: 0.35rem;
    margin-left: auto;
    flex-wrap: wrap;
  }

  /* Action buttons */
  .action-btn {
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

  .action-btn:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent, #89b4fa) 30%, transparent);
  }

  .action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .action-btn--primary {
    background: color-mix(in srgb, var(--accent, #89b4fa) 25%, transparent);
  }

  .action-btn--danger {
    color: var(--error, #f38ba8);
    border-color: color-mix(in srgb, var(--error, #f38ba8) 40%, transparent);
    background: color-mix(in srgb, var(--error, #f38ba8) 10%, transparent);
  }

  .action-btn--danger:hover:not(:disabled) {
    background: color-mix(in srgb, var(--error, #f38ba8) 20%, transparent);
  }

  /* Action forms (edit / correct / archive confirmation) */
  .action-form {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.75rem;
    background: color-mix(in srgb, var(--surface1, #313244) 40%, transparent);
    border: 1px solid var(--border, #45475a);
    border-radius: 6px;
  }

  .action-form--warning {
    border-color: color-mix(in srgb, var(--error, #f38ba8) 40%, transparent);
    background: color-mix(in srgb, var(--error, #f38ba8) 5%, transparent);
  }

  .action-textarea {
    width: 100%;
    box-sizing: border-box;
    padding: 0.5rem 0.65rem;
    font-family: ui-monospace, monospace;
    font-size: 0.8rem;
    line-height: 1.5;
    background: var(--input-bg, #1e1e2e);
    color: var(--fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    resize: vertical;
  }

  .action-textarea:focus {
    outline: 2px solid var(--accent, #89b4fa);
    outline-offset: 1px;
  }

  .action-form-btns {
    display: flex;
    gap: 0.35rem;
  }

  .action-error {
    font-size: 0.8rem;
    color: var(--error, #f38ba8);
    margin: 0;
  }

  .action-confirm-msg {
    font-size: 0.85rem;
    color: var(--fg, #cdd6f4);
    margin: 0;
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

  /* Breadcrumb navigation */
  .breadcrumb-nav {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.25rem;
    padding: 0.4rem 0.6rem;
    background: color-mix(in srgb, var(--surface1, #313244) 60%, transparent);
    border-radius: 4px;
    font-size: 0.75rem;
  }

  .breadcrumb-item {
    background: none;
    border: none;
    padding: 0;
    color: var(--accent, #89b4fa);
    font-size: 0.75rem;
    cursor: pointer;
    text-decoration: underline;
    text-underline-offset: 2px;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .breadcrumb-item:hover {
    color: var(--fg, #cdd6f4);
  }

  .breadcrumb-sep {
    color: var(--fg-muted, #a6adc8);
    user-select: none;
  }

  .breadcrumb-current {
    color: var(--fg, #cdd6f4);
    font-weight: 500;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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

  .relations-direction-group {
    margin-bottom: 0.75rem;
  }

  .direction-label {
    display: block;
    font-size: 0.7rem;
    font-weight: 600;
    color: var(--fg-muted, #a6adc8);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.35rem;
  }

  .relation-type-group {
    margin-left: 0.75rem;
    margin-bottom: 0.35rem;
  }

  .relation-type-label {
    display: inline-block;
    font-size: 0.7rem;
    font-weight: 500;
    color: var(--fg-muted, #a6adc8);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 0.2rem;
    padding: 0.05rem 0.3rem;
    background: color-mix(in srgb, var(--fg-muted, #a6adc8) 10%, transparent);
    border-radius: 3px;
  }

  .relations-list {
    list-style: none;
    margin: 0.2rem 0 0 0.5rem;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .relation-item {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    font-size: 0.8rem;
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
