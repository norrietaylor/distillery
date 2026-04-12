import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import RelationGraph from "./RelationGraph.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

/** Build a MCP relations response payload. */
function makeRelationsResponse(
  entryId: string,
  relations: Array<{ id: string; from_id: string; to_id: string; relation_type: string }>,
): string {
  return JSON.stringify({
    entry_id: entryId,
    direction: "both",
    relation_type: null,
    relations,
    count: relations.length,
  });
}

/** Build a single relation row. */
function makeRelation(
  fromId: string,
  toId: string,
  relType: string,
  id?: string,
): { id: string; from_id: string; to_id: string; relation_type: string } {
  return {
    id: id ?? `rel-${Math.random().toString(36).slice(2)}`,
    from_id: fromId,
    to_id: toId,
    relation_type: relType,
  };
}

function makeMockBridge(
  callToolImpl: (name: string, args?: Record<string, unknown>) => Promise<ToolCallTextResult>,
): McpBridge {
  return {
    isConnected: true,
    callTool: vi.fn().mockImplementation(callToolImpl),
  } as unknown as McpBridge;
}

const onNavigate = vi.fn();
const onPin = vi.fn();

const defaultProps = {
  seedEntryId: "seed-001",
  phase1ResultIds: ["p1-001", "p1-002"],
  onNavigate,
  onPin,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RelationGraph", () => {
  describe("rendering without bridge", () => {
    it("renders without crashing when bridge is null", () => {
      expect(() =>
        render(RelationGraph, { props: { ...defaultProps, bridge: null } }),
      ).not.toThrow();
    });

    it("shows error when bridge is null", async () => {
      render(RelationGraph, { props: { ...defaultProps, bridge: null } });
      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Not connected/)).toBeTruthy();
      });
    });

    it("renders the section with aria-label", () => {
      render(RelationGraph, { props: { ...defaultProps, bridge: null } });
      expect(screen.getByLabelText("Phase 2: Relation Graph")).toBeTruthy();
    });
  });

  describe("loading state", () => {
    it("shows loading spinner while fetching relations", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(RelationGraph, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByRole("status", { name: "Loading relations..." })).toBeTruthy();
      });

      // Resolve all pending calls
      resolveCall(makeResult(makeRelationsResponse("seed-001", [])));
    });
  });

  describe("SEED section", () => {
    it("renders SEED badge", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(makeRelationsResponse("any", [])),
      );
      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("SEED")).toBeTruthy();
      });
    });

    it("renders seed entry node with navigate button", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(makeRelationsResponse("any", [])),
      );
      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Navigate to seed entry seed-001/ }),
        ).toBeTruthy();
      });
    });

    it("calls onNavigate with seedEntryId when seed node clicked", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(makeRelationsResponse("any", [])),
      );
      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Navigate to seed entry seed-001/ }),
        ).toBeTruthy();
      });

      fireEvent.click(screen.getByRole("button", { name: /Navigate to seed entry seed-001/ }));
      expect(onNavigate).toHaveBeenCalledWith("seed-001");
    });

    it("renders Pin button for seed entry", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(makeRelationsResponse("any", [])),
      );
      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Pin seed entry" })).toBeTruthy();
      });
    });

    it("calls onPin when seed pin button is clicked", async () => {
      const bridge = makeMockBridge(async (name, args) => {
        if (name === "distillery_get") {
          const id = (args as Record<string, unknown>)["entry_id"] as string;
          return makeResult(JSON.stringify({ id, content: "Seed entry content", entry_type: "knowledge" }));
        }
        return makeResult(makeRelationsResponse("any", []));
      });
      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Pin seed entry" })).toBeTruthy();
      });

      fireEvent.click(screen.getByRole("button", { name: "Pin seed entry" }));
      await waitFor(() => {
        expect(onPin).toHaveBeenCalledWith(
          expect.objectContaining({ id: "seed-001" }),
        );
      });
    });
  });

  describe("relation grouping", () => {
    it("shows RELATED badge when relations exist", async () => {
      // seed has a citation relation to "related-001"
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "related-001", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("RELATED")).toBeTruthy();
      });
    });

    it("groups relations by type: citation appears as group label", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "related-001", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("citation")).toBeTruthy();
      });
    });

    it("groups multiple relation types separately", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "r1", "citation"),
              makeRelation("seed-001", "r2", "corrects"),
              makeRelation("seed-001", "r3", "link"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("citation")).toBeTruthy();
        expect(screen.getByText("corrects")).toBeTruthy();
        expect(screen.getByText("link")).toBeTruthy();
      });
    });

    it("deduplicates entries that appear in multiple phase1 result relations", async () => {
      // Both seed and p1-001 relate to "shared-node", it should appear once
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "shared-node", "link"),
            ]),
          );
        }
        if (entryId === "p1-001") {
          return makeResult(
            makeRelationsResponse("p1-001", [
              makeRelation("p1-001", "shared-node", "link"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        // Should only have one instance of shared-node navigate button
        const navBtns = screen.getAllByRole("button", { name: /Navigate to/ });
        const sharedBtns = navBtns.filter((b) =>
          b.getAttribute("aria-label")?.includes("shared"),
        );
        // shared-node appears once in the related section
        expect(sharedBtns.length).toBe(1);
      });
    });

    it("excludes seed and phase1 IDs from related entries", async () => {
      // seed relates to "p1-001" (which is already a phase1 result) — should be excluded
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "p1-001", "link"),
              makeRelation("seed-001", "new-node", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        // p1-001 should NOT appear as a related node
        const navBtns = screen.getAllByRole("button", { name: /Navigate to/ });
        const p1Btns = navBtns.filter((b) =>
          b.getAttribute("aria-label")?.includes("p1-001"),
        );
        expect(p1Btns.length).toBe(0);
        // new-node should appear
        expect(screen.getByText("new-node")).toBeTruthy();
      });
    });

    it("shows empty state when no relations found", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(makeRelationsResponse("any", [])),
      );
      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("No relations found for the selected entries.")).toBeTruthy();
      });
    });

    it("renders navigate button for each related entry", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "node-a", "link"),
              makeRelation("seed-001", "node-b", "link"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("node-a")).toBeTruthy();
        expect(screen.getByText("node-b")).toBeTruthy();
      });
    });

    it("calls onNavigate with related entry id when clicked", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "nav-target", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Navigate to nav-target/ })).toBeTruthy();
      });
      fireEvent.click(screen.getByRole("button", { name: /Navigate to nav-target/ }));
      expect(onNavigate).toHaveBeenCalledWith("nav-target");
    });

    it("calls onPin when pin button clicked for related entry", async () => {
      const bridge = makeMockBridge(async (name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (name === "distillery_get") {
          return makeResult(JSON.stringify({ id: entryId, content: "Entry content for " + entryId, entry_type: "knowledge" }));
        }
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "pin-target", "link"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Pin entry pin-target/ })).toBeTruthy();
      });
      fireEvent.click(screen.getByRole("button", { name: /Pin entry pin-target/ }));
      await waitFor(() => {
        expect(onPin).toHaveBeenCalledWith(
          expect.objectContaining({ id: "pin-target" }),
        );
      });
    });
  });

  describe("2nd-degree expand/collapse", () => {
    it("shows expand toggle button for each degree-1 entry", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Expand second-degree relations for deg1-node/ }),
        ).toBeTruthy();
      });
    });

    it("2nd-degree section is collapsed by default", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        const expandBtn = screen.getByRole("button", {
          name: /Expand second-degree relations for deg1-node/,
        }) as HTMLButtonElement;
        expect(expandBtn.getAttribute("aria-expanded")).toBe("false");
      });
    });

    it("expands second-degree section when expand button is clicked", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        if (entryId === "deg1-node") {
          return makeResult(
            makeRelationsResponse("deg1-node", [
              makeRelation("deg1-node", "deg2-node", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Expand second-degree relations for deg1-node/ }),
        ).toBeTruthy();
      });

      fireEvent.click(
        screen.getByRole("button", { name: /Expand second-degree relations for deg1-node/ }),
      );

      await waitFor(() => {
        expect(
          screen.getByLabelText("Second-degree relations of deg1-node"),
        ).toBeTruthy();
      });
    });

    it("collapses second-degree section on second click", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        if (entryId === "deg1-node") {
          return makeResult(
            makeRelationsResponse("deg1-node", [
              makeRelation("deg1-node", "deg2-node", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Expand second-degree relations/ }),
        ).toBeTruthy();
      });

      const expandBtn = screen.getByRole("button", {
        name: /Expand second-degree relations for deg1-node/,
      });

      // First click to expand
      fireEvent.click(expandBtn);
      await waitFor(() => {
        expect(expandBtn.getAttribute("aria-expanded")).toBe("true");
      });

      // Second click to collapse
      fireEvent.click(expandBtn);
      await waitFor(() => {
        expect(expandBtn.getAttribute("aria-expanded")).toBe("false");
        expect(
          screen.queryByLabelText("Second-degree relations of deg1-node"),
        ).toBeNull();
      });
    });

    it("lazy-loads second-degree relations on first expand", async () => {
      let deg1CallCount = 0;
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        if (entryId === "deg1-node") {
          deg1CallCount++;
          return makeResult(
            makeRelationsResponse("deg1-node", [
              makeRelation("deg1-node", "deg2-node", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });

      // Wait for initial load
      await waitFor(() => {
        expect(screen.getByText("SEED")).toBeTruthy();
      });

      // deg1-node should NOT have been called yet
      expect(deg1CallCount).toBe(0);

      // Now expand
      const expandBtn = screen.getByRole("button", {
        name: /Expand second-degree relations for deg1-node/,
      });
      fireEvent.click(expandBtn);

      // Now it should fetch deg1-node's relations
      await waitFor(() => {
        expect(deg1CallCount).toBe(1);
      });
    });

    it("does not re-fetch on subsequent expand/collapse cycles", async () => {
      let deg1CallCount = 0;
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        if (entryId === "deg1-node") {
          deg1CallCount++;
          return makeResult(
            makeRelationsResponse("deg1-node", [
              makeRelation("deg1-node", "deg2-node", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("SEED")).toBeTruthy();
      });

      const expandBtn = screen.getByRole("button", {
        name: /Expand second-degree relations for deg1-node/,
      });

      // Expand
      fireEvent.click(expandBtn);
      await waitFor(() => {
        expect(deg1CallCount).toBe(1);
      });

      // Collapse
      fireEvent.click(expandBtn);
      await waitFor(() => {
        expect(expandBtn.getAttribute("aria-expanded")).toBe("false");
      });

      // Re-expand — should NOT trigger another fetch
      fireEvent.click(expandBtn);
      await waitFor(() => {
        expect(expandBtn.getAttribute("aria-expanded")).toBe("true");
      });
      expect(deg1CallCount).toBe(1);
    });

    it("displays second-degree nodes after expansion", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        if (entryId === "deg1-node") {
          return makeResult(
            makeRelationsResponse("deg1-node", [
              makeRelation("deg1-node", "deg2-node-a", "citation"),
              makeRelation("deg1-node", "deg2-node-b", "link"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("SEED")).toBeTruthy();
      });

      fireEvent.click(
        screen.getByRole("button", { name: /Expand second-degree relations for deg1-node/ }),
      );

      await waitFor(() => {
        expect(screen.getByText("deg2-node-a")).toBeTruthy();
        expect(screen.getByText("deg2-node-b")).toBeTruthy();
      });
    });

    it("second-degree nodes have navigation buttons", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        if (entryId === "deg1-node") {
          return makeResult(
            makeRelationsResponse("deg1-node", [
              makeRelation("deg1-node", "deg2-target", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("SEED")).toBeTruthy();
      });

      fireEvent.click(
        screen.getByRole("button", { name: /Expand second-degree relations for deg1-node/ }),
      );

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Navigate to deg2-target/ }),
        ).toBeTruthy();
      });
    });

    it("calls onNavigate when second-degree node is clicked", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        if (entryId === "deg1-node") {
          return makeResult(
            makeRelationsResponse("deg1-node", [
              makeRelation("deg1-node", "deg2-target", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("SEED")).toBeTruthy();
      });

      fireEvent.click(
        screen.getByRole("button", { name: /Expand second-degree relations for deg1-node/ }),
      );

      await waitFor(() => {
        expect(
          screen.getByRole("button", { name: /Navigate to deg2-target/ }),
        ).toBeTruthy();
      });

      fireEvent.click(screen.getByRole("button", { name: /Navigate to deg2-target/ }));
      expect(onNavigate).toHaveBeenCalledWith("deg2-target");
    });

    it("caps traversal at 2 degrees (does not fetch degree-3)", async () => {
      // After expanding deg1-node, deg2-node appears but has no expand button (cap at 2)
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        if (entryId === "deg1-node") {
          return makeResult(
            makeRelationsResponse("deg1-node", [
              makeRelation("deg1-node", "deg2-node", "citation"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("SEED")).toBeTruthy();
      });

      fireEvent.click(
        screen.getByRole("button", { name: /Expand second-degree relations for deg1-node/ }),
      );

      await waitFor(() => {
        expect(screen.getByText("deg2-node")).toBeTruthy();
      });

      // deg2-node should NOT have an expand button (no degree-3)
      const expandBtns = screen.getAllByRole("button", {
        name: /Expand second-degree relations for/,
      });
      // Only deg1-node has an expand button
      expect(expandBtns).toHaveLength(1);
      expect(expandBtns[0]!.getAttribute("aria-label")).toContain("deg1-node");
    });

    it("shows empty state when no second-degree relations exist", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-isolated", "link"),
            ]),
          );
        }
        // deg1-isolated has no relations
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("SEED")).toBeTruthy();
      });

      fireEvent.click(
        screen.getByRole("button", {
          name: /Expand second-degree relations for deg1-isolated/,
        }),
      );

      await waitFor(() => {
        expect(screen.getByText("No further relations found.")).toBeTruthy();
      });
    });
  });

  describe("error handling", () => {
    it("shows error banner when initial fetch throws", async () => {
      const bridge = makeMockBridge(async () => {
        throw new Error("Network error");
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Network error/)).toBeTruthy();
      });
    });

    it("shows inline error when second-degree fetch fails", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("seed-001", "deg1-node", "link"),
            ]),
          );
        }
        if (entryId === "deg1-node") {
          return makeResult("Fetch failed", true);
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        expect(screen.getByText("SEED")).toBeTruthy();
      });

      fireEvent.click(
        screen.getByRole("button", { name: /Expand second-degree relations for deg1-node/ }),
      );

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Fetch failed/)).toBeTruthy();
      });
    });
  });

  describe("incoming relations", () => {
    it("handles incoming relations (to_id === seedEntryId)", async () => {
      // Another entry relates TO the seed
      const bridge = makeMockBridge(async (_name, args) => {
        const entryId = (args as Record<string, unknown>)["entry_id"] as string;
        if (entryId === "seed-001") {
          return makeResult(
            makeRelationsResponse("seed-001", [
              makeRelation("incoming-src", "seed-001", "corrects"),
            ]),
          );
        }
        return makeResult(makeRelationsResponse(entryId, []));
      });

      render(RelationGraph, { props: { ...defaultProps, bridge } });
      await waitFor(() => {
        // incoming-src should appear in the related section
        expect(screen.getByText("incoming-src")).toBeTruthy();
        expect(screen.getByText("corrects")).toBeTruthy();
      });
    });
  });
});
