<script lang="ts">
  /**
   * RelationGraph — Phase 2 of the InvestigateMode multi-phase investigation.
   *
   * Fetches and displays typed relations for the seed entry and each Phase 1
   * result. Entries are grouped as:
   *   SEED — the original entry
   *   RELATED — first-degree relations, grouped by relation_type
   *   2ND DEGREE — second-degree relations (lazy-loaded, collapsed by default)
   *
   * Each entry is clickable (onNavigate) and pin-able (onPin).
   * Second-degree expansion triggers a lazy distillery_relations call.
   * Traversal is capped at 2 degrees to prevent fan-out.
   */

  import type { McpBridge } from "$lib/mcp-bridge";
  import LoadingSkeleton from "./LoadingSkeleton.svelte";

  // ---------------------------------------------------------------------------
  // Types
  // ---------------------------------------------------------------------------

  /** A relation row returned by distillery_relations(action="get"). */
  interface RelationRow {
    id: string;
    from_id: string;
    to_id: string;
    relation_type: string;
    [key: string]: unknown;
  }

  /** A node in the relation graph with optional content for display. */
  interface GraphNode {
    id: string;
    /** Human-readable label: first 80 chars of content or the ID. */
    label: string;
    /** relation_type that connects it to a degree-1 entry (blank for seed). */
    relationType: string;
    /** The degree-1 entry this second-degree node is connected through. */
    viaId?: string;
  }

  /** State for a second-degree expansion of a degree-1 entry. */
  interface SecondDegreeState {
    loading: boolean;
    loaded: boolean;
    expanded: boolean;
    nodes: GraphNode[];
    error: string | null;
  }

  /** Entry data expected by onPin. */
  interface PinEntry {
    id: string;
    title: string;
    type: string;
    content: string;
  }

  // ---------------------------------------------------------------------------
  // Props
  // ---------------------------------------------------------------------------

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge?: McpBridge | null;
    /** ID of the seed entry that started the investigation. */
    seedEntryId: string;
    /** IDs from Phase 1 semantic search results to traverse relations for. */
    phase1ResultIds: string[];
    /** Callback when user clicks an entry to navigate/pivot to it. */
    onNavigate: (id: string) => void;
    /** Callback when user pins an entry to the working set. */
    onPin?: (entry: PinEntry) => void;
  }

  let {
    bridge = null,
    seedEntryId,
    phase1ResultIds,
    onNavigate,
    onPin,
  }: Props = $props();

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  /** Loading state for the initial batch of relation fetches. */
  let loading = $state(false);
  /** Error encountered during initial fetch. */
  let error = $state<string | null>(null);

  /**
   * First-degree related entries grouped by relation_type.
   * Map<relationType, GraphNode[]>
   */
  let relatedByType = $state(new Map<string, GraphNode[]>());

  /**
   * Second-degree expansion state keyed by the degree-1 entry ID.
   */
  let secondDegree = $state(new Map<string, SecondDegreeState>());

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /** Derive a display label for an entry given its id. Uses ID as fallback. */
  function labelFromId(id: string): string {
    return id.length > 24 ? id.slice(0, 20) + "…" : id;
  }

  /** Parse the MCP response text from distillery_relations(action="get"). */
  function parseRelations(text: string): RelationRow[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        const wrapped = parsed as Record<string, unknown>;
        if (Array.isArray(wrapped.relations)) {
          return wrapped.relations.map(normalizeRelation);
        }
      }
      if (Array.isArray(parsed)) {
        return parsed.map(normalizeRelation);
      }
    } catch {
      // fall through
    }
    const list: RelationRow[] = [];
    for (const line of text.split("\n")) {
      const t = line.trim();
      if (!t) continue;
      try {
        const obj: unknown = JSON.parse(t);
        if (obj && typeof obj === "object") {
          list.push(normalizeRelation(obj as Record<string, unknown>));
        }
      } catch {
        // skip
      }
    }
    return list;
  }

  function normalizeRelation(obj: unknown): RelationRow {
    const r = (obj ?? {}) as Partial<RelationRow>;
    return {
      ...(obj as Record<string, unknown>),
      id: String(r.id ?? ""),
      from_id: String(r.from_id ?? ""),
      to_id: String(r.to_id ?? ""),
      relation_type: String(r.relation_type ?? ""),
    };
  }

  /** Get the related entry ID from a relation row given the focal entry. */
  function relatedId(row: RelationRow, focalId: string): string {
    return row.from_id === focalId ? row.to_id : row.from_id;
  }

  // ---------------------------------------------------------------------------
  // Phase 2: fetch relations on mount
  // ---------------------------------------------------------------------------

  /**
   * Fetch relations for all degree-1 entry IDs (seed + phase1 results).
   * Groups into relatedByType, excluding the seed and already-seen phase1 IDs.
   */
  async function fetchAllRelations() {
    if (!bridge?.isConnected) {
      error = "Not connected to MCP server";
      return;
    }
    loading = true;
    error = null;

    const degree0Ids = new Set<string>([seedEntryId, ...phase1ResultIds]);
    const newRelatedByType = new Map<string, GraphNode[]>();

    try {
      // Fetch relations for seed + each phase1 result in parallel
      const idsToFetch = [seedEntryId, ...phase1ResultIds];
      const results = await Promise.allSettled(
        idsToFetch.map((id) =>
          bridge!.callTool("distillery_relations", { action: "get", entry_id: id }),
        ),
      );

      // Check if all fetches failed — surface a single error rather than silent empty
      const allFailed = results.every((r) => r.status === "rejected");
      if (allFailed && results.length > 0) {
        const firstRejection = results[0] as PromiseRejectedResult;
        error =
          firstRejection.reason instanceof Error
            ? firstRejection.reason.message
            : "Failed to load relations";
      }

      for (let i = 0; i < results.length; i++) {
        const result = results[i];
        const focalId = idsToFetch[i]!;
        if (result.status === "rejected" || result.value.isError) continue;

        const rows = parseRelations(result.value.text);
        for (const row of rows) {
          const relId = relatedId(row, focalId);
          // Skip entries already in degree-0 set
          if (degree0Ids.has(relId)) continue;
          const node: GraphNode = {
            id: relId,
            label: labelFromId(relId),
            relationType: row.relation_type,
          };
          const bucket = newRelatedByType.get(row.relation_type) ?? [];
          // Deduplicate within each type bucket
          if (!bucket.some((n) => n.id === relId)) {
            bucket.push(node);
            newRelatedByType.set(row.relation_type, bucket);
          }
        }
      }
    } catch (err) {
      error = err instanceof Error ? err.message : "Failed to load relations";
    } finally {
      loading = false;
      relatedByType = newRelatedByType;
    }
  }

  // Kick off on mount (reactively on seedEntryId change)
  let lastSeedId = "";
  $effect(() => {
    if (seedEntryId !== lastSeedId) {
      lastSeedId = seedEntryId;
      relatedByType = new Map();
      secondDegree = new Map();
      void fetchAllRelations();
    }
  });

  // ---------------------------------------------------------------------------
  // Second-degree expansion
  // ---------------------------------------------------------------------------

  /** Toggle expand/collapse for a degree-1 entry's second-degree relations. */
  async function toggleSecondDegree(nodeId: string) {
    const existing = secondDegree.get(nodeId);
    if (existing) {
      // Toggle expanded state
      secondDegree = new Map(secondDegree).set(nodeId, {
        ...existing,
        expanded: !existing.expanded,
      });
      // If already loaded, no further fetch needed
      if (existing.loaded) return;
    }

    // First expansion: lazy-load relations for this node
    const state: SecondDegreeState = {
      loading: true,
      loaded: false,
      expanded: true,
      nodes: [],
      error: null,
    };
    secondDegree = new Map(secondDegree).set(nodeId, state);

    if (!bridge?.isConnected) {
      secondDegree = new Map(secondDegree).set(nodeId, {
        ...state,
        loading: false,
        error: "Not connected to MCP server",
      });
      return;
    }

    try {
      const result = await bridge.callTool("distillery_relations", {
        action: "get",
        entry_id: nodeId,
      });

      if (result.isError) {
        secondDegree = new Map(secondDegree).set(nodeId, {
          ...state,
          loading: false,
          error: result.text || "Failed to load second-degree relations",
        });
        return;
      }

      const rows = parseRelations(result.text);
      // Exclude the node itself and entries already in degree-0 / degree-1 sets
      const degree0Ids = new Set([seedEntryId, ...phase1ResultIds]);
      const degree1Ids = new Set<string>();
      for (const nodes of relatedByType.values()) {
        for (const n of nodes) degree1Ids.add(n.id);
      }
      const seen = new Set([...degree0Ids, ...degree1Ids, nodeId]);

      const nodes: GraphNode[] = [];
      for (const row of rows) {
        const relId = relatedId(row, nodeId);
        if (seen.has(relId)) continue;
        if (!nodes.some((n) => n.id === relId)) {
          nodes.push({
            id: relId,
            label: labelFromId(relId),
            relationType: row.relation_type,
            viaId: nodeId,
          });
        }
      }

      secondDegree = new Map(secondDegree).set(nodeId, {
        loading: false,
        loaded: true,
        expanded: true,
        nodes,
        error: null,
      });
    } catch (err) {
      const currentState = secondDegree.get(nodeId) ?? state;
      secondDegree = new Map(secondDegree).set(nodeId, {
        ...currentState,
        loading: false,
        error: err instanceof Error ? err.message : "Failed to load",
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Pin helper
  // ---------------------------------------------------------------------------

  function handlePin(id: string, label: string) {
    onPin?.({ id, title: label, type: "entry", content: label });
  }
</script>

<section class="relation-graph" aria-label="Phase 2: Relation Graph">
  <h3 class="rg-title">Relation Graph</h3>

  {#if loading}
    <LoadingSkeleton rows={3} label="Loading relations..." />
  {:else if error}
    <div class="error-banner" role="alert">
      <strong>Error:</strong> {error}
    </div>
  {:else}
    <!-- SEED section -->
    <div class="rg-section" aria-label="Seed entry">
      <h4 class="rg-section-header">
        <span class="section-badge section-badge--seed">SEED</span>
      </h4>
      <ul class="rg-node-list" aria-label="Seed entry node">
        <li class="rg-node rg-node--seed">
          <button
            class="rg-node-btn"
            onclick={() => onNavigate(seedEntryId)}
            aria-label="Navigate to seed entry {seedEntryId}"
          >
            <span class="rg-node-label">{labelFromId(seedEntryId)}</span>
          </button>
          <button
            class="rg-pin-btn"
            onclick={() => handlePin(seedEntryId, labelFromId(seedEntryId))}
            aria-label="Pin seed entry"
            title="Pin to working set"
          >
            Pin
          </button>
        </li>
      </ul>
    </div>

    <!-- RELATED section: grouped by relation_type -->
    {#if relatedByType.size > 0}
      <div class="rg-section" aria-label="Related entries">
        <h4 class="rg-section-header">
          <span class="section-badge section-badge--related">RELATED</span>
        </h4>
        {#each [...relatedByType.entries()] as [relType, nodes] (relType)}
          <div class="rg-type-group" aria-label="Relation type: {relType}">
            <span class="rg-type-label">{relType || "related"}</span>
            <ul class="rg-node-list" aria-label="{relType} entries">
              {#each nodes as node (node.id)}
                <li class="rg-node">
                  <button
                    class="rg-node-btn"
                    onclick={() => onNavigate(node.id)}
                    aria-label="Navigate to {node.label}"
                  >
                    <span class="rg-node-label">{node.label}</span>
                  </button>
                  <button
                    class="rg-pin-btn"
                    onclick={() => handlePin(node.id, node.label)}
                    aria-label="Pin entry {node.label}"
                    title="Pin to working set"
                  >
                    Pin
                  </button>
                  <!-- 2ND DEGREE expansion toggle -->
                  <button
                    class="rg-expand-btn"
                    onclick={() => toggleSecondDegree(node.id)}
                    aria-expanded={secondDegree.get(node.id)?.expanded ?? false}
                    aria-label="Expand second-degree relations for {node.label}"
                  >
                    {secondDegree.get(node.id)?.expanded ? "▲" : "▼"}
                  </button>

                  <!-- Second-degree content -->
                  {#if secondDegree.get(node.id)?.expanded}
                    {@const sd = secondDegree.get(node.id)!}
                    <div class="rg-second-degree" aria-label="Second-degree relations of {node.label}">
                      {#if sd.loading}
                        <LoadingSkeleton rows={2} label="Loading second-degree relations..." />
                      {:else if sd.error}
                        <p class="rg-error-inline" role="alert">{sd.error}</p>
                      {:else if sd.nodes.length === 0}
                        <p class="rg-empty-inline">No further relations found.</p>
                      {:else}
                        <ul class="rg-node-list rg-node-list--second" aria-label="Second-degree entries">
                          {#each sd.nodes as sdNode (sdNode.id)}
                            <li class="rg-node rg-node--second">
                              <button
                                class="rg-node-btn"
                                onclick={() => onNavigate(sdNode.id)}
                                aria-label="Navigate to {sdNode.label}"
                              >
                                <span class="rg-type-chip">{sdNode.relationType || "related"}</span>
                                <span class="rg-node-label">{sdNode.label}</span>
                              </button>
                              <button
                                class="rg-pin-btn"
                                onclick={() => handlePin(sdNode.id, sdNode.label)}
                                aria-label="Pin entry {sdNode.label}"
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
          </div>
        {/each}
      </div>
    {:else}
      <p class="rg-empty-state">No relations found for the selected entries.</p>
    {/if}
  {/if}
</section>

<style>
  .relation-graph {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .rg-title {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0 0 0.25rem;
  }

  .rg-section {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .rg-section-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0;
    font-size: 0.8rem;
  }

  .section-badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.06em;
  }

  .section-badge--seed {
    background: color-mix(in srgb, var(--accent, #89b4fa) 20%, transparent);
    color: var(--accent, #89b4fa);
    border: 1px solid color-mix(in srgb, var(--accent, #89b4fa) 40%, transparent);
  }

  .section-badge--related {
    background: color-mix(in srgb, #a6e3a1 15%, transparent);
    color: #a6e3a1;
    border: 1px solid color-mix(in srgb, #a6e3a1 40%, transparent);
  }

  .rg-type-group {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .rg-type-label {
    font-size: 0.7rem;
    font-weight: 600;
    color: var(--fg-muted, #a6adc8);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding-left: 0.25rem;
  }

  .rg-node-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  .rg-node-list--second {
    padding-left: 1rem;
    border-left: 2px solid var(--border, #45475a);
    margin-left: 0.5rem;
  }

  .rg-node {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    background: color-mix(in srgb, var(--bg-highlight, #313244) 20%, transparent);
    border: 1px solid var(--border, #45475a);
    border-radius: 5px;
    overflow: hidden;
    flex-wrap: wrap;
  }

  .rg-node--seed {
    border-color: color-mix(in srgb, var(--accent, #89b4fa) 40%, transparent);
  }

  .rg-node--second {
    background: color-mix(in srgb, var(--bg-highlight, #313244) 10%, transparent);
    font-size: 0.82rem;
  }

  .rg-node-btn {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.5rem 0.75rem;
    background: none;
    border: none;
    color: var(--fg, #cdd6f4);
    text-align: left;
    cursor: pointer;
    font-size: 0.85rem;
    min-width: 0;
  }

  .rg-node-btn:hover {
    background: color-mix(in srgb, var(--accent, #89b4fa) 8%, transparent);
  }

  .rg-node-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .rg-type-chip {
    font-size: 0.65rem;
    font-weight: 600;
    padding: 0.1rem 0.3rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    color: var(--accent, #89b4fa);
    border-radius: 6px;
    flex-shrink: 0;
    white-space: nowrap;
  }

  .rg-pin-btn {
    padding: 0.25rem 0.5rem;
    font-size: 0.7rem;
    font-weight: 500;
    background: none;
    color: var(--fg-muted, #a6adc8);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    cursor: pointer;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .rg-pin-btn:hover {
    color: var(--accent, #89b4fa);
    border-color: var(--accent, #89b4fa);
  }

  .rg-expand-btn {
    padding: 0.25rem 0.4rem;
    font-size: 0.65rem;
    background: none;
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    color: var(--fg-muted, #a6adc8);
    cursor: pointer;
    flex-shrink: 0;
    margin-right: 0.25rem;
  }

  .rg-expand-btn:hover {
    background: color-mix(in srgb, var(--fg-muted, #a6adc8) 15%, transparent);
  }

  .rg-second-degree {
    width: 100%;
    padding: 0.5rem 0.75rem 0.5rem 1rem;
    border-top: 1px solid var(--border, #45475a);
    background: color-mix(in srgb, var(--bg-highlight, #313244) 10%, transparent);
  }

  .rg-empty-state {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
    font-style: italic;
    text-align: center;
    padding: 1rem 0;
  }

  .rg-empty-inline {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.8rem;
    font-style: italic;
    margin: 0.25rem 0;
  }

  .rg-error-inline {
    color: var(--error, #f38ba8);
    font-size: 0.8rem;
    margin: 0.25rem 0;
  }

  .error-banner {
    padding: 0.75rem 1rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    border: 1px solid var(--error, #f38ba8);
    border-radius: 6px;
    color: var(--error, #f38ba8);
    font-size: 0.875rem;
  }
</style>
