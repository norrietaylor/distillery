<script lang="ts">
  import type { McpBridge } from "$lib/mcp-bridge";
  import BookmarkCapture from "./BookmarkCapture.svelte";
  import WatchSource from "./WatchSource.svelte";
  import SourcesTable from "./SourcesTable.svelte";

  interface Props {
    bridge: McpBridge;
  }

  let { bridge }: Props = $props();

  /** Bump to trigger SourcesTable refresh after a new source is added. */
  let sourcesRefreshToken = $state(0);

  function handleSourceAdded() {
    sourcesRefreshToken += 1;
  }
</script>

<div class="capture-tab">
  <div class="capture-cards">
    <!-- Bookmark capture card (Unit 1) -->
    <BookmarkCapture {bridge} />

    <!-- Watch source card (Unit 2) -->
    <div class="capture-card">
      <WatchSource {bridge} onSourceAdded={handleSourceAdded} />
    </div>
  </div>

  <!-- Active sources table (Unit 3) -->
  <SourcesTable {bridge} refreshToken={sourcesRefreshToken} />
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
</style>
