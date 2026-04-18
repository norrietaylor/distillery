<script lang="ts">
  /**
   * RecentEntries — newest-first entries list for the Home tab.
   *
   * Replaces the old RecentCorrections component, which fanned out
   * 1 + 2N tool calls per refresh (one distillery_list, then a
   * distillery_relations + distillery_get for each returned session
   * entry). That fan-out was the biggest single contributor to the
   * 60 req/min HTTP rate limit failures — see the commit message
   * on 9ca5bc7 and the RateLimitMiddleware at
   * src/distillery/mcp/middleware.py.
   *
   * This component issues exactly ONE distillery_list call per
   * refresh and renders the entries inline with no follow-up lookups
   * at all. No relations, no per-entry gets.
   */
  import LoadingSkeleton from "./LoadingSkeleton.svelte";
  import type { McpBridge } from "$lib/mcp-bridge";
  import { refreshTick, selectedProject } from "$lib/stores";

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge: McpBridge;
    /** How many recent entries to fetch. Defaults to 10. */
    limit?: number;
  }

  /** A recent-entries list item — the subset of Entry fields we render. */
  interface RecentEntry {
    id: string;
    content: string;
    entry_type: string;
    source: string;
    created_at: string;
    project: string | null;
  }

  let { bridge, limit = 10 }: Props = $props();

  let entries = $state<RecentEntry[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let loadSeq = 0;

  /**
   * Fetch the N most-recent entries with a single distillery_list call.
   *
   * Uses ``content_max_length`` to cap the per-entry content payload at
   * 200 chars — enough for a usable preview without bloating the
   * response, and the server side already supports this trimming
   * (see src/distillery/mcp/tools/crud.py).
   */
  async function loadEntries() {
    const seq = ++loadSeq;
    loading = true;
    error = null;
    try {
      const project = $selectedProject;
      const args: Record<string, unknown> = {
        limit,
        content_max_length: 200,
      };
      if (project) {
        args["project"] = project;
      }

      const result = await bridge.callTool("distillery_list", args);
      if (seq !== loadSeq) return;

      if (result.isError) {
        error = result.text || "Failed to load recent entries";
        entries = [];
        return;
      }

      entries = parseEntries(result.text);
    } catch (err) {
      if (seq !== loadSeq) return;
      error = err instanceof Error ? err.message : "Failed to load recent entries";
      entries = [];
    } finally {
      if (seq === loadSeq) loading = false;
    }
  }

  /**
   * Parse a ``distillery_list`` response into RecentEntry objects.
   *
   * Handles the server's ``{entries, count, total_count, ...}``
   * envelope, with fallbacks to a flat array or a bare object for
   * older response shapes.
   */
  function parseEntries(text: string): RecentEntry[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        const wrapped = parsed as Record<string, unknown>;
        if (Array.isArray(wrapped.entries)) {
          return (wrapped.entries as Array<Record<string, unknown>>).map(normalize);
        }
        return [normalize(wrapped)];
      }
      if (Array.isArray(parsed)) {
        return parsed.map((e) => normalize(e as Record<string, unknown>));
      }
    } catch {
      // Non-JSON — empty list.
    }
    return [];
  }

  function normalize(obj: Record<string, unknown>): RecentEntry {
    const raw = obj as Partial<RecentEntry>;
    return {
      id: String(raw.id ?? crypto.randomUUID()),
      content: String(raw.content ?? ""),
      entry_type: String(raw.entry_type ?? ""),
      source: String(raw.source ?? ""),
      created_at: String(raw.created_at ?? ""),
      project: typeof raw.project === "string" ? raw.project : null,
    };
  }

  /** First line of content, truncated to 120 chars. */
  function contentPreview(content: string): string {
    const first = content.split("\n")[0] ?? content;
    return first.length > 120 ? first.slice(0, 117) + "…" : first;
  }

  /**
   * Format an ISO timestamp as a relative time ("2 hours ago", "3 days ago").
   *
   * Falls back to the raw ISO string if parsing fails. Only positive
   * deltas are rendered as "ago"; future-dated entries render as "just now".
   */
  function relativeTime(iso: string): string {
    if (!iso) return "";
    const t = new Date(iso).getTime();
    if (Number.isNaN(t)) return iso;
    const deltaSec = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (deltaSec < 60) return "just now";
    if (deltaSec < 3600) {
      const m = Math.floor(deltaSec / 60);
      return `${m} minute${m === 1 ? "" : "s"} ago`;
    }
    if (deltaSec < 86400) {
      const h = Math.floor(deltaSec / 3600);
      return `${h} hour${h === 1 ? "" : "s"} ago`;
    }
    const d = Math.floor(deltaSec / 86400);
    return `${d} day${d === 1 ? "" : "s"} ago`;
  }

  // React to refresh ticks and project changes
  $effect(() => {
    const _tick = $refreshTick;
    const _project = $selectedProject;
    void _tick;
    void _project;
    void loadEntries();
  });
</script>

<section class="recent-entries" aria-labelledby="recent-entries-heading">
  <h2 class="section-title" id="recent-entries-heading">Recent Entries</h2>

  {#if loading}
    <LoadingSkeleton rows={3} label="Loading recent entries..." />
  {:else if error}
    <div class="error-message" role="alert">
      <strong>Error:</strong>
      {error}
    </div>
  {:else if entries.length === 0}
    <p class="empty-state">No entries yet.</p>
  {:else}
    <ul class="entry-list" aria-label="Recent entries">
      {#each entries as entry (entry.id)}
        <li class="entry-list__item">
          <div class="entry-header">
            <span class="entry-type-badge">{entry.entry_type || "entry"}</span>
            {#if entry.project}
              <span class="entry-project">{entry.project}</span>
            {/if}
            <span class="entry-time">{relativeTime(entry.created_at)}</span>
          </div>
          <p class="entry-content">{contentPreview(entry.content)}</p>
          {#if entry.source}
            <p class="entry-source">{entry.source}</p>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .recent-entries {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .section-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
    padding-bottom: 0.25rem;
    border-bottom: 1px solid var(--border, #313244);
  }

  .entry-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .entry-list__item {
    padding: 0.6rem 0.8rem;
    background: var(--card-bg, #181825);
    border: 1px solid var(--border, #313244);
    border-radius: 6px;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  .entry-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.75rem;
    color: var(--fg-muted, #a6adc8);
  }

  .entry-type-badge {
    padding: 0.1rem 0.4rem;
    background: var(--accent-bg, #313244);
    color: var(--accent-fg, #cdd6f4);
    border-radius: 999px;
    font-weight: 500;
    text-transform: lowercase;
  }

  .entry-project {
    font-style: italic;
  }

  .entry-time {
    margin-left: auto;
    opacity: 0.85;
  }

  .entry-content {
    font-size: 0.875rem;
    color: var(--fg, #cdd6f4);
    margin: 0;
    line-height: 1.4;
    overflow-wrap: anywhere;
  }

  .entry-source {
    font-size: 0.7rem;
    color: var(--fg-muted, #a6adc8);
    margin: 0;
    opacity: 0.8;
  }

  .empty-state {
    font-size: 0.875rem;
    color: var(--fg-muted, #a6adc8);
    padding: 0.5rem 0;
  }

  .error-message {
    font-size: 0.875rem;
    padding: 0.75rem 1rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    border: 1px solid var(--error, #f38ba8);
    border-radius: 6px;
    color: var(--error, #f38ba8);
  }
</style>
