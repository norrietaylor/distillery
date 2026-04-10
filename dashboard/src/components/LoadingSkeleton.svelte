<script lang="ts">
  interface Props {
    /** Number of skeleton rows to render. Default 4. */
    rows?: number;
    /** Whether to show a header skeleton above the rows. Default true. */
    showHeader?: boolean;
    /** ARIA label describing what is loading. */
    label?: string;
  }

  let {
    rows = 4,
    showHeader = true,
    label = "Loading data...",
  }: Props = $props();
</script>

<div class="skeleton-container" role="status" aria-label={label} aria-busy="true">
  {#if showHeader}
    <div class="skeleton-header"></div>
  {/if}
  {#each { length: rows } as _, i (i)}
    <div class="skeleton-row" style="width: {85 + (i % 3) * 5}%"></div>
  {/each}
</div>

<style>
  .skeleton-container {
    padding: 1rem 0;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .skeleton-header {
    height: 1.25rem;
    width: 40%;
    border-radius: 4px;
    background: var(--skeleton-bg, #313244);
    animation: pulse 1.5s ease-in-out infinite;
    margin-bottom: 0.4rem;
  }

  .skeleton-row {
    height: 0.85rem;
    border-radius: 4px;
    background: var(--skeleton-bg, #313244);
    animation: pulse 1.5s ease-in-out infinite;
  }

  .skeleton-row:nth-child(even) {
    animation-delay: 0.2s;
  }

  @keyframes pulse {
    0%, 100% {
      opacity: 1;
    }
    50% {
      opacity: 0.4;
    }
  }
</style>
