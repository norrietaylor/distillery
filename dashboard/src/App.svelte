<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import NavBar from "./components/NavBar.svelte";
  import ProjectSelector from "./components/ProjectSelector.svelte";
  import LoadingSkeleton from "./components/LoadingSkeleton.svelte";
  import { McpBridge } from "$lib/mcp-bridge";
  import {
    currentUser,
    isLoading,
    refreshIntervalMs,
    triggerRefresh,
    refreshTick,
  } from "$lib/stores";
  import type { UserIdentity } from "$lib/stores";

  const bridge = new McpBridge({ appName: "Distillery Dashboard", appVersion: "0.1.0" });

  let initializing = $state(true);
  let connectError = $state<string | null>(null);
  let autoRefreshHandle: ReturnType<typeof setInterval> | null = null;

  async function initBridge() {
    try {
      await bridge.connect();
      // Attempt to resolve user identity via MCP Apps context
      await resolveUserIdentity();
    } catch (err) {
      connectError =
        err instanceof Error ? err.message : "Failed to connect to MCP host";
    } finally {
      initializing = false;
    }
  }

  async function resolveUserIdentity() {
    try {
      // Call the MCP server to get the authenticated user's identity.
      // Falls back gracefully if the tool or field is unavailable.
      const result = await bridge.callTool("distillery_status");
      if (!result.isError && result.text) {
        const loginMatch = result.text.match(/user[:\s]+([^\s,\n]+)/i);
        if (loginMatch) {
          const login = loginMatch[1] ?? "user";
          const identity: UserIdentity = {
            login,
            displayName: login,
          };
          currentUser.set(identity);
          return;
        }
      }
    } catch {
      // Identity resolution is best-effort — not fatal
    }
    // Fallback: set a placeholder identity so the nav bar renders
    currentUser.set({ login: "user", displayName: "Authenticated User" });
  }

  function startAutoRefresh(intervalMs: number) {
    stopAutoRefresh();
    if (intervalMs > 0) {
      autoRefreshHandle = setInterval(() => {
        triggerRefresh();
      }, intervalMs);
    }
  }

  function stopAutoRefresh() {
    if (autoRefreshHandle !== null) {
      clearInterval(autoRefreshHandle);
      autoRefreshHandle = null;
    }
  }

  // React to changes in the configured interval
  $effect(() => {
    const interval = $refreshIntervalMs;
    if (!initializing) {
      startAutoRefresh(interval);
    }
    return () => stopAutoRefresh();
  });

  // Track loading state based on refresh ticks
  $effect(() => {
    const _tick = $refreshTick;
    if (!initializing && _tick > 0) {
      isLoading.set(true);
      // Reset loading indicator after a short window —
      // individual data sections manage their own loading states.
      setTimeout(() => isLoading.set(false), 500);
    }
  });

  onMount(() => {
    initBridge().then(() => {
      if (!connectError) {
        startAutoRefresh($refreshIntervalMs);
        // Trigger initial data load
        triggerRefresh();
      }
    });
  });

  onDestroy(async () => {
    stopAutoRefresh();
    await bridge.disconnect();
  });
</script>

<div class="app">
  <NavBar title="Distillery Dashboard" />

  <div class="toolbar">
    <ProjectSelector {bridge} />
  </div>

  <main class="content">
    {#if initializing}
      <LoadingSkeleton rows={6} label="Connecting to knowledge base..." />
    {:else if connectError}
      <div class="error-banner" role="alert">
        <strong>Connection error:</strong>
        {connectError}
      </div>
    {:else}
      <section id="home" class="home-section">
        <p class="placeholder-text">
          Dashboard home — knowledge base data will appear here.
        </p>
      </section>
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

  .app {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }

  .toolbar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 1rem;
    background: var(--toolbar-bg, #181825);
    border-bottom: 1px solid var(--border, #313244);
  }

  .content {
    flex: 1;
    max-width: 1200px;
    width: 100%;
    margin: 0 auto;
    padding: 1.5rem 1rem;
  }

  .home-section {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .placeholder-text {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.9rem;
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
