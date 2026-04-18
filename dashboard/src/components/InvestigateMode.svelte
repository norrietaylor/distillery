<script lang="ts">
  /**
   * InvestigateMode — container component for multi-phase investigation.
   *
   * Launched from EntryDetail "Investigate" button. Provides:
   *   1. "Back to results" button (calls onExit)
   *   2. Phase indicator: 4 numbered steps, current highlighted, completed clickable
   *   3. Breadcrumb trail: seed entry + pivots as clickable links
   *   4. Phase 1 — Semantic Search: runs search with seed content, displays ranked cards
   *   5. State: phaseData, currentPhase, investigationPath, seenEntryIds
   *   6. Each phase section loads independently with its own loading spinner
   *   7. Pin button on each card (calls onPin)
   */

  import type { McpBridge } from "$lib/mcp-bridge";
  import { selectedProject } from "$lib/stores";
  import LoadingSkeleton from "./LoadingSkeleton.svelte";
  import ScoreBadge from "./ScoreBadge.svelte";
  import TagNeighborhood from "./TagNeighborhood.svelte";
  import RelationGraph from "./RelationGraph.svelte";

  // ---------------------------------------------------------------------------
  // Types
  // ---------------------------------------------------------------------------

  /** A single search result card in the investigation. */
  interface InvestigateResult {
    id: string;
    content: string;
    entry_type: string;
    source: string;
    score: number;
    tags: string[];
    created_at: string;
    [key: string]: unknown;
  }

  /** A breadcrumb in the investigation path. */
  interface PathEntry {
    id: string;
    title: string;
    query: string;
  }

  /** Phase metadata for the indicator. */
  interface PhaseInfo {
    number: number;
    label: string;
  }

  // ---------------------------------------------------------------------------
  // Props
  // ---------------------------------------------------------------------------

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge?: McpBridge | null;
    /** ID of the seed entry that started the investigation. */
    seedEntryId: string;
    /** Title of the seed entry (first line of content). */
    seedTitle: string;
    /** Content snippet used as the initial search query. */
    seedContent: string;
    /** Callback to exit investigate mode and return to results. */
    onExit: () => void;
    /** Callback to pin an entry to the working set. */
    onPin?: (entry: { id: string; title: string; type: string; content: string }) => void;
  }

  let {
    bridge = null,
    seedEntryId,
    seedTitle,
    seedContent,
    onExit,
    onPin,
  }: Props = $props();

  // ---------------------------------------------------------------------------
  // Phase definitions
  // ---------------------------------------------------------------------------

  const PHASES: PhaseInfo[] = [
    { number: 1, label: "Semantic Search" },
    { number: 2, label: "Relation Graph" },
    { number: 3, label: "Tag Neighborhood" },
    { number: 4, label: "Gap Analysis" },
  ];

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  /** Current active phase (1-based). */
  let currentPhase = $state(1);

  /** Set of entry IDs already seen in this investigation. */
  let seenEntryIds = $state(new Set<string>());

  /** Breadcrumb trail: seed + each pivot. */
  let investigationPath = $state<PathEntry[]>([]);

  // Initialize state from seed props. This $effect reads the props reactively
  // and resets state if the seed changes (e.g., component remount with new seed).
  let lastSeedId = "";
  $effect(() => {
    if (seedEntryId !== lastSeedId) {
      lastSeedId = seedEntryId;
      seenEntryIds = new Set<string>([seedEntryId]);
      investigationPath = [
        {
          id: seedEntryId,
          title: seedTitle,
          query: buildQuery(seedContent),
        },
      ];
      currentPhase = 1;
      completedPhase = 0;
      phase1Results = [];
      phase1Error = null;
      phase4Results = [];
      phase4Error = null;
      phase3DiscoveredTags = [];
    }
  });

  /** Phase 1 search results. */
  let phase1Results = $state<InvestigateResult[]>([]);
  let phase1Loading = $state(false);
  let phase1Error = $state<string | null>(null);

  /** Request counters to detect stale in-flight phase searches. */
  let activePhase1Request = 0;
  let activePhase4Request = 0;
  let activePivotRequest = 0;

  /** Highest phase that has been completed (0 = none). */
  let completedPhase = $state(0);

  /** Phase 3: collect seed tags from Phase 1 results for TagNeighborhood. */
  let phase3SeedTags = $derived.by((): string[] => {
    const allTags = phase1Results.flatMap((r) => r.tags);
    return Array.from(new Set(allTags));
  });

  /** Phase 4 gap-fill results. */
  let phase4Results = $state<InvestigateResult[]>([]);
  let phase4Loading = $state(false);
  let phase4Error = $state<string | null>(null);

  /** Tags discovered in Phase 3 (set via callback from TagNeighborhood). */
  let phase3DiscoveredTags = $state<string[]>([]);

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /** Build a search query from content: first 200 chars, trimmed. */
  function buildQuery(content: string): string {
    const first = content.split("\n")[0] ?? content;
    return first.length > 200 ? first.slice(0, 200) : first;
  }

  /** Content preview: first line up to 100 chars. */
  function contentPreview(content: string): string {
    const first = content.split("\n")[0] ?? content;
    return first.length > 100 ? first.slice(0, 100) + "..." : first;
  }

  /** Parse tool response text into result objects. */
  function parseResults(text: string): InvestigateResult[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      // Handle distillery_search response: { results: [{ score, entry }], count }
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        const wrapped = parsed as Record<string, unknown>;
        if (Array.isArray(wrapped.results)) {
          return wrapped.results.map((r: unknown) => {
            const row = r as { score?: number; entry?: Record<string, unknown> };
            const entry = row.entry ?? (r as Record<string, unknown>);
            return normalizeResult({ ...entry, score: row.score ?? entry.score });
          });
        }
        return [normalizeResult(wrapped)];
      }
      if (Array.isArray(parsed)) return parsed.map(normalizeResult);
    } catch {
      // fall through to line-by-line
    }
    const list: InvestigateResult[] = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const obj: unknown = JSON.parse(trimmed);
        if (obj && typeof obj === "object") {
          list.push(normalizeResult(obj as Record<string, unknown>));
        }
      } catch {
        // skip
      }
    }
    return list;
  }

  function normalizeResult(obj: Record<string, unknown>): InvestigateResult {
    const raw = obj as Partial<InvestigateResult>;
    return {
      ...obj,
      id: String(raw.id ?? crypto.randomUUID()),
      content: String(raw.content ?? ""),
      entry_type: String(raw.entry_type ?? raw.type ?? ""),
      source: String(raw.source ?? ""),
      score: typeof raw.score === "number" ? raw.score : 0,
      tags: Array.isArray(raw.tags) ? (raw.tags as string[]) : [],
      created_at: String(raw.created_at ?? ""),
    };
  }

  // ---------------------------------------------------------------------------
  // Phase 1: Semantic Search
  // ---------------------------------------------------------------------------

  async function runPhase1Search(query: string) {
    if (!bridge?.isConnected) {
      phase1Error = "Not connected to MCP server";
      return;
    }
    const requestId = ++activePhase1Request;
    phase1Loading = true;
    phase1Error = null;
    try {
      const args: Record<string, unknown> = { query: query.trim(), limit: 10 };
      const project = $selectedProject;
      if (project) args["project"] = project;
      const result = await bridge.callTool("distillery_search", args);
      if (requestId !== activePhase1Request) return;
      if (result.isError) {
        phase1Error = result.text || "Search failed";
        phase1Results = [];
        return;
      }
      const all = parseResults(result.text);
      // Filter out entries already seen in this investigation
      phase1Results = all.filter((r) => !seenEntryIds.has(r.id));
      completedPhase = Math.max(completedPhase, 1);
    } catch (err) {
      if (requestId !== activePhase1Request) return;
      phase1Error = err instanceof Error ? err.message : "Search failed";
      phase1Results = [];
    } finally {
      if (requestId === activePhase1Request) {
        phase1Loading = false;
      }
    }
  }

  // Kick off Phase 1 on mount / on pivot.
  // NOTE: the `void $selectedProject;` read is load-bearing — it registers the
  // project store as a dependency of this effect. runPhase1Search() reads
  // $selectedProject via closure *before* the first await, which in theory
  // Svelte 5's reactivity tracker should follow through function calls, but
  // in practice is a brittle edge case. Without this explicit read, switching
  // the ProjectSelector (e.g. back to "All projects") would not retrigger the
  // Phase 1 search. Do not "clean up" this seemingly-unused read.
  $effect(() => {
    void $selectedProject;
    const path = investigationPath;
    if (path.length > 0 && currentPhase === 1) {
      const currentEntry = path[path.length - 1];
      void runPhase1Search(currentEntry.query);
    }
  });

  // ---------------------------------------------------------------------------
  // Phase 4: Gap Analysis
  // ---------------------------------------------------------------------------

  /** The current pivot query derived from the last breadcrumb entry. */
  const currentQuery = $derived(
    investigationPath.length > 0
      ? (investigationPath[investigationPath.length - 1]?.query ?? buildQuery(seedContent))
      : buildQuery(seedContent),
  );

  /** Synthesize a gap-fill query from current pivot + top tags from Phase 3. */
  function synthesizeGapQuery(): string {
    const pivotLine = currentQuery.split("\n")[0] ?? currentQuery;
    const topTags = (phase3DiscoveredTags.length > 0 ? phase3DiscoveredTags : phase3SeedTags)
      .slice(0, 3)
      .join(" ");
    return topTags ? `${pivotLine} ${topTags}` : pivotLine;
  }

  async function runPhase4GapFill() {
    if (!bridge?.isConnected) {
      phase4Error = "Not connected to MCP server";
      return;
    }
    const requestId = ++activePhase4Request;
    phase4Loading = true;
    phase4Error = null;
    try {
      const query = synthesizeGapQuery();
      const args: Record<string, unknown> = { query: query.trim(), limit: 5 };
      const project = $selectedProject;
      if (project) args["project"] = project;
      const result = await bridge.callTool("distillery_search", args);
      if (requestId !== activePhase4Request) return;
      if (result.isError) {
        phase4Error = result.text || "Gap analysis failed";
        phase4Results = [];
        return;
      }
      const all = parseResults(result.text);
      // Filter out entries already seen in this investigation
      phase4Results = all.filter((r) => !seenEntryIds.has(r.id));
      completedPhase = Math.max(completedPhase, 4);
    } catch (err) {
      if (requestId !== activePhase4Request) return;
      phase4Error = err instanceof Error ? err.message : "Gap analysis failed";
      phase4Results = [];
    } finally {
      if (requestId === activePhase4Request) {
        phase4Loading = false;
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Pivot: click a result card to use it as new seed
  // ---------------------------------------------------------------------------

  function handlePivot(result: InvestigateResult) {
    // Invalidate any in-flight async graph pivot hydration — a synchronous
    // pivot on a Phase 1 result takes precedence and must not be overwritten.
    activePivotRequest++;
    seenEntryIds = new Set([...seenEntryIds, result.id]);
    investigationPath = [
      ...investigationPath,
      {
        id: result.id,
        title: contentPreview(result.content),
        query: buildQuery(result.content),
      },
    ];
    currentPhase = 1;
    completedPhase = 0;
    phase1Results = [];
    phase4Results = [];
    phase4Error = null;
    phase3DiscoveredTags = [];
  }

  // ---------------------------------------------------------------------------
  // Breadcrumb navigation: jump back to a previous pivot
  // ---------------------------------------------------------------------------

  function handleBreadcrumbClick(index: number) {
    if (index >= investigationPath.length - 1) return; // already here
    // Invalidate any in-flight async pivot hydration — the breadcrumb jump
    // defines the new "current" state and must not be overwritten.
    activePivotRequest++;
    investigationPath = investigationPath.slice(0, index + 1);
    currentPhase = 1;
    completedPhase = 0;
    phase1Results = [];
    phase4Results = [];
    phase4Error = null;
    phase3DiscoveredTags = [];
  }

  // ---------------------------------------------------------------------------
  // Phase indicator click
  // ---------------------------------------------------------------------------

  function handlePhaseClick(phaseNumber: number) {
    const previousPhase = currentPhase;
    if (
      phaseNumber <= completedPhase ||
      phaseNumber === currentPhase ||
      phaseNumber === completedPhase + 1 ||
      phaseNumber === currentPhase + 1
    ) {
      currentPhase = phaseNumber;
      // If the user manually navigates to Phase 4, kick off the gap-fill
      // search (Phase 3's onResults handler normally does this, but a direct
      // click would otherwise land on an empty state).
      if (phaseNumber === 4 && previousPhase !== 4) {
        void runPhase4GapFill();
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Pin entry
  // ---------------------------------------------------------------------------

  function handlePin(result: InvestigateResult) {
    onPin?.({
      id: result.id,
      title: contentPreview(result.content),
      type: result.entry_type,
      content: result.content,
    });
  }
</script>

<section class="investigate-mode" aria-label="Investigation mode">
  <!-- Back button -->
  <div class="investigate-header">
    <button
      class="back-btn"
      onclick={onExit}
      aria-label="Back to results"
    >
      &larr; Back to results
    </button>
    <h2 class="investigate-title">Investigation</h2>
  </div>

  <!-- Phase indicator -->
  <nav class="phase-indicator" aria-label="Investigation phases">
    <ol class="phase-list">
      {#each PHASES as phase (phase.number)}
        {@const isActive = phase.number === currentPhase}
        {@const isCompleted = phase.number <= completedPhase}
        {@const isClickable = isCompleted || isActive || phase.number === completedPhase + 1 || phase.number === currentPhase + 1}
        <li class="phase-item" class:phase-item--active={isActive} class:phase-item--completed={isCompleted}>
          <button
            class="phase-btn"
            class:phase-btn--active={isActive}
            class:phase-btn--completed={isCompleted}
            disabled={!isClickable}
            onclick={() => handlePhaseClick(phase.number)}
            aria-current={isActive ? "step" : undefined}
            aria-label="Phase {phase.number}: {phase.label}"
          >
            <span class="phase-number">{phase.number}</span>
            <span class="phase-label">{phase.label}</span>
          </button>
        </li>
      {/each}
    </ol>
  </nav>

  <!-- Breadcrumb trail -->
  <nav class="breadcrumb-trail" aria-label="Investigation path">
    <ol class="breadcrumb-list">
      {#each investigationPath as crumb, i (crumb.id + "-" + i)}
        {@const isLast = i === investigationPath.length - 1}
        <li class="breadcrumb-item">
          {#if isLast}
            <span class="breadcrumb-current" aria-current="location">{crumb.title}</span>
          {:else}
            <button
              class="breadcrumb-link"
              onclick={() => handleBreadcrumbClick(i)}
              aria-label="Return to {crumb.title}"
            >
              {crumb.title}
            </button>
            <span class="breadcrumb-separator" aria-hidden="true">/</span>
          {/if}
        </li>
      {/each}
    </ol>
  </nav>

  <!-- Phase content -->
  <div class="phase-content">
    {#if currentPhase === 1}
      <section class="phase-section" aria-label="Phase 1: Semantic Search">
        <h3 class="phase-section-title">Semantic Search Results</h3>

        {#if phase1Loading}
          <LoadingSkeleton rows={4} label="Searching related entries..." />
        {:else if phase1Error}
          <div class="error-banner" role="alert">
            <strong>Error:</strong> {phase1Error}
          </div>
        {:else if phase1Results.length === 0}
          <p class="empty-state">No related entries found.</p>
        {:else}
          <ul class="result-cards" aria-label="Search results">
            {#each phase1Results as result (result.id)}
              <li class="result-card">
                <button
                  class="card-body"
                  onclick={() => handlePivot(result)}
                  aria-label="Pivot to: {contentPreview(result.content)}"
                >
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
                </button>
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
      </section>
    {:else if currentPhase === 2}
      <!-- Phase 2: Relation Graph -->
      <section class="phase-section" aria-label="Phase 2: Relation Graph">
        <RelationGraph
          {bridge}
          seedEntryId={investigationPath[investigationPath.length - 1]?.id ?? seedEntryId}
          phase1ResultIds={phase1Results.map((r) => r.id)}
          onNavigate={(id) => {
            const found = phase1Results.find((r) => r.id === id);
            if (found) {
              handlePivot(found);
            } else {
              // Navigate to an entry not in phase1 results: hydrate via distillery_get
              const pivotRequestId = ++activePivotRequest;
              void (async () => {
                if (!bridge?.isConnected) return;
                try {
                  const result = await bridge.callTool("distillery_get", { entry_id: id });
                  // Drop stale responses: if the user pivoted again or the
                  // breadcrumb changed, ignore this fetch.
                  if (pivotRequestId !== activePivotRequest) return;
                  if (result.isError) return;
                  const raw: unknown = JSON.parse(result.text);
                  const obj = (Array.isArray(raw) ? raw[0] : raw) as Record<string, unknown> | undefined;
                  if (!obj) return;
                  const content = String(obj["content"] ?? "");
                  const firstLine = content.split("\n")[0] ?? content;
                  const title = firstLine.length > 60 ? firstLine.slice(0, 57) + "…" : firstLine || id;
                  const query = buildQuery(content);
                  seenEntryIds = new Set([...seenEntryIds, id]);
                  investigationPath = [
                    ...investigationPath,
                    { id, title, query },
                  ];
                  currentPhase = 1;
                  completedPhase = 0;
                  phase1Results = [];
                  phase4Results = [];
                  phase4Error = null;
                  phase3DiscoveredTags = [];
                } catch {
                  // If fetch fails, skip pivoting rather than storing raw id as query
                }
              })();
            }
          }}
          onPin={(entry) => onPin?.(entry)}
        />
      </section>
    {:else if currentPhase === 3}
      <!-- Phase 3: Tag Neighborhood -->
      <section class="phase-section" aria-label="Phase 3: Tag Neighborhood">
        <TagNeighborhood
          {bridge}
          seedTags={phase3SeedTags}
          project={$selectedProject}
          investigationTopic={currentQuery}
          onResults={(results) => {
            // Capture discovered tags from Phase 3 for Phase 4 synthesis
            if (results.length > 0) {
              const allTags = results.flatMap((r) => r.tags);
              phase3DiscoveredTags = Array.from(new Set(allTags));
              completedPhase = Math.max(completedPhase, 3);
              // Auto-advance to Phase 4 and run gap-fill
              currentPhase = 4;
              void runPhase4GapFill();
            }
          }}
          onPin={(entry) => handlePin(entry as InvestigateResult)}
        />
      </section>
    {:else if currentPhase === 4}
      <!-- Phase 4: Gap Analysis -->
      <section class="phase-section" aria-label="Phase 4: Gap Analysis">
        <h3 class="phase-section-title">You might also want to look at:</h3>

        {#if phase4Loading}
          <LoadingSkeleton rows={3} label="Running gap analysis..." />
        {:else if phase4Error}
          <div class="error-banner" role="alert">
            <strong>Error:</strong> {phase4Error}
          </div>
        {:else if phase4Results.length === 0}
          <p class="empty-state">No additional entries found.</p>
        {:else}
          <ul class="result-cards" aria-label="Gap analysis results">
            {#each phase4Results as result (result.id)}
              <li class="result-card">
                <button
                  class="card-body"
                  onclick={() => handlePivot(result)}
                  aria-label="Pivot to: {contentPreview(result.content)}"
                >
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
                </button>
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
      </section>
    {/if}
  </div>
</section>

<style>
  .investigate-mode {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  /* Header with back button */
  .investigate-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .back-btn {
    padding: 0.35rem 0.75rem;
    font-size: 0.85rem;
    background: none;
    color: var(--accent, #89b4fa);
    border: 1px solid color-mix(in srgb, var(--accent, #89b4fa) 40%, transparent);
    border-radius: 4px;
    cursor: pointer;
    white-space: nowrap;
  }

  .back-btn:hover {
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
  }

  .investigate-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  /* Phase indicator */
  .phase-indicator {
    padding: 0.5rem 0;
  }

  .phase-list {
    display: flex;
    gap: 0.25rem;
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .phase-item {
    flex: 1;
  }

  .phase-btn {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    width: 100%;
    padding: 0.4rem 0.6rem;
    background: color-mix(in srgb, var(--bg-highlight, #313244) 30%, transparent);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    color: var(--fg-muted, #a6adc8);
    font-size: 0.8rem;
    cursor: default;
    transition: background 0.15s, border-color 0.15s;
  }

  .phase-btn:not(:disabled) {
    cursor: pointer;
  }

  .phase-btn--active {
    background: color-mix(in srgb, var(--accent, #89b4fa) 20%, transparent);
    border-color: var(--accent, #89b4fa);
    color: var(--accent, #89b4fa);
  }

  .phase-btn--completed:not(.phase-btn--active) {
    background: color-mix(in srgb, #a6e3a1 10%, transparent);
    border-color: color-mix(in srgb, #a6e3a1 40%, transparent);
    color: #a6e3a1;
  }

  .phase-btn:disabled:not(.phase-btn--active):not(.phase-btn--completed) {
    opacity: 0.4;
  }

  .phase-number {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.4rem;
    height: 1.4rem;
    border-radius: 50%;
    font-size: 0.7rem;
    font-weight: 700;
    background: color-mix(in srgb, currentColor 20%, transparent);
    flex-shrink: 0;
  }

  .phase-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Breadcrumb trail */
  .breadcrumb-trail {
    padding: 0.25rem 0;
  }

  .breadcrumb-list {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
    list-style: none;
    margin: 0;
    padding: 0;
    font-size: 0.8rem;
  }

  .breadcrumb-item {
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }

  .breadcrumb-link {
    background: none;
    border: none;
    color: var(--accent, #89b4fa);
    cursor: pointer;
    padding: 0.1rem 0.25rem;
    border-radius: 2px;
    font-size: 0.8rem;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .breadcrumb-link:hover {
    text-decoration: underline;
    background: color-mix(in srgb, var(--accent, #89b4fa) 10%, transparent);
  }

  .breadcrumb-current {
    color: var(--fg, #cdd6f4);
    font-weight: 500;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .breadcrumb-separator {
    color: var(--fg-muted, #a6adc8);
  }

  /* Phase content area */
  .phase-content {
    min-height: 200px;
  }

  .phase-section-title {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0 0 0.75rem;
  }

  /* Result cards */
  .result-cards {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    list-style: none;
    margin: 0;
    padding: 0;
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
    gap: 0.35rem;
    padding: 0.75rem;
    background: none;
    border: none;
    color: var(--fg, #cdd6f4);
    text-align: left;
    cursor: pointer;
    font-size: 0.85rem;
    min-width: 0;
  }

  .card-body:hover {
    background: color-mix(in srgb, var(--accent, #89b4fa) 8%, transparent);
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .card-type {
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.1rem 0.35rem;
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
    gap: 0.25rem;
  }

  .card-tag {
    display: inline-block;
    padding: 0.1rem 0.35rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 12%, transparent);
    color: var(--accent, #89b4fa);
    border-radius: 8px;
    font-size: 0.65rem;
    font-weight: 500;
  }

  .pin-btn {
    align-self: center;
    padding: 0.3rem 0.6rem;
    font-size: 0.75rem;
    font-weight: 500;
    background: none;
    color: var(--fg-muted, #a6adc8);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    cursor: pointer;
    white-space: nowrap;
    margin-right: 0.5rem;
    flex-shrink: 0;
  }

  .pin-btn:hover {
    color: var(--accent, #89b4fa);
    border-color: var(--accent, #89b4fa);
  }

  /* Error and empty states */
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
</style>
