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
      // distillery_list with group_by returns
      //   {"groups": [{"value": "project-a", "count": 12}, ...],
      //    "total_groups": N, "total_entries": N}
      // We intentionally do NOT pass output="stats" — the server rejects
      // the combination with INVALID_PARAMS because output="stats" and
      // group_by are mutually exclusive (see
      // src/distillery/mcp/tools/crud.py::_handle_list). Earlier this
      // component sent both and silently swallowed the server's rejection
      // under an empty project dropdown.
      const result = await bridge.callTool("distillery_list", {
        group_by: "project",
      });
      if (result.isError) {
        loadError = "Failed to load projects";
        return;
      }
      // Parse the JSON payload: extract each group's value as a project
      // name, skip null/empty. An earlier version of this component
      // text-parsed "project_name: N entries" lines, which never matched
      // the real JSON response at all — the dropdown was effectively a
      // no-op regardless of whether the server call succeeded.
      const parsed: string[] = [];
      try {
        const data = JSON.parse(result.text) as {
          groups?: Array<{ value?: unknown; count?: unknown }>;
        };
        if (Array.isArray(data.groups)) {
          for (const g of data.groups) {
            if (g.value == null) continue;
            const name = String(g.value).trim();
            if (name && name !== "null" && name !== "undefined") {
              parsed.push(name);
            }
          }
        }
      } catch {
        // Non-JSON response — leave the project list empty so the
        // dropdown degrades to "All projects" only instead of showing
        // garbage.
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
