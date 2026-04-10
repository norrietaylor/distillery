import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import InvestigateMode from "./InvestigateMode.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";

/** Build a minimal mock ToolCallTextResult. */
function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

/** Build a JSON result entry. */
function makeEntry(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: `id-${Math.random().toString(36).slice(2)}`,
    content: "Test investigation result content",
    source: "github.com/example",
    entry_type: "knowledge",
    score: 0.82,
    tags: ["test"],
    created_at: "2026-01-15T12:00:00Z",
    ...overrides,
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

const defaultProps = {
  seedEntryId: "seed-001",
  seedTitle: "Seed Entry Title",
  seedContent: "This is the seed entry content for investigation",
  onExit: vi.fn(),
  onPin: vi.fn(),
};

// Suppress Svelte warnings in test output
beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
  defaultProps.onExit = vi.fn();
  defaultProps.onPin = vi.fn();
});

describe("InvestigateMode", () => {
  describe("shell rendering", () => {
    it("renders without crashing when bridge is null", () => {
      expect(() =>
        render(InvestigateMode, { props: { ...defaultProps, bridge: null } }),
      ).not.toThrow();
    });

    it("shows the investigation title", () => {
      render(InvestigateMode, { props: { ...defaultProps, bridge: null } });
      expect(screen.getByText("Investigation")).toBeTruthy();
    });

    it("renders the investigation mode section", () => {
      render(InvestigateMode, { props: { ...defaultProps, bridge: null } });
      expect(screen.getByLabelText("Investigation mode")).toBeTruthy();
    });
  });

  describe("back button", () => {
    it("shows a Back to results button", () => {
      render(InvestigateMode, { props: { ...defaultProps, bridge: null } });
      expect(screen.getByRole("button", { name: "Back to results" })).toBeTruthy();
    });

    it("calls onExit when back button is clicked", async () => {
      render(InvestigateMode, { props: { ...defaultProps, bridge: null } });
      const btn = screen.getByRole("button", { name: "Back to results" });
      await fireEvent.click(btn);
      expect(defaultProps.onExit).toHaveBeenCalledOnce();
    });
  });

  describe("phase indicator", () => {
    it("renders 4 phase buttons", () => {
      render(InvestigateMode, { props: { ...defaultProps, bridge: null } });
      const nav = screen.getByLabelText("Investigation phases");
      expect(nav).toBeTruthy();
      // Check all 4 phase buttons are present
      expect(screen.getByRole("button", { name: "Phase 1: Semantic Search" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "Phase 2: Relation Graph" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "Phase 3: Tag Neighborhood" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "Phase 4: Gap Analysis" })).toBeTruthy();
    });

    it("marks Phase 1 as current step", () => {
      render(InvestigateMode, { props: { ...defaultProps, bridge: null } });
      const phase1Btn = screen.getByRole("button", { name: "Phase 1: Semantic Search" });
      expect(phase1Btn.getAttribute("aria-current")).toBe("step");
    });

    it("disables phases 2-4 when not completed", () => {
      render(InvestigateMode, { props: { ...defaultProps, bridge: null } });
      const phase2 = screen.getByRole("button", { name: "Phase 2: Relation Graph" }) as HTMLButtonElement;
      const phase3 = screen.getByRole("button", { name: "Phase 3: Tag Neighborhood" }) as HTMLButtonElement;
      const phase4 = screen.getByRole("button", { name: "Phase 4: Gap Analysis" }) as HTMLButtonElement;
      expect(phase2.disabled).toBe(true);
      expect(phase3.disabled).toBe(true);
      expect(phase4.disabled).toBe(true);
    });
  });

  describe("breadcrumb trail", () => {
    it("shows the seed entry as the initial breadcrumb", () => {
      render(InvestigateMode, { props: { ...defaultProps, bridge: null } });
      const breadcrumb = screen.getByLabelText("Investigation path");
      expect(breadcrumb).toBeTruthy();
      expect(screen.getByText("Seed Entry Title")).toBeTruthy();
    });

    it("marks the current breadcrumb with aria-current=location", () => {
      render(InvestigateMode, { props: { ...defaultProps, bridge: null } });
      const current = screen.getByText("Seed Entry Title");
      expect(current.getAttribute("aria-current")).toBe("location");
    });
  });

  describe("Phase 1 — Semantic Search", () => {
    it("shows loading state while search is in progress", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByRole("status", { name: "Searching related entries..." })).toBeTruthy();
      });

      resolveCall(makeResult("[]"));
    });

    it("calls distillery_recall with seed content as query", async () => {
      const bridge = makeMockBridge(async () => makeResult("[]"));

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(bridge.callTool).toHaveBeenCalledWith(
          "distillery_recall",
          expect.objectContaining({
            query: "This is the seed entry content for investigation",
            limit: 10,
          }),
        );
      });
    });

    it("displays search result cards after successful search", async () => {
      const results = [
        makeEntry({ id: "r1", content: "First related result", score: 0.9 }),
        makeEntry({ id: "r2", content: "Second related result", score: 0.7 }),
      ];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(results)));

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("First related result")).toBeTruthy();
        expect(screen.getByText("Second related result")).toBeTruthy();
      });
    });

    it("shows error banner when search fails", async () => {
      const bridge = makeMockBridge(async () => makeResult("Search error", true));

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Search error/)).toBeTruthy();
      });
    });

    it("shows empty state when no results found", async () => {
      const bridge = makeMockBridge(async () => makeResult("[]"));

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("No related entries found.")).toBeTruthy();
      });
    });

    it("filters out the seed entry from results", async () => {
      const results = [
        makeEntry({ id: "seed-001", content: "Seed entry itself", score: 1.0 }),
        makeEntry({ id: "other-1", content: "Other result", score: 0.8 }),
      ];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(results)));

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("Other result")).toBeTruthy();
        expect(screen.queryByText("Seed entry itself")).toBeNull();
      });
    });

    it("shows pin button on each result card", async () => {
      const results = [makeEntry({ id: "r1", content: "Result to pin" })];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(results)));

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Pin entry" })).toBeTruthy();
      });
    });

    it("calls onPin when pin button is clicked", async () => {
      const results = [makeEntry({ id: "pin-1", content: "Pinnable result", entry_type: "note" })];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(results)));

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Pin entry" })).toBeTruthy();
      });

      await fireEvent.click(screen.getByRole("button", { name: "Pin entry" }));
      expect(defaultProps.onPin).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "pin-1",
          type: "note",
        }),
      );
    });
  });

  describe("pivot", () => {
    it("updates breadcrumb trail when a result card is clicked", async () => {
      const results = [
        makeEntry({ id: "pivot-1", content: "Pivot target content", score: 0.85 }),
      ];
      // First call returns the initial results, second call returns empty
      let callCount = 0;
      const bridge = makeMockBridge(async () => {
        callCount++;
        if (callCount === 1) return makeResult(JSON.stringify(results));
        return makeResult("[]");
      });

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      // Wait for initial results
      await waitFor(() => {
        expect(screen.getByText("Pivot target content")).toBeTruthy();
      });

      // Click to pivot
      await fireEvent.click(
        screen.getByLabelText("Pivot to: Pivot target content"),
      );

      // Breadcrumb should now have 2 entries — seed becomes a link
      await waitFor(() => {
        // The seed title should now be a clickable breadcrumb link
        expect(screen.getByLabelText("Return to Seed Entry Title")).toBeTruthy();
        // The pivot target becomes current breadcrumb
        expect(screen.getByText("Pivot target content")).toBeTruthy();
      });
    });

    it("triggers a new search after pivot", async () => {
      const results = [
        makeEntry({ id: "pivot-2", content: "New seed for search", score: 0.9 }),
      ];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(results)));

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      await waitFor(() => {
        expect(screen.getByText("New seed for search")).toBeTruthy();
      });

      // Click to pivot
      await fireEvent.click(
        screen.getByLabelText("Pivot to: New seed for search"),
      );

      // Should have been called again with new query
      await waitFor(() => {
        expect((bridge.callTool as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThanOrEqual(2);
      });
    });
  });

  describe("breadcrumb navigation", () => {
    it("navigating back via breadcrumb resets to that point", async () => {
      const results = [
        makeEntry({ id: "pivot-3", content: "Intermediate pivot", score: 0.8 }),
      ];
      let callCount = 0;
      const bridge = makeMockBridge(async () => {
        callCount++;
        if (callCount === 1) return makeResult(JSON.stringify(results));
        return makeResult("[]");
      });

      render(InvestigateMode, { props: { ...defaultProps, bridge } });

      // Wait for initial results
      await waitFor(() => {
        expect(screen.getByText("Intermediate pivot")).toBeTruthy();
      });

      // Pivot to create a second breadcrumb
      await fireEvent.click(
        screen.getByLabelText("Pivot to: Intermediate pivot"),
      );

      // Now click the seed breadcrumb to go back
      await waitFor(() => {
        const backLink = screen.getByLabelText("Return to Seed Entry Title");
        expect(backLink).toBeTruthy();
      });

      await fireEvent.click(screen.getByLabelText("Return to Seed Entry Title"));

      // The seed should be current again
      await waitFor(() => {
        const current = screen.getByText("Seed Entry Title");
        expect(current.getAttribute("aria-current")).toBe("location");
      });
    });
  });
});
