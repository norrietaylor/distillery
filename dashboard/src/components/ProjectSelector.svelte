<script lang="ts">
  import { selectedProject, refreshTick } from "$lib/stores";
  import type { McpBridge } from "$lib/mcp-bridge";

  interface Props {
    bridge?: McpBridge | null;
  }

  let { bridge = null }: Props = $props();

  let projects = $state<string[]>([]);
  let loadError = $state<string | null>(null);
  let loadingProjects = $state(false);

  async function loadProjects() {
    if (!bridge?.isConnected) return;
    loadingProjects = true;
    loadError = null;
    try {
      const result = await bridge.callTool("distillery_list", {
        output: "stats",
        group_by: "project",
      });
      if (result.isError) {
        loadError = "Failed to load projects";
        return;
      }
      // Parse the text response: each line may be "project_name: N entries"
      // Accept any non-empty token before the colon as a project name.
      const lines = result.text.split("\n");
      const parsed: string[] = [];
      for (const line of lines) {
        const match = line.match(/^([^:]+):\s*\d+/);
        if (match && match[1]) {
          const name = match[1].trim();
          if (name && name !== "null" && name !== "undefined") {
            parsed.push(name);
          }
        }
      }
      projects = parsed;
    } catch (err) {
      loadError = err instanceof Error ? err.message : "Failed to load projects";
    } finally {
      loadingProjects = false;
    }
  }

  // Re-load project list on each refresh tick when bridge is available
  $effect(() => {
    // Depend on refresh tick so we reload on manual/auto refresh
    const _tick = $refreshTick;
    void loadProjects();
  });

  function handleChange(event: Event) {
    const select = event.target as HTMLSelectElement;
    selectedProject.set(select.value === "" ? null : select.value);
  }
</script>

<div class="project-selector">
  <label for="project-select" class="project-label">Project</label>
  <select
    id="project-select"
    class="project-select"
    value={$selectedProject ?? ""}
    onchange={handleChange}
    disabled={loadingProjects}
    aria-label="Select project"
  >
    <option value="">All projects</option>
    {#each projects as project (project)}
      <option value={project}>{project}</option>
    {/each}
  </select>
  {#if loadError}
    <span class="project-error" role="alert">{loadError}</span>
  {/if}
</div>

<style>
  .project-selector {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .project-label {
    font-size: 0.8rem;
    font-weight: 500;
    color: var(--nav-fg-muted, #a6adc8);
    white-space: nowrap;
  }

  .project-select {
    padding: 0.3rem 0.6rem;
    font-size: 0.8rem;
    background: var(--select-bg, #313244);
    color: var(--nav-fg, #cdd6f4);
    border: 1px solid var(--border, #45475a);
    border-radius: 4px;
    cursor: pointer;
    min-width: 140px;
  }

  .project-select:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .project-error {
    font-size: 0.75rem;
    color: var(--error, #f38ba8);
  }
</style>
