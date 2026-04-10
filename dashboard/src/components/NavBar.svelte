<script lang="ts">
  import { currentUser, triggerRefresh, isLoading, activeTab } from "$lib/stores";
  import type { DashboardTab } from "$lib/stores";

  interface Props {
    title?: string;
  }

  let { title = "Distillery Dashboard" }: Props = $props();

  const tabs: { id: DashboardTab; label: string }[] = [
    { id: "home", label: "Home" },
    { id: "capture", label: "Capture" },
  ];

  function setTab(tab: DashboardTab): void {
    activeTab.set(tab);
  }
</script>

<nav class="navbar">
  <div class="navbar-left">
    <span class="navbar-title">{title}</span>
    <div class="tab-bar" role="tablist">
      {#each tabs as tab (tab.id)}
        <button
          class="tab-button"
          class:tab-button--active={$activeTab === tab.id}
          role="tab"
          aria-selected={$activeTab === tab.id}
          aria-controls="{tab.id}-panel"
          onclick={() => setTab(tab.id)}
        >
          {tab.label}
        </button>
      {/each}
    </div>
  </div>
  <div class="navbar-right">
    {#if $currentUser}
      <span class="user-indicator" title={$currentUser.displayName}>
        {#if $currentUser.avatarUrl}
          <img
            class="user-avatar"
            src={$currentUser.avatarUrl}
            alt={$currentUser.displayName}
            width="24"
            height="24"
          />
        {/if}
        <span class="user-login">{$currentUser.login}</span>
      </span>
    {:else}
      <span class="user-indicator user-indicator--loading">Loading...</span>
    {/if}

    <button
      class="refresh-button"
      onclick={triggerRefresh}
      disabled={$isLoading}
      aria-label="Refresh data"
    >
      {$isLoading ? "Refreshing..." : "Refresh"}
    </button>
  </div>
</nav>

<style>
  .navbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.75rem 1rem;
    background: var(--nav-bg, #1e1e2e);
    color: var(--nav-fg, #cdd6f4);
    border-bottom: 1px solid var(--border, #313244);
    gap: 1rem;
  }

  .navbar-left {
    display: flex;
    align-items: center;
    gap: 1.25rem;
  }

  .navbar-title {
    font-size: 1.1rem;
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  .tab-bar {
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }

  .tab-button {
    padding: 0.3rem 0.75rem;
    font-size: 0.875rem;
    font-weight: 500;
    background: transparent;
    color: var(--nav-fg-muted, #a6adc8);
    border: 1px solid transparent;
    border-radius: 4px;
    cursor: pointer;
    transition: color 0.15s, background 0.15s, border-color 0.15s;
  }

  .tab-button:hover:not(.tab-button--active) {
    color: var(--nav-fg, #cdd6f4);
    background: var(--btn-bg, #313244);
  }

  .tab-button--active {
    color: var(--accent, #89b4fa);
    border-color: var(--accent, #89b4fa);
    background: color-mix(in srgb, var(--accent, #89b4fa) 10%, transparent);
  }

  .navbar-right {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .user-indicator {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.875rem;
    color: var(--nav-fg-muted, #a6adc8);
  }

  .user-indicator--loading {
    opacity: 0.6;
  }

  .user-avatar {
    border-radius: 50%;
    object-fit: cover;
  }

  .user-login {
    font-weight: 500;
  }

  .refresh-button {
    padding: 0.35rem 0.75rem;
    font-size: 0.8rem;
    font-weight: 500;
    background: var(--btn-bg, #313244);
    color: var(--btn-fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
  }

  .refresh-button:hover:not(:disabled) {
    background: var(--btn-hover, #45475a);
  }

  .refresh-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
