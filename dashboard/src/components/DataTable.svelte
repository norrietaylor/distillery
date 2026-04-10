<script lang="ts" generics="T extends Record<string, unknown>">
  import type { Snippet } from "svelte";
  import Pagination from "./Pagination.svelte";

  /** Column definition for a DataTable. */
  export interface Column<R extends Record<string, unknown>> {
    /** Field key in the row object. */
    key: string;
    /** Display label for the column header. */
    label: string;
    /** Whether this column is sortable. Default false. */
    sortable?: boolean;
    /** Optional custom cell renderer. Returns an HTML string or plain text. */
    renderText?: (row: R) => string;
    /** Optional snippet-based cell renderer. Receives the row object. */
    renderSnippet?: Snippet<[R]>;
  }

  interface Props {
    /** Column definitions. */
    columns: Column<T>[];
    /** Row data (all rows, pre-filtered from caller if needed). */
    rows: T[];
    /** Default sort column key. */
    defaultSortKey?: string;
    /** Default sort direction. */
    defaultSortDir?: "asc" | "desc";
    /** Number of rows per page. Default 20. */
    pageSize?: number;
    /** Unique key field name in each row. Default "id". */
    rowKey?: string;
    /** Callback when a row is clicked. */
    onRowClick?: (row: T) => void;
    /** Optional slot-like render via snippet — id of currently expanded row. */
    expandedRowId?: string | null;
  }

  let {
    columns,
    rows,
    defaultSortKey,
    defaultSortDir = "desc",
    pageSize = 20,
    rowKey = "id",
    onRowClick,
    expandedRowId = null,
  }: Props = $props();

  let sortKey = $state<string | null>(defaultSortKey ?? null);
  let sortDir = $state<"asc" | "desc">(defaultSortDir);
  let currentPage = $state(1);

  $effect(() => {
    rows;
    currentPage = 1;
  });

  function toggleSort(key: string) {
    if (sortKey === key) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortKey = key;
      sortDir = "desc";
    }
    currentPage = 1;
  }

  function compareValues(a: unknown, b: unknown): number {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a).localeCompare(String(b));
  }

  let sorted = $derived.by((): T[] => {
    if (!sortKey) return [...rows];
    const key = sortKey;
    const dir = sortDir;
    return [...rows].sort((a, b) => {
      const cmp = compareValues(a[key], b[key]);
      return dir === "asc" ? cmp : -cmp;
    });
  });

  let totalItems = $derived(rows.length);

  let paginated = $derived.by((): T[] => {
    const s = sorted;
    const start = (currentPage - 1) * pageSize;
    return s.slice(start, start + pageSize);
  });

  function handlePageChange(page: number) {
    currentPage = page;
  }

  function sortArrow(key: string): string {
    if (sortKey !== key) return "";
    return sortDir === "asc" ? " ▲" : " ▼";
  }

  function getRowId(row: T): string {
    return String(row[rowKey] ?? "");
  }
</script>

<div class="datatable-wrapper">
  <div class="datatable-scroll">
    <table class="datatable" role="grid">
      <thead>
        <tr role="row">
          {#each columns as col (col.key)}
            <th
              class="datatable-th"
              class:sortable={col.sortable}
              class:sorted={sortKey === col.key}
              onclick={() => col.sortable && toggleSort(col.key)}
              aria-sort={sortKey === col.key ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
              tabindex={col.sortable ? 0 : undefined}
              onkeydown={(e) => {
                if (col.sortable && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  toggleSort(col.key);
                }
              }}
            >
              {col.label}{sortArrow(col.key)}
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each paginated as row (getRowId(row))}
          {@const rowId = getRowId(row)}
          {@const isExpanded = expandedRowId === rowId}
          <tr
            role="row"
            class="datatable-row"
            class:expanded={isExpanded}
            class:clickable={!!onRowClick}
            onclick={() => onRowClick?.(row)}
            tabindex={onRowClick ? 0 : undefined}
            onkeydown={(e) => {
              if (onRowClick && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                onRowClick(row);
              }
            }}
            aria-expanded={onRowClick ? isExpanded : undefined}
          >
            {#each columns as col (col.key)}
              <td class="datatable-td">
                {#if col.renderSnippet}
                  {@render col.renderSnippet(row)}
                {:else if col.renderText}
                  {col.renderText(row)}
                {:else}
                  {row[col.key] ?? ""}
                {/if}
              </td>
            {/each}
          </tr>
        {/each}
        {#if paginated.length === 0}
          <tr>
            <td colspan={columns.length} class="datatable-empty">
              No entries found.
            </td>
          </tr>
        {/if}
      </tbody>
    </table>
  </div>

  {#if totalItems > pageSize}
    <Pagination
      {totalItems}
      {pageSize}
      {currentPage}
      onPageChange={handlePageChange}
    />
  {/if}
</div>

<style>
  .datatable-wrapper {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .datatable-scroll {
    overflow-x: auto;
  }

  .datatable {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
  }

  .datatable-th {
    text-align: left;
    padding: 0.6rem 0.75rem;
    border-bottom: 2px solid var(--border, #313244);
    font-weight: 600;
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    white-space: nowrap;
    user-select: none;
  }

  .datatable-th.sortable {
    cursor: pointer;
  }

  .datatable-th.sortable:hover {
    color: var(--fg, #cdd6f4);
  }

  .datatable-th.sorted {
    color: var(--accent, #89b4fa);
  }

  .datatable-row {
    border-bottom: 1px solid var(--border, #313244);
    transition: background 0.1s;
  }

  .datatable-row.clickable {
    cursor: pointer;
  }

  .datatable-row.clickable:hover {
    background: var(--row-hover, #313244);
  }

  .datatable-row.expanded {
    background: color-mix(in srgb, var(--accent, #89b4fa) 8%, transparent);
  }

  .datatable-td {
    padding: 0.55rem 0.75rem;
    vertical-align: middle;
    color: var(--fg, #cdd6f4);
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .datatable-empty {
    padding: 1.5rem 0.75rem;
    text-align: center;
    color: var(--fg-muted, #a6adc8);
    font-style: italic;
  }
</style>
