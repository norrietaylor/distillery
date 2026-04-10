<script lang="ts">
  import { currentUser, triggerRefresh, isLoading, activeTab, userRole, inboxBadgeCount, reviewBadgeCount } from "$lib/stores";
  import type { DashboardTab, UserRole } from "$lib/stores";

  interface Props {
    title?: string;
  }

  let { title = "Distillery Dashboard" }: Props = $props();

  interface TabDef {
    id: DashboardTab;
    label: string;
    /** Minimum role required. null = any authenticated user. */
    minRole: UserRole | null;
  }

  const tabs: TabDef[] = [
    { id: "home", label: "Home", minRole: null },
    { id: "explore", label: "Explore", minRole: null },
    { id: "capture", label: "Capture", minRole: null },
    { id: "manage", label: "Manage", minRole: "curator" },
  ];

  /** Role hierarchy for access checks. */
  const roleRank: Record<UserRole, number> = {
    developer: 0,
    curator: 1,
    admin: 2,
  };

  function canAccessTab(tab: TabDef): boolean {
    if (!tab.minRole) return true;
    const role = $userRole;
    if (!role) return false;
    return roleRank[role] >= roleRank[tab.minRole];
  }

  function manageBadgeCount(): number | null {
    const inbox = $inboxBadgeCount;
    const review = $reviewBadgeCount;
    if (inbox === null && review === null) return null;
    return (inbox ?? 0) + (review ?? 0);
  }

  function getBadge(tabId: DashboardTab): number | null {
    if (tabId === "manage") return manageBadgeCount();
    return null;
  }

  function selectTab(tab: TabDef): void {
    if (canAccessTab(tab)) {
      activeTab.set(tab.id);
    }
  }
</script>

<nav class="navbar">
  <div class="navbar-left">
    <span class="navbar-title">{title}</span>
    <div class="tab-list" role="tablist" aria-label="Dashboard sections">
      {#each tabs as tab (tab.id)}
        {@const accessible = canAccessTab(tab)}
        {@const badge = getBadge(tab.id)}
        <button
          role="tab"
          class="tab-button"
          class:tab-button--active={$activeTab === tab.id}
          class:tab-button--disabled={!accessible}
          aria-selected={$activeTab === tab.id}
          aria-disabled={!accessible}
          disabled={!accessible}
          onclick={() => selectTab(tab)}
          data-tab={tab.id}
        >
          {tab.label}
          {#if badge !== null && badge > 0}
            <span class="tab-badge" aria-label="{badge} items">{badge}</span>
          {/if}
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
    gap: 0.75rem;
  }

  .navbar-title {
    font-size: 1.1rem;
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  .tab-list {
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }

  .tab-button {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.35rem 0.65rem;
    font-size: 0.85rem;
    font-weight: 500;
    background: transparent;
    color: var(--nav-fg-muted, #a6adc8);
    border: 1px solid transparent;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s, color 0.15s;
  }

  .tab-button:hover:not(:disabled) {
    background: var(--btn-bg, #313244);
    color: var(--nav-fg, #cdd6f4);
  }

  .tab-button--active {
    background: var(--btn-bg, #313244);
    color: var(--nav-fg, #cdd6f4);
    border-color: var(--border, #45475a);
  }

  .tab-button--disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .tab-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.1rem;
    height: 1.1rem;
    padding: 0 0.3rem;
    font-size: 0.7rem;
    font-weight: 600;
    background: var(--accent, #cba6f7);
    color: var(--bg, #1e1e2e);
    border-radius: 999px;
    line-height: 1;
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
