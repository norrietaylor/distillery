<script lang="ts">
  import { selectedProject, currentUser } from "$lib/stores";
  import type { McpBridge } from "$lib/mcp-bridge";

  interface Props {
    /** The MCP bridge instance for tool calls. */
    bridge?: McpBridge | null;
  }

  let { bridge = null }: Props = $props();

  /** Bookmark form state machine. */
  type FormPhase = "idle" | "checking" | "reviewed" | "saving" | "saved";

  /** Dedup action recommended by find_similar. */
  type DedupAction = "create" | "skip" | "merge" | "link";

  /** A single dedup result from find_similar. */
  interface DedupResult {
    id: string;
    content: string;
    similarity: number;
    action: DedupAction;
  }

  let url = $state("");
  let tagsInput = $state("");
  let phase = $state<FormPhase>("idle");
  let dedupResults = $state<DedupResult[]>([]);
  let dedupChecked = $state(false);
  let saveError = $state<string | null>(null);
  let successMessage = $state<string | null>(null);
  let successEntryId = $state<string | null>(null);

  /** Parse tags from the input string, stripping # prefixes and splitting on spaces. */
  function parseTags(input: string): string[] {
    return input
      .split(/\s+/)
      .map((t) => t.replace(/^#/, ""))
      .filter((t) => t.length > 0);
  }

  /** Validate URL starts with http:// or https://. */
  function isValidUrl(value: string): boolean {
    return /^https?:\/\/.+/.test(value.trim());
  }

  let urlValid = $derived(isValidUrl(url));
  let parsedTags = $derived(parseTags(tagsInput));

  /** The top dedup result (highest similarity). */
  let topResult = $derived<DedupResult | null>(
    dedupResults.length > 0 ? dedupResults[0] ?? null : null,
  );

  /** Check for duplicates via find_similar. */
  async function checkDuplicates() {
    if (!bridge?.isConnected || !urlValid) return;
    phase = "checking";
    dedupResults = [];
    saveError = null;
    successMessage = null;
    try {
      const result = await bridge.callTool("find_similar", {
        content: url.trim(),
        threshold: 0.8,
        dedup_action: true,
      });
      if (result.isError) {
        saveError = result.text || "Failed to check for duplicates";
        phase = "idle";
        return;
      }
      const parsed = parseDedupResults(result.text);
      dedupResults = parsed;
      dedupChecked = true;
      phase = "reviewed";
    } catch (err) {
      saveError = err instanceof Error ? err.message : "Failed to check for duplicates";
      phase = "idle";
    }
  }

  /** Parse find_similar response into DedupResult[]. */
  function parseDedupResults(text: string): DedupResult[] {
    if (!text.trim()) return [];
    try {
      const parsed: unknown = JSON.parse(text);
      if (Array.isArray(parsed)) {
        return parsed.map(normalizeDedupResult);
      }
      if (parsed && typeof parsed === "object") {
        return [normalizeDedupResult(parsed as Record<string, unknown>)];
      }
    } catch {
      // fall through
    }
    return [];
  }

  function normalizeDedupResult(obj: Record<string, unknown>): DedupResult {
    const similarity = typeof obj["similarity"] === "number" ? obj["similarity"] : 0;
    let action: DedupAction = "create";
    if (typeof obj["action"] === "string") {
      const a = obj["action"] as string;
      if (a === "skip" || a === "merge" || a === "link" || a === "create") {
        action = a;
      }
    } else {
      // Derive action from similarity if not provided
      if (similarity >= 0.95) action = "skip";
      else if (similarity >= 0.85) action = "merge";
      else if (similarity >= 0.70) action = "link";
    }
    return {
      id: String(obj["id"] ?? ""),
      content: String(obj["content"] ?? ""),
      similarity,
      action,
    };
  }

  /** Save the bookmark via store tool. */
  async function saveBookmark() {
    if (!bridge?.isConnected || !urlValid) return;
    phase = "saving";
    saveError = null;
    try {
      const args: Record<string, unknown> = {
        content: url.trim(),
        entry_type: "bookmark",
        author: $currentUser?.login ?? "user",
        source: "claude-code",
      };
      if ($selectedProject) args["project"] = $selectedProject;
      if (parsedTags.length > 0) args["tags"] = parsedTags;

      const result = await bridge.callTool("store", args);
      if (result.isError) {
        saveError = result.text || "Failed to save bookmark";
        phase = dedupChecked ? "reviewed" : "idle";
        return;
      }
      // Extract entry ID from result
      const idMatch = result.text.match(/(?:id[:\s]+)?([0-9a-f-]{36})/i);
      const entryId = idMatch ? idMatch[1] : result.text.trim();
      successEntryId = entryId ?? null;
      successMessage = `Bookmark saved: ${entryId ?? "success"}`;
      phase = "saved";
      // Clear form after a brief delay to show success
      setTimeout(clearForm, 200);
    } catch (err) {
      saveError = err instanceof Error ? err.message : "Failed to save bookmark";
      phase = dedupChecked ? "reviewed" : "idle";
    }
  }

  /** Clear form fields and reset state. */
  function clearForm() {
    url = "";
    tagsInput = "";
    phase = "idle";
    dedupResults = [];
    dedupChecked = false;
    saveError = null;
    // Keep successMessage visible for toast auto-dismiss
  }

  /** Dismiss the success toast. */
  function dismissToast() {
    successMessage = null;
    successEntryId = null;
  }

  // Auto-dismiss toast after 5 seconds
  $effect(() => {
    if (successMessage) {
      const handle = setTimeout(dismissToast, 5000);
      return () => clearTimeout(handle);
    }
  });

  /** Whether we're in a loading state (checking or saving). */
  let isLoading = $derived(phase === "checking" || phase === "saving");

  /** Buttons disabled when URL is invalid or loading. */
  let checkDisabled = $derived(!urlValid || isLoading);
  let saveDisabled = $derived(!urlValid || isLoading);
</script>

<div class="bookmark-card" data-testid="bookmark-card">
  <h2 class="card-title">Bookmark</h2>

  <!-- URL input -->
  <div class="form-group">
    <label for="bookmark-url" class="form-label">URL</label>
    <input
      id="bookmark-url"
      class="form-input"
      type="url"
      placeholder="https://example.com/article"
      bind:value={url}
      readonly={phase === "checking"}
      aria-label="Bookmark URL"
    />
    {#if url.length > 0 && !urlValid}
      <span class="validation-message" role="alert">
        Enter a valid URL starting with http:// or https://
      </span>
    {/if}
  </div>

  <!-- Tags input -->
  <div class="form-group">
    <label for="bookmark-tags" class="form-label">Tags</label>
    <input
      id="bookmark-tags"
      class="form-input"
      type="text"
      placeholder="#tag1 #tag2"
      bind:value={tagsInput}
      aria-label="Bookmark tags"
    />
  </div>

  <!-- Project selector (read-only, from global filter) -->
  <div class="form-group">
    <label for="bookmark-project" class="form-label">Project</label>
    <input
      id="bookmark-project"
      class="form-input form-input--readonly"
      type="text"
      value={$selectedProject ?? "All projects"}
      readonly
      aria-label="Bookmark project"
    />
  </div>

  <!-- Action buttons -->
  <div class="form-actions">
    <button
      class="btn btn--secondary"
      disabled={checkDisabled}
      onclick={checkDuplicates}
      aria-label="Check for duplicates"
    >
      {#if phase === "checking"}
        <span class="spinner" aria-hidden="true"></span>
        Checking...
      {:else}
        Check for duplicates
      {/if}
    </button>

    {#if !topResult || topResult.action !== "skip"}
      <button
        class="btn btn--primary"
        disabled={saveDisabled}
        onclick={saveBookmark}
        aria-label="Save"
      >
        {#if phase === "saving"}
          <span class="spinner" aria-hidden="true"></span>
          Saving...
        {:else}
          Save
        {/if}
      </button>
    {/if}
  </div>

  <!-- Error message -->
  {#if saveError}
    <div class="error-banner" role="alert">
      {saveError}
    </div>
  {/if}

  <!-- Dedup results -->
  {#if dedupChecked && phase === "reviewed"}
    <div class="dedup-results" data-testid="dedup-results">
      {#if dedupResults.length === 0}
        <!-- No duplicates -->
        <div class="dedup-clear">
          <span class="indicator indicator--green" aria-hidden="true"></span>
          No duplicates found
        </div>
      {:else if topResult}
        {#if topResult.action === "skip"}
          <!-- Skip recommendation -->
          <div class="dedup-warning" role="alert">
            <strong>This entry already exists</strong>
            <p class="dedup-existing">
              <a href="#entry-{topResult.id}" class="entry-link">
                {topResult.content || topResult.id}
              </a>
              <span class="similarity-badge">
                {(topResult.similarity * 100).toFixed(0)}% similar
              </span>
            </p>
            <button
              class="btn btn--secondary btn--small"
              onclick={saveBookmark}
              aria-label="Save anyway"
            >
              Save anyway
            </button>
          </div>
        {:else if topResult.action === "merge"}
          <!-- Merge recommendation -->
          <div class="dedup-info">
            <p class="dedup-existing">
              Similar entry found:
              <span class="similarity-badge">
                {(topResult.similarity * 100).toFixed(0)}% similar
              </span>
            </p>
            <p class="dedup-content">{topResult.content}</p>
            <div class="dedup-actions">
              <button
                class="btn btn--primary btn--small"
                onclick={saveBookmark}
                aria-label="Merge with existing"
              >
                Merge with existing
              </button>
              <button
                class="btn btn--secondary btn--small"
                onclick={saveBookmark}
                aria-label="Save as new"
              >
                Save as new
              </button>
            </div>
          </div>
        {:else if topResult.action === "link"}
          <!-- Link recommendation -->
          <div class="dedup-info">
            <p class="dedup-existing">
              Related entry found:
              <span class="similarity-badge">
                {(topResult.similarity * 100).toFixed(0)}% similar
              </span>
            </p>
            <p class="dedup-content">{topResult.content}</p>
            <div class="dedup-actions">
              <button
                class="btn btn--primary btn--small"
                onclick={saveBookmark}
                aria-label="Save and link"
              >
                Save and link
              </button>
              <button
                class="btn btn--secondary btn--small"
                onclick={saveBookmark}
                aria-label="Save without linking"
              >
                Save without linking
              </button>
            </div>
          </div>
        {/if}
      {/if}
    </div>
  {/if}

  <!-- Success toast -->
  {#if successMessage}
    <div class="toast toast--success" role="status" data-testid="success-toast">
      <span>{successMessage}</span>
      {#if successEntryId}
        <a href="#entry-{successEntryId}" class="toast-link">View entry</a>
      {/if}
      <button class="toast-dismiss" onclick={dismissToast} aria-label="Dismiss">
        &times;
      </button>
    </div>
  {/if}
</div>

<style>
  .bookmark-card {
    background: var(--card-bg, #181825);
    border: 1px solid var(--border, #313244);
    border-radius: 8px;
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .card-title {
    font-size: 1rem;
    font-weight: 600;
    color: var(--fg, #cdd6f4);
    margin-bottom: 0.25rem;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .form-label {
    font-size: 0.75rem;
    font-weight: 500;
    color: var(--fg-muted, #a6adc8);
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .form-input {
    padding: 0.4rem 0.65rem;
    font-size: 0.85rem;
    background: var(--input-bg, #313244);
    color: var(--fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    width: 100%;
  }

  .form-input::placeholder {
    color: var(--fg-muted, #a6adc8);
  }

  .form-input--readonly {
    opacity: 0.7;
    cursor: default;
  }

  .validation-message {
    font-size: 0.75rem;
    color: var(--error, #f38ba8);
  }

  .form-actions {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .btn {
    padding: 0.4rem 0.9rem;
    font-size: 0.8rem;
    font-weight: 500;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }

  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn--primary {
    background: color-mix(in srgb, var(--accent, #89b4fa) 20%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent, #89b4fa) 50%, transparent);
    color: var(--accent, #89b4fa);
  }

  .btn--primary:hover:not(:disabled) {
    background: color-mix(in srgb, var(--accent, #89b4fa) 35%, transparent);
  }

  .btn--secondary {
    background: var(--btn-bg, #313244);
    color: var(--btn-fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
  }

  .btn--secondary:hover:not(:disabled) {
    background: var(--btn-hover, #45475a);
  }

  .btn--small {
    padding: 0.3rem 0.65rem;
    font-size: 0.75rem;
  }

  .spinner {
    display: inline-block;
    width: 0.75rem;
    height: 0.75rem;
    border: 2px solid currentColor;
    border-right-color: transparent;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  .error-banner {
    padding: 0.5rem 0.75rem;
    background: color-mix(in srgb, var(--error, #f38ba8) 15%, transparent);
    border: 1px solid var(--error, #f38ba8);
    border-radius: 6px;
    color: var(--error, #f38ba8);
    font-size: 0.8rem;
  }

  /* Dedup results */
  .dedup-results {
    padding: 0.75rem;
    background: var(--detail-bg, #11111b);
    border-radius: 6px;
    border: 1px solid var(--border, #313244);
  }

  .dedup-clear {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
    color: var(--success, #a6e3a1);
  }

  .indicator {
    display: inline-block;
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
  }

  .indicator--green {
    background: var(--success, #a6e3a1);
  }

  .dedup-warning {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    color: var(--warning, #fab387);
    font-size: 0.85rem;
  }

  .dedup-info {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    font-size: 0.85rem;
    color: var(--fg, #cdd6f4);
  }

  .dedup-existing {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .dedup-content {
    font-size: 0.8rem;
    color: var(--fg-muted, #a6adc8);
    background: var(--code-bg, #181825);
    padding: 0.5rem;
    border-radius: 4px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .dedup-actions {
    display: flex;
    gap: 0.5rem;
  }

  .entry-link {
    color: var(--accent, #89b4fa);
    text-decoration: underline;
    font-size: 0.8rem;
  }

  .similarity-badge {
    font-size: 0.7rem;
    padding: 0.1rem 0.4rem;
    background: color-mix(in srgb, var(--accent, #89b4fa) 15%, transparent);
    border-radius: 10px;
    color: var(--accent, #89b4fa);
    font-weight: 500;
  }

  /* Toast */
  .toast {
    position: relative;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.6rem 0.9rem;
    border-radius: 6px;
    font-size: 0.8rem;
    animation: slideIn 0.2s ease-out;
  }

  .toast--success {
    background: color-mix(in srgb, var(--success, #a6e3a1) 15%, transparent);
    border: 1px solid var(--success, #a6e3a1);
    color: var(--success, #a6e3a1);
  }

  .toast-link {
    color: var(--accent, #89b4fa);
    text-decoration: underline;
    font-size: 0.8rem;
  }

  .toast-dismiss {
    margin-left: auto;
    background: none;
    border: none;
    color: inherit;
    font-size: 1rem;
    cursor: pointer;
    padding: 0 0.25rem;
    line-height: 1;
  }

  @keyframes slideIn {
    from {
      opacity: 0;
      transform: translateY(-0.5rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
</style>
