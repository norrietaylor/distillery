<script lang="ts">
  /**
   * Recall widget — standalone MCP Apps surface for the /recall skill.
   *
   * Minimal mobile-first search experience: connect the MCP bridge, render a
   * search bar, show ranked results. No tabs, no project selector, no detail
   * side-panel — those belong to sibling widgets (investigate, pour) or the
   * legacy dashboard.
   */

  import { onMount, onDestroy } from "svelte";
  import { McpBridge } from "$lib/mcp-bridge";
  import SearchBar from "../../components/SearchBar.svelte";

  const bridge = new McpBridge({
    appName: "Distillery Recall",
    appVersion: "0.1.0",
  });

  let initializing = $state(true);
  let connectError = $state<string | null>(null);

  onMount(async () => {
    try {
      await bridge.connect();
    } catch (err) {
      connectError = err instanceof Error ? err.message : "Failed to connect to MCP host";
    } finally {
      initializing = false;
    }
  });

  onDestroy(async () => {
    await bridge.disconnect();
  });
</script>

<div class="recall">
  <header class="recall-header">
    <h1 class="recall-title">Recall</h1>
    <p class="recall-subtitle">Ranked semantic search across the knowledge base.</p>
  </header>

  <main class="recall-main">
    {#if initializing}
      <p class="recall-status" role="status" aria-live="polite">Connecting…</p>
    {:else if connectError}
      <div class="error-banner" role="alert">
        <strong>Connection error:</strong>
        {connectError}
      </div>
    {:else}
      <SearchBar {bridge} />
    {/if}
  </main>
</div>

<style>
  :global(*) {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  :global(body) {
    font-family: system-ui, -apple-system, sans-serif;
    background: var(--bg, #1e1e2e);
    color: var(--fg, #cdd6f4);
    min-height: 100vh;
  }

  .recall {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    max-width: 720px;
    margin: 0 auto;
    padding: 1rem;
    gap: 1rem;
  }

  .recall-header {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border, #313244);
  }

  .recall-title {
    font-size: 1.25rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--fg, #cdd6f4);
  }

  .recall-subtitle {
    font-size: 0.85rem;
    color: var(--fg-muted, #a6adc8);
  }

  .recall-main {
    flex: 1;
  }

  .recall-status {
    font-size: 0.875rem;
    color: var(--fg-muted, #a6adc8);
    font-style: italic;
    padding: 1rem 0;
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
