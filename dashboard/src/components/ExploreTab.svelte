<script lang="ts">
  import type { McpBridge } from "$lib/mcp-bridge";

  interface Props {
    bridge?: McpBridge | null;
  }

  let { bridge = null }: Props = $props();
</script>

<section id="explore" class="explore-section">
  <div class="explore-placeholder">
    <h2>Explore Tab</h2>
    <p>Advanced search and knowledge base exploration coming soon.</p>
  </div>
</section>

<style>
  .explore-section {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .explore-placeholder {
    padding: 2rem;
    background: color-mix(in srgb, var(--bg-highlight, #313244) 30%, transparent);
    border: 1px solid var(--border, #45475a);
    border-radius: 8px;
    text-align: center;
  }

  .explore-placeholder h2 {
    font-size: 1.25rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: var(--fg, #cdd6f4);
  }

  .explore-placeholder p {
    color: var(--fg-muted, #a6adc8);
    font-size: 0.95rem;
  }
</style>
