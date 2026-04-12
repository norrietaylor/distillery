<script lang="ts">
  import type { McpBridge } from "$lib/mcp-bridge";

  interface ExpiryEntry {
    id: string;
    title: string;
    expires_at: string;
    daysRemaining: number;
  }

  interface Props {
    entry: ExpiryEntry;
    bridge: McpBridge;
    onAction?: () => void;
  }

  let { entry, bridge, onAction }: Props = $props();

  let actionError = $state<string | null>(null);
  let actioning = $state(false);

  async function archive() {
    actioning = true;
    actionError = null;
    try {
      const result = await bridge.callTool("distillery_update", {
        entry_id: entry.id,
        status: "archived",
      });
      if (result.isError) {
        actionError = "Failed to archive entry.";
      } else {
        onAction?.();
      }
    } catch {
      actionError = "Failed to archive entry.";
    } finally {
      actioning = false;
    }
  }

  async function extend() {
    actioning = true;
    actionError = null;
    try {
      const plusThirty = new Date();
      plusThirty.setDate(plusThirty.getDate() + 30);
      const result = await bridge.callTool("distillery_update", {
        entry_id: entry.id,
        expires_at: plusThirty.toISOString(),
      });
      if (result.isError) {
        actionError = "Failed to extend entry.";
      } else {
        onAction?.();
      }
    } catch {
      actionError = "Failed to extend entry.";
    } finally {
      actioning = false;
    }
  }

  function formatDate(isoDate: string): string {
    try {
      return new Date(isoDate).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return isoDate;
    }
  }

  const urgencyClass = $derived(
    entry.daysRemaining <= 3
      ? "urgent"
      : entry.daysRemaining <= 7
        ? "warning"
        : "notice",
  );
</script>

<div class="expiry-card {urgencyClass}">
  <div class="card-header">
    <span class="entry-title">{entry.title}</span>
    <span class="days-badge" aria-label="{entry.daysRemaining} days remaining">
      {entry.daysRemaining}d
    </span>
  </div>
  <div class="card-body">
    <span class="expiry-date">Expires {formatDate(entry.expires_at)}</span>
  </div>
  {#if actionError}
    <div class="action-error" role="alert">{actionError}</div>
  {/if}
  <div class="card-actions">
    <button
      class="btn-archive"
      onclick={archive}
      disabled={actioning}
      aria-label="Archive {entry.title}"
    >
      Archive
    </button>
    <button
      class="btn-extend"
      onclick={extend}
      disabled={actioning}
      aria-label="Extend {entry.title}"
    >
      Extend +30d
    </button>
  </div>
</div>

<style>
  .expiry-card {
    border-radius: 6px;
    padding: 0.75rem 1rem;
    border-left: 4px solid var(--notice-color, #89b4fa);
    background: color-mix(in srgb, var(--notice-color, #89b4fa) 8%, var(--bg, #1e1e2e));
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .expiry-card.warning {
    border-left-color: var(--warning-color, #f9e2af);
    background: color-mix(in srgb, var(--warning-color, #f9e2af) 8%, var(--bg, #1e1e2e));
  }

  .expiry-card.urgent {
    border-left-color: var(--error, #f38ba8);
    background: color-mix(in srgb, var(--error, #f38ba8) 8%, var(--bg, #1e1e2e));
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .entry-title {
    font-weight: 600;
    font-size: 0.9rem;
    color: var(--fg, #cdd6f4);
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .days-badge {
    font-size: 0.75rem;
    font-weight: 700;
    padding: 0.15rem 0.4rem;
    border-radius: 3px;
    background: var(--notice-color, #89b4fa);
    color: var(--bg, #1e1e2e);
    flex-shrink: 0;
  }

  .warning .days-badge {
    background: var(--warning-color, #f9e2af);
  }

  .urgent .days-badge {
    background: var(--error, #f38ba8);
  }

  .card-body {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
  }

  .action-error {
    font-size: 0.8rem;
    color: var(--error, #f38ba8);
  }

  .card-actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.25rem;
  }

  button {
    font-size: 0.8rem;
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    border: 1px solid var(--border, #313244);
    cursor: pointer;
    transition: opacity 0.15s;
  }

  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-archive {
    background: transparent;
    color: var(--fg-muted, #a6adc8);
  }

  .btn-archive:hover:not(:disabled) {
    background: color-mix(in srgb, var(--fg-muted, #a6adc8) 15%, transparent);
  }

  .btn-extend {
    background: color-mix(in srgb, var(--notice-color, #89b4fa) 20%, transparent);
    color: var(--notice-color, #89b4fa);
    border-color: var(--notice-color, #89b4fa);
  }

  .btn-extend:hover:not(:disabled) {
    background: color-mix(in srgb, var(--notice-color, #89b4fa) 30%, transparent);
  }
</style>