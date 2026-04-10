<script lang="ts">
  import type { McpBridge } from "$lib/mcp-bridge";
  import BookmarkCapture from "./BookmarkCapture.svelte";
  import WatchSource from "./WatchSource.svelte";

  interface Props {
    bridge: McpBridge;
  }

  let { bridge }: Props = $props();
</script>

<div class="capture-tab">
  <div class="capture-cards">
    <!-- Bookmark capture card (Unit 1) -->
    <BookmarkCapture {bridge} />

    <!-- Watch source card (Unit 2) -->
    <div class="capture-card">
      <WatchSource {bridge} />
    </div>
  </div>

  <!-- Active sources table (Unit 3) — populated by SourcesTable component -->
  <div class="sources-table-placeholder">
    <h2 class="card-title">Current Sources</h2>
    <p class="card-placeholder">Sources table coming soon.</p>
  </div>
</div>

<style>
  .capture-tab {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .capture-cards {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
  }

  @media (max-width: 768px) {
    .capture-cards {
      grid-template-columns: 1fr;
    }
  }

  .capture-card {
    background: var(--card-bg, #181825);
    border: 1px solid var(--border, #313244);
    border-radius: 8px;
    padding: 1.25rem;
  }

  .capture-card--placeholder {
    min-height: 200px;
  }

  .sources-table-placeholder {
    background: var(--card-bg, #181825);
    border: 1px solid var(--border, #313244);
    border-radius: 8px;
    padding: 1.25rem;
    min-height: 150px;
  }

  .card-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin-bottom: 0.75rem;
  }

  .card-placeholder {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.875rem;
  }
</style>
