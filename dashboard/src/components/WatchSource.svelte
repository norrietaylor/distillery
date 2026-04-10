<script lang="ts">
  import type { McpBridge } from "$lib/mcp-bridge";

  interface Props {
    bridge: McpBridge | null;
    /** Called after a source is successfully added. */
    onSourceAdded?: () => void;
  }

  let { bridge, onSourceAdded }: Props = $props();

  type SourceType = "rss" | "github";

  let url = $state("");
  let sourceType = $state<SourceType>("rss");
  let label = $state("");
  let trustWeight = $state(1.0);
  let importHistory = $state(false);

  let loading = $state(false);
  let successMessage = $state<string | null>(null);
  let errorMessage = $state<string | null>(null);

  /** Validate that the URL starts with http:// or https:// */
  function isValidUrl(value: string): boolean {
    return /^https?:\/\/.+/.test(value.trim());
  }

  let urlValid = $derived(isValidUrl(url));
  let canSubmit = $derived(urlValid && !loading);

  /** Format trust weight to exactly one decimal place to avoid floating point artifacts. */
  function formatTrustWeight(value: number): string {
    return (Math.round(value * 10) / 10).toFixed(1);
  }

  let trustWeightDisplay = $derived(formatTrustWeight(trustWeight));

  function handleSliderInput(e: Event) {
    const input = e.target as HTMLInputElement;
    trustWeight = Math.round(parseFloat(input.value) * 10) / 10;
  }

  function resetForm() {
    url = "";
    label = "";
    trustWeight = 1.0;
    importHistory = false;
    sourceType = "rss";
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
    if (!canSubmit || !bridge) return;

    loading = true;
    successMessage = null;
    errorMessage = null;

    try {
      const result = await bridge.callTool("distillery_watch", {
        action: "add",
        url: url.trim(),
        source_type: sourceType,
        label: label.trim(),
        trust_weight: Math.round(trustWeight * 10) / 10,
        sync_history: importHistory,
      });

      if (result.isError) {
        const msg = result.text ?? "";
        if (msg.toLowerCase().includes("duplicate") || msg.toLowerCase().includes("already")) {
          errorMessage = "This source URL is already being watched";
        } else {
          errorMessage = msg || "Failed to add source";
        }
      } else {
        successMessage = `Source added: ${url.trim()}`;
        resetForm();
        onSourceAdded?.();
      }
    } catch (err) {
      const raw = err instanceof Error ? err.message : String(err);
      if (raw.toLowerCase().includes("duplicate") || raw.toLowerCase().includes("already")) {
        errorMessage = "This source URL is already being watched";
      } else {
        errorMessage = raw || "Failed to add source";
      }
    } finally {
      loading = false;
    }
  }
</script>

<div class="watch-source-card">
  <h2 class="card-title">Watch Source</h2>

  {#if successMessage}
    <div class="toast toast--success" role="status" aria-live="polite">
      {successMessage}
    </div>
  {/if}

  {#if errorMessage}
    <div class="error-message" role="alert">
      {errorMessage}
    </div>
  {/if}

  <form onsubmit={handleSubmit} novalidate>
    <div class="form-group">
      <label for="watch-url" class="form-label">URL</label>
      <input
        id="watch-url"
        type="url"
        class="form-input"
        placeholder="https://example.com/feed.xml"
        bind:value={url}
        aria-label="Feed URL"
        autocomplete="off"
      />
    </div>

    <div class="form-group">
      <label for="watch-source-type" class="form-label">Source Type</label>
      <select
        id="watch-source-type"
        class="form-select"
        bind:value={sourceType}
        aria-label="Source type"
      >
        <option value="rss">RSS</option>
        <option value="github">GitHub</option>
      </select>
    </div>

    <div class="form-group">
      <label for="watch-label" class="form-label">Label</label>
      <input
        id="watch-label"
        type="text"
        class="form-input"
        placeholder="My feed source"
        bind:value={label}
        aria-label="Source label"
      />
    </div>

    <div class="form-group">
      <label for="watch-trust-weight" class="form-label">
        Trust Weight: <span class="trust-weight-value" aria-live="polite">{trustWeightDisplay}</span>
      </label>
      <input
        id="watch-trust-weight"
        type="range"
        class="form-range"
        min="0"
        max="1"
        step="0.1"
        value={trustWeight}
        oninput={handleSliderInput}
        aria-label="Trust weight"
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={trustWeight}
        aria-valuetext={trustWeightDisplay}
      />
    </div>

    <div class="form-group">
      <label class="checkbox-label">
        <input
          type="checkbox"
          bind:checked={importHistory}
          aria-label="Import full history"
        />
        Import full history
      </label>
      <p class="info-note">Full history items land in Inbox for triage. Uses bulk insert.</p>
    </div>

    <button
      type="submit"
      class="btn-primary"
      disabled={!canSubmit}
      aria-busy={loading}
    >
      {#if loading}
        <span class="btn-spinner" aria-hidden="true"></span>
        Adding…
      {:else}
        Add Source
      {/if}
    </button>
  </form>
</div>

<style>
  .watch-source-card {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .card-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin: 0 0 0.5rem 0;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .form-label {
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--fg-muted, #a6adc8);
  }

  .form-input,
  .form-select {
    background: var(--input-bg, #1e1e2e);
    border: 1px solid var(--border, #313244);
    border-radius: 4px;
    color: var(--fg, #cdd6f4);
    font-size: 0.875rem;
    padding: 0.4rem 0.6rem;
    width: 100%;
    box-sizing: border-box;
  }

  .form-input:focus,
  .form-select:focus {
    outline: 2px solid var(--accent, #89b4fa);
    outline-offset: 1px;
  }

  .form-range {
    width: 100%;
    accent-color: var(--accent, #89b4fa);
  }

  .trust-weight-value {
    color: var(--fg, #cdd6f4);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .checkbox-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.875rem;
    color: var(--fg, #cdd6f4);
    cursor: pointer;
  }

  .info-note {
    font-size: 0.75rem;
    color: var(--fg-muted, #a6adc8);
    margin: 0.2rem 0 0 0;
    font-style: italic;
  }

  .btn-primary {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    background: var(--accent, #89b4fa);
    color: var(--base, #1e1e2e);
    border: none;
    border-radius: 4px;
    padding: 0.5rem 1rem;
    font-size: 0.875rem;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
    width: 100%;
  }

  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-primary:not(:disabled):hover {
    opacity: 0.85;
  }

  .btn-spinner {
    display: inline-block;
    width: 0.8rem;
    height: 0.8rem;
    border: 2px solid transparent;
    border-top-color: currentColor;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }

  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }

  .toast {
    border-radius: 4px;
    font-size: 0.875rem;
    padding: 0.5rem 0.75rem;
  }

  .toast--success {
    background: color-mix(in srgb, var(--green, #a6e3a1) 15%, transparent);
    border: 1px solid var(--green, #a6e3a1);
    color: var(--green, #a6e3a1);
  }

  .error-message {
    border-radius: 4px;
    font-size: 0.875rem;
    padding: 0.5rem 0.75rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    border: 1px solid var(--error, #f38ba8);
    color: var(--error, #f38ba8);
  }
</style>
