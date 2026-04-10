<script lang="ts">
  /**
   * PieChart — a simple SVG pie chart for displaying entries by type.
   *
   * Uses raw SVG arcs, following the Layercake SVG-first philosophy.
   * Color-consistent with the type/status color mapping used across charts.
   */

  interface Slice {
    label: string;
    value: number;
    color: string;
  }

  interface Props {
    /** Data slices to render. */
    data: Slice[];
    /** Width of the SVG canvas. */
    width?: number;
    /** Height of the SVG canvas. */
    height?: number;
    /** Inner radius as fraction of outer radius (0 = solid pie, >0 = donut). */
    innerRadiusFraction?: number;
    /** Accessible label for the chart. */
    ariaLabel?: string;
  }

  let {
    data,
    width = 220,
    height = 220,
    innerRadiusFraction = 0,
    ariaLabel = "Pie chart",
  }: Props = $props();

  const cx = $derived(width / 2);
  const cy = $derived(height / 2);
  const r = $derived(Math.min(width, height) / 2 - 4);
  const innerR = $derived(r * innerRadiusFraction);

  /** Compute cumulative pie slices. */
  const slices = $derived(() => {
    const total = data.reduce((sum, d) => sum + d.value, 0);
    if (total === 0) return [];

    let startAngle = -Math.PI / 2; // start at 12 o'clock
    return data.map((d) => {
      const sweep = (d.value / total) * 2 * Math.PI;
      const endAngle = startAngle + sweep;
      const result = { ...d, startAngle, endAngle, sweep };
      startAngle = endAngle;
      return result;
    });
  });

  /** Convert polar coordinates to SVG x,y. */
  function polar(angle: number, radius: number, centerX: number, centerY: number) {
    return {
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
    };
  }

  /** Build an SVG arc path for a single slice. */
  function arcPath(
    startAngle: number,
    endAngle: number,
    outerRadius: number,
    innerRadius: number,
    centerX: number,
    centerY: number,
  ): string {
    const sweep = endAngle - startAngle;
    const largeArc = sweep > Math.PI ? 1 : 0;

    const outerStart = polar(startAngle, outerRadius, centerX, centerY);
    const outerEnd = polar(endAngle, outerRadius, centerX, centerY);

    if (innerRadius <= 0) {
      // Solid pie
      return [
        `M ${centerX} ${centerY}`,
        `L ${outerStart.x} ${outerStart.y}`,
        `A ${outerRadius} ${outerRadius} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
        "Z",
      ].join(" ");
    }

    // Donut
    const innerStart = polar(startAngle, innerRadius, centerX, centerY);
    const innerEnd = polar(endAngle, innerRadius, centerX, centerY);

    return [
      `M ${outerStart.x} ${outerStart.y}`,
      `A ${outerRadius} ${outerRadius} 0 ${largeArc} 1 ${outerEnd.x} ${outerEnd.y}`,
      `L ${innerEnd.x} ${innerEnd.y}`,
      `A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${innerStart.x} ${innerStart.y}`,
      "Z",
    ].join(" ");
  }
</script>

<div class="pie-chart" role="figure" aria-label={ariaLabel}>
  {#if data.length === 0 || data.every((d) => d.value === 0)}
    <div class="empty-state" aria-label="No data">
      <svg {width} {height} aria-hidden="true">
        <circle cx={cx} cy={cy} r={r} fill="var(--border, #313244)" />
        {#if innerRadiusFraction > 0}
          <circle cx={cx} cy={cy} r={innerR} fill="var(--card-bg, #181825)" />
        {/if}
      </svg>
      <p class="empty-label">No data</p>
    </div>
  {:else}
    <svg {width} {height} aria-hidden="true">
      {#each slices() as slice (slice.label)}
        <path
          d={arcPath(slice.startAngle, slice.endAngle, r, innerR, cx, cy)}
          fill={slice.color}
          stroke="var(--card-bg, #181825)"
          stroke-width="1"
          role="presentation"
          aria-label="{slice.label}: {slice.value}"
        />
      {/each}
    </svg>
    <ul class="legend" aria-label="Legend">
      {#each data as item (item.label)}
        {#if item.value > 0}
          <li class="legend-item">
            <span class="legend-swatch" style="background: {item.color};" aria-hidden="true"></span>
            <span class="legend-label">{item.label}</span>
            <span class="legend-value">{item.value}</span>
          </li>
        {/if}
      {/each}
    </ul>
  {/if}
</div>

<style>
  .pie-chart {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
  }

  .empty-label {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    margin: 0;
  }

  .legend {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    width: 100%;
    max-width: 220px;
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8rem;
  }

  .legend-swatch {
    width: 10px;
    height: 10px;
    border-radius: 2px;
    flex-shrink: 0;
  }

  .legend-label {
    flex: 1;
    color: var(--fg-muted, #a6adc8);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .legend-value {
    font-variant-numeric: tabular-nums;
    color: var(--fg, #cdd6f4);
    font-weight: 500;
  }
</style>
