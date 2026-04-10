<script lang="ts">
  /**
   * MetricCard — a single stat tile in the briefing stats row.
   *
   * Displays a large numeric value with a label and optional color coding.
   * Color coding prop controls the visual severity indicator.
   */

  interface Props {
    /** Display label for this metric. */
    label: string;
    /** Numeric value to display. null while loading. */
    value: number | null;
    /** Color coding variant. 'default' renders normally; 'warning' renders yellow; 'danger' renders red. */
    variant?: "default" | "warning" | "danger";
    /** Whether the card is in a loading state. */
    loading?: boolean;
    /** Inline error message. null if no error. */
    error?: string | null;
  }

  let {
    label,
    value,
    variant = "default",
    loading = false,
    error = null,
  }: Props = $props();
</script>

<div class="metric-card metric-card--{variant}" aria-label="{label}: {value ?? 'loading'}">
  <div class="metric-label">{label}</div>

  {#if loading}
    <div class="metric-value metric-value--loading" aria-busy="true" aria-live="polite">
      <span class="skeleton-number"></span>
    </div>
  {:else if error}
    <div class="metric-value metric-value--error" role="alert" title={error}>
      &mdash;
    </div>
  {:else}
    <div class="metric-value" aria-live="polite">
      {value ?? 0}
    </div>
  {/if}
</div>

<style>
  .metric-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 1rem 1.25rem;
    background: var(--card-bg, #181825);
    border: 1px solid var(--border, #313244);
    border-radius: 8px;
    min-width: 120px;
    flex: 1;
    gap: 0.4rem;
    text-align: center;
  }

  .metric-label {
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--fg-muted, #a6adc8);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    white-space: nowrap;
  }

  .metric-value {
    font-size: 2rem;
    font-weight: 700;
    color: var(--fg, #cdd6f4);
    line-height: 1;
    font-variant-numeric: tabular-nums;
  }

  .metric-value--loading {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .metric-value--error {
    color: var(--fg-muted, #a6adc8);
    font-size: 1.5rem;
  }

  /* Color coding variants */
  .metric-card--warning .metric-value {
    color: var(--warning, #f9e2af);
  }

  .metric-card--warning {
    border-color: color-mix(in srgb, var(--warning, #f9e2af) 40%, transparent);
  }

  .metric-card--danger .metric-value {
    color: var(--error, #f38ba8);
  }

  .metric-card--danger {
    border-color: color-mix(in srgb, var(--error, #f38ba8) 40%, transparent);
  }

  /* Loading skeleton for the number */
  .skeleton-number {
    display: inline-block;
    width: 3rem;
    height: 2rem;
    background: var(--skeleton-bg, #313244);
    border-radius: 4px;
    animation: pulse 1.5s ease-in-out infinite;
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
