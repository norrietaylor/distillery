<script lang="ts">
  /**
   * ManageTab — the Manage top-level tab container.
   *
   * Provides internal sub-tab navigation for:
   *   - Inbox   : triage untyped entries
   *   - Review  : review queue for pending_review entries
   *   - Health  : aggregate knowledge base metrics (charts via Layercake)
   *   - Sources : feed source health table
   *
   * Role-gated to curator and admin roles. Developer role sees an access
   * denied message.
   */

  import type { McpBridge } from "$lib/mcp-bridge";
  import { userRole, inboxBadgeCount, reviewBadgeCount } from "$lib/stores";
  import InboxTriage from "./InboxTriage.svelte";
  import ReviewQueue from "./ReviewQueue.svelte";
  import HealthOverview from "./HealthOverview.svelte";
  import SourceHealth from "./SourceHealth.svelte";

  interface Props {
    bridge: McpBridge;
  }

  let { bridge }: Props = $props();

  type ManageSubTab = "inbox" | "review" | "health" | "sources";

  let activeSubTab = $state<ManageSubTab>("inbox");

  interface SubTabDef {
    id: ManageSubTab;
    label: string;
  }

  const subTabs: SubTabDef[] = [
    { id: "inbox", label: "Inbox" },
    { id: "review", label: "Review" },
    { id: "health", label: "Health" },
    { id: "sources", label: "Sources" },
  ];

  function getSubTabBadge(id: ManageSubTab): number | null {
    if (id === "inbox") return $inboxBadgeCount;
    if (id === "review") return $reviewBadgeCount;
    return null;
  }

  function roleState(): "loading" | "denied" | "allowed" {
    const role = $userRole;
    if (role === null) return "loading";
    if (role === "developer") return "denied";
    return "allowed";
  }
</script>

{#if roleState() === "loading"}
  <div class="loading-state" aria-busy="true" aria-label="Loading">
    <div class="loading-skeleton loading-skeleton--wide"></div>
    <div class="loading-skeleton loading-skeleton--medium"></div>
    <div class="loading-skeleton loading-skeleton--narrow"></div>
  </div>
{:else if roleState() === "denied"}
  <div class="access-denied" role="alert" aria-live="polite">
    <div class="access-denied__icon" aria-hidden="true">&#x1F512;</div>
    <h2 class="access-denied__title">Access Restricted</h2>
    <p class="access-denied__message">
      The Manage tab is available to curators and administrators only.
    </p>
  </div>
{:else}
  <div class="manage-tab">
    <!-- Sub-tab navigation -->
    <nav class="sub-nav" aria-label="Manage sections">
      <div class="sub-tab-list" role="tablist">
        {#each subTabs as tab (tab.id)}
          {@const badge = getSubTabBadge(tab.id)}
          <button
            role="tab"
            class="sub-tab-button"
            class:sub-tab-button--active={activeSubTab === tab.id}
            aria-selected={activeSubTab === tab.id}
            onclick={() => { activeSubTab = tab.id; }}
            data-subtab={tab.id}
          >
            {tab.label}
            {#if badge !== null && badge > 0}
              <span class="sub-tab-badge" aria-label="{badge} items">{badge}</span>
            {/if}
          </button>
        {/each}
      </div>
    </nav>

    <!-- Sub-tab content panels -->
    <div class="manage-content">
      {#if activeSubTab === "inbox"}
        <div
          role="tabpanel"
          aria-label="Inbox"
          class="sub-panel"
          data-panel="inbox"
        >
          <InboxTriage {bridge} />
        </div>
      {:else if activeSubTab === "review"}
        <div
          role="tabpanel"
          aria-label="Review"
          class="sub-panel"
          data-panel="review"
        >
          <ReviewQueue {bridge} />
        </div>
      {:else if activeSubTab === "health"}
        <div
          role="tabpanel"
          aria-label="Health"
          class="sub-panel"
          data-panel="health"
        >
          <HealthOverview {bridge} />
        </div>
      {:else if activeSubTab === "sources"}
        <div
          role="tabpanel"
          aria-label="Sources"
          class="sub-panel"
          data-panel="sources"
        >
          <SourceHealth {bridge} />
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .access-denied {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 4rem 2rem;
    text-align: center;
    gap: 0.75rem;
  }

  .access-denied__icon {
    font-size: 2.5rem;
    line-height: 1;
  }

  .access-denied__title {
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0;
  }

  .access-denied__message {
    font-size: 0.9rem;
    color: var(--fg-muted, #a6adc8);
    max-width: 32ch;
    margin: 0;
  }

  .manage-tab {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .sub-nav {
    border-bottom: 1px solid var(--border, #313244);
  }

  .sub-tab-list {
    display: flex;
    gap: 0;
    overflow-x: auto;
  }

  .sub-tab-button {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    background: transparent;
    color: var(--fg-muted, #a6adc8);
    border: none;
    border-bottom: 2px solid transparent;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s;
    white-space: nowrap;
  }

  .sub-tab-button:hover {
    color: var(--fg, #cdd6f4);
  }

  .sub-tab-button--active {
    color: var(--fg, #cdd6f4);
    border-bottom-color: var(--accent, #cba6f7);
    font-weight: 600;
  }

  .sub-tab-badge {
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

  .manage-content {
    flex: 1;
  }

  .sub-panel {
    padding: 1rem 0;
  }

  .loading-state {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 2rem;
  }

  .loading-skeleton {
    height: 1rem;
    border-radius: 4px;
    background: var(--surface1, #313244);
    animation: pulse 1.5s ease-in-out infinite;
  }

  .loading-skeleton--wide { width: 100%; }
  .loading-skeleton--medium { width: 66%; }
  .loading-skeleton--narrow { width: 40%; }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

</style>
