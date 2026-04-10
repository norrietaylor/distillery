<script lang="ts">
  interface Props {
    /** Total number of items across all pages. */
    totalItems: number;
    /** Number of items per page. Default 20. */
    pageSize?: number;
    /** Current page (1-based). */
    currentPage: number;
    /** Callback when the page changes. */
    onPageChange: (page: number) => void;
  }

  let {
    totalItems,
    pageSize = 20,
    currentPage,
    onPageChange,
  }: Props = $props();

  let totalPages = $derived(Math.max(1, Math.ceil(totalItems / pageSize)));
  let safePage = $derived(Math.min(Math.max(currentPage, 1), totalPages || 1));
  let hasPrev = $derived(safePage > 1);
  let hasNext = $derived(safePage < totalPages);

  /** Range label e.g. "21–40 of 45" */
  let rangeLabel = $derived.by(() => {
    const start = (safePage - 1) * pageSize + 1;
    const end = Math.min(safePage * pageSize, totalItems);
    if (totalItems === 0) return "0 results";
    return `${start}–${end} of ${totalItems}`;
  });
</script>

<div class="pagination" role="navigation" aria-label="Pagination">
  <span class="pagination-range">{rangeLabel}</span>

  <div class="pagination-controls">
    <button
      class="pagination-btn"
      onclick={() => onPageChange(currentPage - 1)}
      disabled={!hasPrev}
      aria-label="Previous page"
    >
      &lsaquo; Prev
    </button>

    <span class="pagination-page" aria-current="page">
      {currentPage} / {totalPages}
    </span>

    <button
      class="pagination-btn"
      onclick={() => onPageChange(currentPage + 1)}
      disabled={!hasNext}
      aria-label="Next page"
    >
      Next &rsaquo;
    </button>
  </div>
</div>

<style>
  .pagination {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0;
    gap: 1rem;
  }

  .pagination-range {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
  }

  .pagination-controls {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .pagination-page {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    min-width: 4rem;
    text-align: center;
  }

  .pagination-btn {
    padding: 0.3rem 0.65rem;
    font-size: 0.8rem;
    font-weight: 500;
    background: var(--btn-bg, #313244);
    color: var(--btn-fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
  }

  .pagination-btn:hover:not(:disabled) {
    background: var(--btn-hover, #45475a);
  }

  .pagination-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
