import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import TagNeighborhood from "./TagNeighborhood.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";

/** Build a minimal mock ToolCallTextResult. */
function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

/** Build a distillery_list group_by=tags response. */
function makeTagGroupsResponse(groups: Array<{ value: string; count: number }>): string {
  return JSON.stringify({
    group_by: "tags",
    groups,
    total_groups: groups.length,
    total_entries: groups.reduce((sum, g) => sum + g.count, 0),
  });
}

/** Build a distillery_search response with entries. */
function makeSearchResponse(
  results: Array<{ id: string; content: string; score?: number; entry_type?: string; tags?: string[] }>,
): string {
  return JSON.stringify({
    results: results.map((r) => ({
      score: r.score ?? 0.8,
      entry: {
        id: r.id,
        content: r.content,
        entry_type: r.entry_type ?? "knowledge",
        source: "github.com/test",
        tags: r.tags ?? [],
        created_at: "2026-01-15T12:00:00Z",
      },
    })),
    count: results.length,
  });
}

function makeMockBridge(
  callToolImpl: (name: string, args?: Record<string, unknown>) => Promise<ToolCallTextResult>,
): McpBridge {
  return {
    isConnected: true,
    callTool: vi.fn().mockImplementation(callToolImpl),
  } as unknown as McpBridge;
}

const defaultProps = {
  seedTags: ["lang/python", "domain/ml"],
  project: null,
  investigationTopic: "machine learning in Python",
  onResults: vi.fn(),
  onPin: vi.fn(),
};

beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
  defaultProps.onResults = vi.fn();
  defaultProps.onPin = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TagNeighborhood", () => {
  describe("rendering", () => {
    it("renders without crashing when bridge is null", () => {
      expect(() =>
        render(TagNeighborhood, { props: { ...defaultProps, bridge: null } }),
      ).not.toThrow();
    });

    it("shows the section heading", () => {
      render(TagNeighborhood, { props: { ...defaultProps, bridge: null } });
      expect(screen.getByText("Tag Neighborhood")).toBeTruthy();
    });

    it("shows error when bridge is not connected", async () => {
      render(TagNeighborhood, { props: { ...defaultProps, bridge: null } });
      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Not connected/)).toBeTruthy();
      });
    });

    it("renders the aside element with correct aria-label", () => {
      render(TagNeighborhood, { props: { ...defaultProps, bridge: null } });
      expect(screen.getByRole("complementary", { name: "Tag neighborhood" })).toBeTruthy();
    });
  });

  describe("tag cluster display", () => {
    it("shows loading state while fetching tag clusters", async () => {
      let resolve!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((r) => {
        resolve = r;
      });
      const bridge = makeMockBridge(() => pending);

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByRole("status", { name: "Loading tag clusters..." })).toBeTruthy();
      });

      resolve(makeResult(makeTagGroupsResponse([])));
    });

    it("displays tag clusters with entry counts after fetch", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(
          makeTagGroupsResponse([
            { value: "lang/python", count: 12 },
            { value: "domain/ml", count: 8 },
          ]),
        ),
      );

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
        expect(screen.getByText("(12 entries)")).toBeTruthy();
        expect(screen.getByText("domain/ml")).toBeTruthy();
        expect(screen.getByText("(8 entries)")).toBeTruthy();
      });
    });

    it("shows singular 'entry' for count of 1", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(makeTagGroupsResponse([{ value: "lang/python", count: 1 }])),
      );

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("(1 entry)")).toBeTruthy();
      });
    });

    it("shows empty state when no clusters found", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(makeTagGroupsResponse([])),
      );

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("No related tags found.")).toBeTruthy();
      });
    });

    it("shows error banner when distillery_list fails", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult("Internal server error", true),
      );

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Internal server error/)).toBeTruthy();
      });
    });

    it("renders tag clusters as a list", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(
          makeTagGroupsResponse([
            { value: "lang/python", count: 5 },
            { value: "lang/typescript", count: 3 },
          ]),
        ),
      );

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByRole("list", { name: "Tag clusters" })).toBeTruthy();
      });
    });

    it("calls distillery_list with tag_prefix for each namespace in seedTags", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(makeTagGroupsResponse([])),
      );

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        const calls = vi.mocked(bridge.callTool).mock.calls;
        const listCalls = calls.filter(([name]) => name === "distillery_list");
        expect(listCalls.length).toBeGreaterThanOrEqual(1);
        // Should have called with tag_prefix for "lang" and "domain"
        const prefixes = listCalls.map(([, args]) => (args as Record<string, unknown>)["tag_prefix"]);
        expect(prefixes).toContain("lang");
        expect(prefixes).toContain("domain");
      });
    });

    it("passes project to distillery_list when project is set", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(makeTagGroupsResponse([])),
      );

      render(TagNeighborhood, {
        props: { ...defaultProps, bridge, project: "my-project" },
      });

      await waitFor(() => {
        const calls = vi.mocked(bridge.callTool).mock.calls;
        const listCall = calls.find(([name]) => name === "distillery_list");
        expect(listCall).toBeTruthy();
        const args = listCall![1] as Record<string, unknown>;
        expect(args["project"]).toBe("my-project");
      });
    });
  });

  describe("click-to-search", () => {
    it("clicking a tag cluster calls distillery_search with the tag and investigationTopic", async () => {
      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 10 }]),
          );
        }
        return makeResult(makeSearchResponse([]));
      });

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      await fireEvent.click(
        screen.getByRole("button", { name: "Tag cluster: lang/python, 10 entries" }),
      );

      await waitFor(() => {
        const calls = vi.mocked(bridge.callTool).mock.calls;
        const searchCall = calls.find(([name]) => name === "distillery_search");
        expect(searchCall).toBeTruthy();
        const args = searchCall![1] as Record<string, unknown>;
        expect(args["query"]).toBe("machine learning in Python");
        expect(args["tags"]).toEqual(["lang/python"]);
        expect(args["limit"]).toBe(10);
      });
    });

    it("clicking an already-expanded tag collapses it", async () => {
      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 5 }]),
          );
        }
        return makeResult(makeSearchResponse([]));
      });

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      const btn = screen.getByRole("button", { name: "Tag cluster: lang/python, 5 entries" });

      // Click to expand
      await fireEvent.click(btn);
      await waitFor(() => {
        expect(btn.getAttribute("aria-expanded")).toBe("true");
      });

      // Click again to collapse
      await fireEvent.click(btn);
      await waitFor(() => {
        expect(btn.getAttribute("aria-expanded")).toBe("false");
      });
    });

    it("shows loading spinner while searching tag results", async () => {
      let resolveSearch!: (v: ToolCallTextResult) => void;
      const pendingSearch = new Promise<ToolCallTextResult>((r) => {
        resolveSearch = r;
      });

      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 5 }]),
          );
        }
        return pendingSearch;
      });

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      await fireEvent.click(
        screen.getByRole("button", { name: "Tag cluster: lang/python, 5 entries" }),
      );

      await waitFor(() => {
        expect(screen.getByRole("status", { name: "Searching tag entries..." })).toBeTruthy();
      });

      resolveSearch(makeResult(makeSearchResponse([])));
    });

    it("passes project to distillery_search when project is set", async () => {
      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 3 }]),
          );
        }
        return makeResult(makeSearchResponse([]));
      });

      render(TagNeighborhood, {
        props: { ...defaultProps, bridge, project: "scoped-project" },
      });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      await fireEvent.click(
        screen.getByRole("button", { name: "Tag cluster: lang/python, 3 entries" }),
      );

      await waitFor(() => {
        const calls = vi.mocked(bridge.callTool).mock.calls;
        const searchCall = calls.find(([name]) => name === "distillery_search");
        const args = searchCall![1] as Record<string, unknown>;
        expect(args["project"]).toBe("scoped-project");
      });
    });
  });

  describe("results rendering", () => {
    it("displays search results after clicking a tag cluster", async () => {
      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 5 }]),
          );
        }
        return makeResult(
          makeSearchResponse([
            { id: "r1", content: "Python ML result", score: 0.9 },
            { id: "r2", content: "Another Python result", score: 0.7 },
          ]),
        );
      });

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      await fireEvent.click(
        screen.getByRole("button", { name: "Tag cluster: lang/python, 5 entries" }),
      );

      await waitFor(() => {
        expect(screen.getByText("Python ML result")).toBeTruthy();
        expect(screen.getByText("Another Python result")).toBeTruthy();
      });
    });

    it("shows entry_type badge for each result", async () => {
      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 2 }]),
          );
        }
        return makeResult(
          makeSearchResponse([
            { id: "r1", content: "A bookmark entry", entry_type: "bookmark" },
          ]),
        );
      });

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      await fireEvent.click(
        screen.getByRole("button", { name: "Tag cluster: lang/python, 2 entries" }),
      );

      await waitFor(() => {
        expect(screen.getByText("bookmark")).toBeTruthy();
      });
    });

    it("shows empty state when tag search returns no results", async () => {
      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 4 }]),
          );
        }
        return makeResult(makeSearchResponse([]));
      });

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      await fireEvent.click(
        screen.getByRole("button", { name: "Tag cluster: lang/python, 4 entries" }),
      );

      await waitFor(() => {
        expect(screen.getByText("No results found for this tag.")).toBeTruthy();
      });
    });

    it("shows error banner when tag search fails", async () => {
      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 6 }]),
          );
        }
        return makeResult("Search failed badly", true);
      });

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      await fireEvent.click(
        screen.getByRole("button", { name: "Tag cluster: lang/python, 6 entries" }),
      );

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Search failed badly/)).toBeTruthy();
      });
    });

    it("shows pin button on each search result", async () => {
      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 3 }]),
          );
        }
        return makeResult(
          makeSearchResponse([{ id: "r1", content: "Pinnable result" }]),
        );
      });

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      await fireEvent.click(
        screen.getByRole("button", { name: "Tag cluster: lang/python, 3 entries" }),
      );

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Pin entry" })).toBeTruthy();
      });
    });

    it("calls onPin when pin button is clicked", async () => {
      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 2 }]),
          );
        }
        return makeResult(
          makeSearchResponse([{ id: "pin-1", content: "To pin", entry_type: "note" }]),
        );
      });

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      await fireEvent.click(
        screen.getByRole("button", { name: "Tag cluster: lang/python, 2 entries" }),
      );

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Pin entry" })).toBeTruthy();
      });

      await fireEvent.click(screen.getByRole("button", { name: "Pin entry" }));
      expect(defaultProps.onPin).toHaveBeenCalledWith(
        expect.objectContaining({ id: "pin-1" }),
      );
    });

    it("calls onResults callback after successful tag search", async () => {
      const bridge = makeMockBridge(async (name) => {
        if (name === "distillery_list") {
          return makeResult(
            makeTagGroupsResponse([{ value: "lang/python", count: 5 }]),
          );
        }
        return makeResult(
          makeSearchResponse([{ id: "r1", content: "Result" }]),
        );
      });

      render(TagNeighborhood, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("lang/python")).toBeTruthy();
      });

      await fireEvent.click(
        screen.getByRole("button", { name: "Tag cluster: lang/python, 5 entries" }),
      );

      await waitFor(() => {
        expect(defaultProps.onResults).toHaveBeenCalledWith(
          expect.arrayContaining([expect.objectContaining({ id: "r1" })]),
        );
      });
    });
  });
});
