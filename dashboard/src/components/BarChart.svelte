<script lang="ts">
  /**
   * BarChart — a simple horizontal SVG bar chart for displaying entries by status.
   *
   * Uses raw SVG rectangles, following the Layercake SVG-first philosophy.
   * Color-consistent with the type/status color mapping used across charts.
   */

  interface Bar {
    label: string;
    value: number;
    color: string;
  }

  interface Props {
    /** Data bars to render. */
    data: Bar[];
    /** Width of the SVG canvas. */
    width?: number;
    /** Height of the SVG canvas. */
    height?: number;
    /** Accessible label for the chart. */
    ariaLabel?: string;
  }

  let {
    data,
    width = 360,
    height = 180,
    ariaLabel = "Bar chart",
  }: Props = $props();

  const BAR_HEIGHT = 24;
  const BAR_GAP = 10;
  const LABEL_WIDTH = 110;
  const VALUE_WIDTH = 36;
  const PADDING_TOP = 8;
  const PADDING_BOTTOM = 8;

  const maxValue = $derived(Math.max(...data.map((d) => d.value), 1));
  const barAreaWidth = $derived(Math.max(width - LABEL_WIDTH - VALUE_WIDTH - 8, 1));
  const computedHeight = $derived(
    data.length > 0
      ? PADDING_TOP + data.length * (BAR_HEIGHT + BAR_GAP) - BAR_GAP + PADDING_BOTTOM
      : height,
  );

  const bars = $derived(
    data.map((d, i) => ({
      ...d,
      y: PADDING_TOP + i * (BAR_HEIGHT + BAR_GAP),
      barWidth: (d.value / maxValue) * barAreaWidth,
    })),
  );
</script>

<div class="bar-chart" role="figure" aria-label={ariaLabel}>
  {#if data.length === 0 || data.every((d) => d.value === 0)}
    <div class="empty-state" aria-label="No data">
      <p class="empty-label">No data</p>
    </div>
  {:else}
    <svg width={width} height={computedHeight} aria-hidden="true">
      {#each bars as bar (bar.label)}
        <!-- Label -->
        <text
          x={0}
          y={bar.y + BAR_HEIGHT / 2 + 5}
          font-size="12"
          fill="var(--fg-muted, #a6adc8)"
          text-anchor="start"
          dominant-baseline="auto"
          role="presentation"
        >
          {bar.label}
        </text>
        <!-- Bar -->
        <rect
          x={LABEL_WIDTH}
          y={bar.y}
          width={Math.max(bar.barWidth, bar.value > 0 ? 2 : 0)}
          height={BAR_HEIGHT}
          fill={bar.color}
          rx="3"
          role="presentation"
          aria-label="{bar.label}: {bar.value}"
        />
        <!-- Value -->
        <text
          x={LABEL_WIDTH + barAreaWidth + 6}
          y={bar.y + BAR_HEIGHT / 2 + 5}
          font-size="12"
          fill="var(--fg, #cdd6f4)"
          text-anchor="start"
          dominant-baseline="auto"
          font-weight="500"
          role="presentation"
        >
          {bar.value}
        </text>
      {/each}
    </svg>
  {/if}
</div>

<style>
  .bar-chart {
    width: 100%;
  }

  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 80px;
  }

  .empty-label {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    margin: 0;
  }
</style>
