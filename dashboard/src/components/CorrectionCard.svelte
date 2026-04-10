<script lang="ts">
  export interface CorrectionEntry {
    /** ID of the correcting session entry. */
    id: string;
    /** Brief summary derived from content (first 80 chars). */
    summary: string;
    /** Full content of the correcting entry. */
    content: string;
    /** ID of the original entry being corrected. */
    originalId: string;
    /** Content of the original entry being corrected. */
    originalContent: string;
    /** ISO timestamp of the correcting entry. */
    createdAt: string;
  }

  interface Props {
    correction: CorrectionEntry;
  }

  let { correction }: Props = $props();

  let expanded = $state(false);

  function toggle() {
    expanded = !expanded;
  }

  function formatDate(isoString: string): string {
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return isoString;
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }
</script>

<div
  class="correction-card"
  class:correction-card--expanded={expanded}
  role="button"
  tabindex="0"
  aria-expanded={expanded}
  onclick={toggle}
  onkeydown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}
>
  <div class="correction-card__header">
    <span class="correction-card__icon" aria-hidden="true"
      >{expanded ? "▾" : "▸"}</span
    >
    <span class="correction-card__summary">{correction.summary}</span>
    <span class="correction-card__date">{formatDate(correction.createdAt)}</span>
  </div>

  {#if expanded}
    <div class="correction-card__body" role="region" aria-label="Correction detail">
      <div class="correction-card__columns">
        <div class="correction-card__panel correction-card__panel--original">
          <h4 class="correction-card__panel-title">Original</h4>
          <pre class="correction-card__content">{correction.originalContent}</pre>
        </div>
        <div class="correction-card__panel correction-card__panel--corrected">
          <h4 class="correction-card__panel-title">Corrected</h4>
          <pre class="correction-card__content">{correction.content}</pre>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .correction-card {
    border: 1px solid var(--border, #313244);
    border-radius: 6px;
    background: var(--card-bg, #181825);
    cursor: pointer;
    transition: border-color 0.15s;
    outline: none;
  }

  .correction-card:hover,
  .correction-card:focus-visible {
    border-color: var(--accent, #89b4fa);
  }

  .correction-card--expanded {
    border-color: var(--accent, #89b4fa);
  }

  .correction-card__header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
  }

  .correction-card__icon {
    font-size: 0.75rem;
    color: var(--fg-muted, #a6adc8);
    flex-shrink: 0;
  }

  .correction-card__summary {
    flex: 1;
    font-size: 0.875rem;
    color: var(--fg, #cdd6f4);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .correction-card__date {
    font-size: 0.75rem;
    color: var(--fg-muted, #a6adc8);
    flex-shrink: 0;
  }

  .correction-card__body {
    padding: 0 1rem 1rem;
    border-top: 1px solid var(--border, #313244);
  }

  .correction-card__columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    padding-top: 0.75rem;
  }

  .correction-card__panel {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .correction-card__panel-title {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--fg-muted, #a6adc8);
    margin: 0;
  }

  .correction-card__panel--original .correction-card__panel-title {
    color: var(--error, #f38ba8);
  }

  .correction-card__panel--corrected .correction-card__panel-title {
    color: var(--green, #a6e3a1);
  }

  .correction-card__content {
    font-size: 0.8rem;
    line-height: 1.5;
    color: var(--fg, #cdd6f4);
    background: var(--code-bg, #1e1e2e);
    border: 1px solid var(--border, #313244);
    border-radius: 4px;
    padding: 0.5rem 0.75rem;
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    overflow: auto;
    max-height: 200px;
    font-family: ui-monospace, "Cascadia Code", "Source Code Pro", monospace;
  }
</style>
