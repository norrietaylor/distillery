import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import HealthOverview from "./HealthOverview.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";
import { selectedProject, refreshCounter } from "$lib/stores";

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

/** Build a bridge that returns different responses based on call arguments. */
function makeMockBridge(
  callToolImpl: (name: string, args?: Record<string, unknown>) => Promise<ToolCallTextResult>,
): McpBridge {
  return {
    isConnected: true,
    callTool: vi.fn().mockImplementation(callToolImpl),
  } as unknown as McpBridge;
}

/** Default bridge that returns sensible defaults for all calls. */
function makeDefaultBridge(): McpBridge {
  return makeMockBridge(async (_name, args) => {
    const a = args as Record<string, unknown>;
    if (a.group_by === "entry_type") {
      return makeResult('[{"entry_type":"insight","count":10},{"entry_type":"session","count":5}]');
    }
    if (a.group_by === "status") {
      return makeResult('[{"status":"active","count":12},{"status":"pending_review","count":3}]');
    }
    if (a.output === "stats") {
      if (a.status === "active") return makeResult("12");
      if (a.status === "pending_review") return makeResult("3");
      if (a.status === "archived") return makeResult("2");
      if (a.entry_type === "inbox") return makeResult("1");
      // Global stats response with multiple fields
      return makeResult("total: 18\nactive: 12\npending_review: 3\narchived: 2\ninbox: 1\nstorage_bytes: 2048");
    }
    return makeResult("0");
  });
}

// Suppress Svelte warnings in test output
beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
  selectedProject.set(null);
});

// ── Tests ────────────────────────────────────────────────────────────────────

describe("HealthOverview", () => {
  describe("metric cards", () => {
    it("renders 5 metric cards: Total Entries, Active, Pending Review, Archived, Inbox", async () => {
      const bridge = makeDefaultBridge();
      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Total Entries/)).toBeTruthy();
        expect(screen.getByLabelText(/Active/)).toBeTruthy();
        expect(screen.getByLabelText(/Pending Review/)).toBeTruthy();
        expect(screen.getByLabelText(/Archived/)).toBeTruthy();
        expect(screen.getByLabelText(/Inbox/)).toBeTruthy();
      });
    });

    it("renders a row of 5 metric-card elements", async () => {
      const bridge = makeDefaultBridge();
      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const cards = container.querySelectorAll(".metric-card");
        expect(cards.length).toBe(5);
      });
    });

    it("calls distillery_list with output=stats to populate metrics", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("0"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const statsCalls = mockCallTool.mock.calls.filter(
          (call: unknown[]) =>
            call[0] === "distillery_list" && (call[1] as Record<string, unknown>)?.output === "stats" && !(call[1] as Record<string, unknown>)?.status && !(call[1] as Record<string, unknown>)?.entry_type,
        );
        expect(statsCalls.length).toBeGreaterThan(0);
      });
    });

    it("populates Total Entries metric from stats response", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.output === "stats" && !a.status && !a.entry_type) {
          return makeResult("total: 42");
        }
        return makeResult("0");
      });

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Total Entries: 42/)).toBeTruthy();
      });
    });

    it("passes project filter to metric calls when project is selected", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("0"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      selectedProject.set("my-project");
      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const projectCalls = mockCallTool.mock.calls.filter(
          (call: unknown[]) =>
            (call[1] as Record<string, unknown>)?.project === "my-project",
        );
        expect(projectCalls.length).toBeGreaterThan(0);
      });
    });
  });

  describe("pie chart — entries by type", () => {
    it("renders pie chart section for entries by type", async () => {
      const bridge = makeDefaultBridge();
      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("Entries by Type")).toBeTruthy();
      });
    });

    it("calls distillery_list with group_by=entry_type for pie chart data", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("0"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const groupByCalls = mockCallTool.mock.calls.filter(
          (call: unknown[]) =>
            call[0] === "distillery_list" &&
            (call[1] as Record<string, unknown>)?.group_by === "entry_type",
        );
        expect(groupByCalls.length).toBeGreaterThan(0);
      });
    });

    it("renders pie chart SVG with slices for each type", async () => {
      const bridge = makeDefaultBridge();
      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        // The pie chart renders SVG paths for each slice
        const paths = container.querySelectorAll(".pie-chart svg path");
        expect(paths.length).toBeGreaterThan(0);
      });
    });

    it("renders legend entries for each type", async () => {
      const bridge = makeDefaultBridge();
      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const legendItems = container.querySelectorAll(".legend-item");
        expect(legendItems.length).toBeGreaterThan(0);
      });
    });

    it("parses JSON group_by response for pie chart", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.group_by === "entry_type") {
          return makeResult('[{"entry_type":"insight","count":7},{"entry_type":"bookmark","count":3}]');
        }
        return makeResult("0");
      });

      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const legendLabels = container.querySelectorAll(".legend-label");
        const labels = Array.from(legendLabels).map((el) => el.textContent?.trim());
        expect(labels).toContain("insight");
        expect(labels).toContain("bookmark");
      });
    });

    it("shows empty-state chart when no type data", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.group_by === "entry_type") {
          return makeResult("[]");
        }
        return makeResult("0");
      });

      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        // The empty state shows "No data" inside the pie chart
        const emptyStates = container.querySelectorAll(".pie-chart .empty-state");
        expect(emptyStates.length).toBeGreaterThan(0);
      });
    });
  });

  describe("bar chart — entries by status", () => {
    it("renders bar chart section for entries by status", async () => {
      const bridge = makeDefaultBridge();
      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("Entries by Status")).toBeTruthy();
      });
    });

    it("calls distillery_list with group_by=status for bar chart data", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("0"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const groupByCalls = mockCallTool.mock.calls.filter(
          (call: unknown[]) =>
            call[0] === "distillery_list" &&
            (call[1] as Record<string, unknown>)?.group_by === "status",
        );
        expect(groupByCalls.length).toBeGreaterThan(0);
      });
    });

    it("renders bar chart SVG with bars for each status", async () => {
      const bridge = makeDefaultBridge();
      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const rects = container.querySelectorAll(".bar-chart svg rect");
        expect(rects.length).toBeGreaterThan(0);
      });
    });

    it("parses JSON group_by response for bar chart", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.group_by === "status") {
          return makeResult('[{"status":"active","count":15},{"status":"archived","count":4}]');
        }
        return makeResult("0");
      });

      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        // Check SVG text labels for status names
        const textEls = container.querySelectorAll(".bar-chart svg text");
        const labels = Array.from(textEls).map((el) => el.textContent?.trim());
        expect(labels.some((l) => l === "active")).toBe(true);
        expect(labels.some((l) => l === "archived")).toBe(true);
      });
    });

    it("shows empty-state chart when no status data", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.group_by === "status") {
          return makeResult("[]");
        }
        return makeResult("0");
      });

      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const emptyStates = container.querySelectorAll(".bar-chart .empty-state");
        expect(emptyStates.length).toBeGreaterThan(0);
      });
    });
  });

  describe("storage size display", () => {
    it("displays storage in KB for values under 1 MB", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.output === "stats" && !a.status && !a.entry_type) {
          return makeResult("total: 5\nstorage_bytes: 2048");
        }
        return makeResult("0");
      });

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Storage size/i)).toBeTruthy();
        expect(screen.getByText(/KB/)).toBeTruthy();
      });
    });

    it("displays storage in MB for values under 1 GB", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.output === "stats" && !a.status && !a.entry_type) {
          return makeResult("total: 100\nstorage_bytes: 5242880");
        }
        return makeResult("0");
      });

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/MB/)).toBeTruthy();
      });
    });

    it("displays storage in GB for large values", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.output === "stats" && !a.status && !a.entry_type) {
          return makeResult("total: 1000\nstorage_bytes: 2147483648");
        }
        return makeResult("0");
      });

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/GB/)).toBeTruthy();
      });
    });

    it("does not render storage row when storage_bytes is not in stats response", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.output === "stats" && !a.status && !a.entry_type) {
          return makeResult("total: 5");
        }
        return makeResult("0");
      });

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        // The storage row should not appear if no storage_bytes field
        expect(screen.queryByLabelText(/Storage size/i)).toBeNull();
      });
    });
  });

  describe("auto-refresh", () => {
    it("reloads all health data when refreshTick changes", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("0"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalled();
      });

      const initialCallCount = mockCallTool.mock.calls.length;

      // Trigger refresh
      refreshCounter.update((n) => n + 1);

      await waitFor(() => {
        expect(mockCallTool.mock.calls.length).toBeGreaterThan(initialCallCount);
      });
    });

    it("reloads data when project filter changes", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("0"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalled();
      });

      const initialCallCount = mockCallTool.mock.calls.length;

      // Change project
      selectedProject.set("new-project");

      await waitFor(() => {
        const newCalls = mockCallTool.mock.calls.slice(initialCallCount);
        const projectCalls = newCalls.filter(
          (call: unknown[]) =>
            (call[1] as Record<string, unknown>)?.project === "new-project",
        );
        expect(projectCalls.length).toBeGreaterThan(0);
      });
    });
  });

  describe("empty KB state", () => {
    it("renders metric cards with zero values when KB is empty", async () => {
      const bridge = makeMockBridge(async () => makeResult("0"));

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        // With all zeros, cards should still render (not crash)
        expect(screen.getByLabelText(/Total Entries/)).toBeTruthy();
      });
    });

    it("shows empty state pie chart when no type data returned for empty KB", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.group_by === "entry_type") {
          return makeResult("[]");
        }
        return makeResult("0");
      });

      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        // Empty state should display without errors
        const emptyStates = container.querySelectorAll(".empty-state");
        expect(emptyStates.length).toBeGreaterThanOrEqual(1);
      });
    });

    it("shows empty state bar chart when no status data returned for empty KB", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.group_by === "status") {
          return makeResult("[]");
        }
        return makeResult("0");
      });

      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const emptyStates = container.querySelectorAll(".bar-chart .empty-state");
        expect(emptyStates.length).toBeGreaterThan(0);
      });
    });

    it("does not throw when bridge is null", () => {
      expect(() =>
        render(HealthOverview, { props: { bridge: null } }),
      ).not.toThrow();
    });
  });

  describe("color consistency", () => {
    it("uses the same color for a given entry_type in pie chart", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.group_by === "entry_type") {
          return makeResult('[{"entry_type":"insight","count":5}]');
        }
        return makeResult("0");
      });

      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        // "insight" should use the purple/accent color #cba6f7 / rgb(203, 166, 247)
        const swatch = container.querySelector(".legend-swatch");
        expect(swatch).toBeTruthy();
        const bgStyle = (swatch as HTMLElement)?.style?.background ?? "";
        const hasColor = bgStyle.includes("cba6f7") || bgStyle.includes("203, 166, 247");
        expect(hasColor).toBe(true);
      });
    });

    it("applies status-specific colors to bar chart bars", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.group_by === "status") {
          return makeResult('[{"status":"active","count":10}]');
        }
        return makeResult("0");
      });

      const { container } = render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        // "active" should use green #a6e3a1
        const rect = container.querySelector(".bar-chart svg rect");
        expect(rect).toBeTruthy();
        const fill = rect?.getAttribute("fill");
        expect(fill).toBe("#a6e3a1");
      });
    });
  });

  describe("error handling", () => {
    it("shows error state when metric fetch fails", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.output === "stats" && !a.status && !a.entry_type) {
          return makeResult("error", true);
        }
        return makeResult("0");
      });

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        // Metric cards should still render (with error state)
        expect(screen.getByLabelText(/Total Entries/)).toBeTruthy();
      });
    });

    it("shows error message when type chart fetch fails", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.group_by === "entry_type") {
          return makeResult("error", true);
        }
        return makeResult("0");
      });

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        // Error state should display
        const alerts = screen.getAllByRole("alert");
        const typeChartError = alerts.find((el) =>
          el.textContent?.includes("type distribution") ||
          el.textContent?.includes("Failed to load"),
        );
        expect(typeChartError).toBeTruthy();
      });
    });

    it("shows error message when status chart fetch fails", async () => {
      const bridge = makeMockBridge(async (_name, args) => {
        const a = args as Record<string, unknown>;
        if (a.group_by === "status") {
          return makeResult("error", true);
        }
        return makeResult("0");
      });

      render(HealthOverview, { props: { bridge } });

      await waitFor(() => {
        const alerts = screen.getAllByRole("alert");
        const statusChartError = alerts.find((el) =>
          el.textContent?.includes("status distribution") ||
          el.textContent?.includes("Failed to load"),
        );
        expect(statusChartError).toBeTruthy();
      });
    });
  });
});
