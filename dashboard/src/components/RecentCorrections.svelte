<script lang="ts">
  import { selectedProject, refreshTick } from "$lib/stores";
  import LoadingSkeleton from "./LoadingSkeleton.svelte";
  import CorrectionCard from "./CorrectionCard.svelte";
  import type { CorrectionEntry } from "./CorrectionCard.svelte";
  import type { McpBridge } from "$lib/mcp-bridge";

  interface Props {
    bridge: McpBridge;
  }

  let { bridge }: Props = $props();

  let loading = $state(true);
  let error = $state<string | null>(null);
  let corrections = $state<CorrectionEntry[]>([]);

  /** Return ISO string for N days ago. */
  function daysAgo(n: number): string {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString();
  }

  /** Derive a brief summary from raw content (first 80 chars). */
  function toSummary(content: string): string {
    const trimmed = content.trim().replace(/\s+/g, " ");
    return trimmed.length > 80 ? trimmed.slice(0, 77) + "..." : trimmed;
  }

  async function loadCorrections() {
    loading = true;
    error = null;

    try {
      const project = $selectedProject;
      const dateFrom = daysAgo(7);

      // Fetch recent session entries
      const listArgs: Record<string, unknown> = {
        entry_type: "session",
        limit: 10,
        date_from: dateFrom,
      };
      if (project) listArgs["project"] = project;

      const listResult = await bridge.callTool("distillery_list", listArgs);

      if (listResult.isError) {
        throw new Error(listResult.text || "Failed to fetch session entries");
      }

      // Parse entry IDs from the text response.
      // The MCP server returns a newline-separated list of entries or JSON.
      const entryIds = parseEntryIds(listResult.text);

      if (entryIds.length === 0) {
        corrections = [];
        return;
      }

      // For each entry, check if it has "corrects" relations
      const correctionResults: CorrectionEntry[] = [];

      for (const entry of entryIds) {
        try {
          const relResult = await bridge.callTool("distillery_relations", {
            action: "get",
            entry_id: entry.id,
            relation_type: "corrects",
          });

          if (relResult.isError || !relResult.text) continue;

          const relatedIds = parseRelatedIds(relResult.text);
          if (relatedIds.length === 0) continue;

          // Fetch the original entry content for the first relation
          const originalId = relatedIds[0];
          let originalContent = "";
          try {
            const getResult = await bridge.callTool("distillery_get", { entry_id: originalId });
            if (!getResult.isError && getResult.text) {
              originalContent = extractContent(getResult.text);
            }
          } catch {
            originalContent = "(original content unavailable)";
          }

          correctionResults.push({
            id: entry.id,
            summary: toSummary(entry.content),
            content: entry.content,
            originalId,
            originalContent: originalContent || "(original content unavailable)",
            createdAt: entry.createdAt,
          });
        } catch {
          // Skip entries where relation lookup fails
        }
      }

      corrections = correctionResults;
    } catch (err) {
      error = err instanceof Error ? err.message : "Failed to load corrections";
      corrections = [];
    } finally {
      loading = false;
    }
  }

  interface ParsedEntry {
    id: string;
    content: string;
    createdAt: string;
  }

  /**
   * Parse entry IDs and content from MCP list tool text response.
   * Handles both JSON array and plain-text list formats.
   */
  function parseEntryIds(text: string): ParsedEntry[] {
    if (!text) return [];

    // Attempt JSON parse
    try {
      const parsed: unknown = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed
          .filter(
            (item): item is { id: string; content?: string; created_at?: string } =>
              typeof item === "object" && item !== null && typeof item.id === "string",
          )
          .map((item) => ({
            id: item.id,
            content: item.content ?? "",
            createdAt: item.created_at ?? new Date().toISOString(),
          }));
      }
    } catch {
      // Not JSON — fall through to line parsing
    }

    // Plain text: one entry per line, format: "<id> | <content>" or just "<id>"
    return text
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0 && !line.startsWith("#"))
      .map((line) => {
        const parts = line.split("|").map((p) => p.trim());
        return {
          id: parts[0] ?? line,
          content: parts[1] ?? "",
          createdAt: parts[2] ?? new Date().toISOString(),
        };
      })
      .filter((e) => e.id.length > 0);
  }

  /**
   * Parse related entry IDs from relations tool text response.
   */
  function parseRelatedIds(text: string): string[] {
    if (!text) return [];

    // Attempt JSON parse
    try {
      const parsed: unknown = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed
          .filter(
            (item): item is { target_id: string } | { id: string } =>
              typeof item === "object" && item !== null,
          )
          .map((item) => {
            const asTarget = item as { target_id?: string; id?: string };
            return asTarget.target_id ?? asTarget.id ?? "";
          })
          .filter((id) => id.length > 0);
      }
    } catch {
      // Not JSON
    }

    // Plain text: one ID per line
    return text
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0 && !line.startsWith("#"));
  }

  /**
   * Extract content field from a get tool text response.
   */
  function extractContent(text: string): string {
    // Attempt JSON parse
    try {
      const parsed: unknown = JSON.parse(text);
      if (
        typeof parsed === "object" &&
        parsed !== null &&
        "content" in parsed &&
        typeof (parsed as { content: unknown }).content === "string"
      ) {
        return (parsed as { content: string }).content;
      }
    } catch {
      // Not JSON — return as-is
    }
    return text;
  }

  // React to refresh ticks and project changes
  $effect(() => {
    const _tick = $refreshTick;
    const _project = $selectedProject;
    void loadCorrections();
  });

</script>

<section class="recent-corrections" aria-labelledby="recent-corrections-heading">
  <h2 class="section-title" id="recent-corrections-heading">Recent Corrections</h2>

  {#if loading}
    <LoadingSkeleton rows={3} label="Loading recent corrections..." />
  {:else if error}
    <div class="error-message" role="alert">
      <strong>Error:</strong>
      {error}
    </div>
  {:else if corrections.length === 0}
    <p class="empty-state">No corrections found in the last 7 days.</p>
  {:else}
    <ul class="corrections-list" aria-label="Recent corrections">
      {#each corrections as correction (correction.id)}
        <li class="corrections-list__item">
          <CorrectionCard {correction} />
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .recent-corrections {
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

  .corrections-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .corrections-list__item {
    display: block;
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
