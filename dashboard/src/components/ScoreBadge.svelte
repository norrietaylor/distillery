<script lang="ts">
  interface Props {
    /** Relevance score between 0 and 1. */
    score: number;
    /** ARIA label override. */
    label?: string;
  }

  let { score, label }: Props = $props();

  /** Determine color tier from score value. */
  function tier(s: number): "green" | "yellow" | "gray" {
    if (s > 0.8) return "green";
    if (s > 0.5) return "yellow";
    return "gray";
  }

  let colorTier = $derived(tier(score));
  let displayLabel = $derived(label ?? `Score: ${score.toFixed(2)}`);
</script>

<span
  class="score-badge score-badge--{colorTier}"
  aria-label={displayLabel}
  title={displayLabel}
>
  {score.toFixed(2)}
</span>

<style>
  .score-badge {
    display: inline-block;
    padding: 0.2rem 0.5rem;
    border-radius: 10px;
    font-size: 0.75rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .score-badge--green {
    background: color-mix(in srgb, #a6e3a1 20%, transparent);
    color: #a6e3a1;
    border: 1px solid color-mix(in srgb, #a6e3a1 40%, transparent);
  }

  .score-badge--yellow {
    background: color-mix(in srgb, #f9e2af 20%, transparent);
    color: #f9e2af;
    border: 1px solid color-mix(in srgb, #f9e2af 40%, transparent);
  }

  .score-badge--gray {
    background: color-mix(in srgb, #a6adc8 20%, transparent);
    color: #a6adc8;
    border: 1px solid color-mix(in srgb, #a6adc8 40%, transparent);
  }
</style>
