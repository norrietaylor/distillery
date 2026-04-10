<script lang="ts">
  import LoadingSkeleton from "./LoadingSkeleton.svelte";
  import ExpiryCard from "./ExpiryCard.svelte";
  import type { McpBridge } from "$lib/mcp-bridge";
  import { refreshTick, selectedProject } from "$lib/stores";

  interface Props {
    bridge: McpBridge;
  }

  interface ExpiryEntry {
    id: string;
    title: string;
    expires_at: string;
    daysRemaining: number;
  }

  let { bridge }: Props = $props();

  let entries = $state<ExpiryEntry[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function loadExpiring() {
    loading = true;
    error = null;
    try {
      const project = $selectedProject;
      const args: Record<string, unknown> = { limit: 10 };
      if (project) {
        args["project"] = project;
      }

      const result = await bridge.callTool("distillery_list", args);

      if (result.isError) {
        error = "Failed to load expiring entries.";
        return;
      }

      const now = new Date();
      const cutoff = new Date(now.getTime() + 14 * 24 * 60 * 60 * 1000);

      const parsed = parseEntries(result.text);
      entries = parsed
        .filter((e) => {
          if (!e.expires_at) return false;
          const exp = new Date(e.expires_at);
          return exp > now && exp <= cutoff;
        })
        .map((e) => {
          const exp = new Date(e.expires_at);
          const daysRemaining = Math.ceil(
            (exp.getTime() - now.getTime()) / (1000 * 60 * 60 * 24),
          );
          return {
            id: e.id,
            title: e.title || e.id,
            expires_at: e.expires_at,
            daysRemaining,
          };
        })
        .sort((a, b) => a.daysRemaining - b.daysRemaining);
    } catch (err) {
      error = err instanceof Error ? err.message : "Failed to load expiring entries.";
    } finally {
      loading = false;
    }
  }

  function parseEntries(
    text: string,
  ): Array<{ id: string; title: string; expires_at: string }> {
    try {
      const data = JSON.parse(text);
      if (Array.isArray(data)) {
        return data as Array<{ id: string; title: string; expires_at: string }>;
      }
      if (data && Array.isArray(data.entries)) {
        return data.entries as Array<{ id: string; title: string; expires_at: string }>;
      }
    } catch {
      // Non-JSON response — return empty
    }
    return [];
  }

  // Re-fetch on refresh tick or project change
  $effect(() => {
    const _tick = $refreshTick;
    const _project = $selectedProject;
    void _tick;
    void _project;
    void loadExpiring();
  });
</script>

<section class="expiring-soon" aria-labelledby="expiring-heading">
  <h2 id="expiring-heading" class="section-title">Expiring Soon</h2>

  {#if loading}
    <LoadingSkeleton rows={3} label="Loading expiring entries..." />
  {:else if error}
    <div class="error-message" role="alert">{error}</div>
  {:else if entries.length === 0}
    <div class="empty-state" role="status">
      <p>No entries expiring in the next 14 days.</p>
      <p class="empty-hint">Entries with expiry dates approaching will appear here.</p>
    </div>
  {:else}
    <ul class="entry-list" aria-label="Expiring entries">
      {#each entries as entry (entry.id)}
        <li>
          <ExpiryCard {entry} {bridge} onAction={loadExpiring} />
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .expiring-soon {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .section-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .error-message {
    padding: 0.6rem 0.9rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 12%, transparent);
    border: 1px solid var(--error, #f38ba8);
    border-radius: 6px;
    color: var(--error, #f38ba8);
    font-size: 0.875rem;
  }

  .empty-state {
    padding: 1.5rem;
    text-align: center;
    color: var(--fg-muted, #a6adc8);
    font-size: 0.9rem;
    border: 1px dashed var(--border, #313244);
    border-radius: 8px;
  }

  .empty-hint {
    font-size: 0.8rem;
    margin-top: 0.35rem;
    opacity: 0.7;
  }

  .entry-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
</style>
