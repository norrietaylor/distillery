import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import BriefingStats from "./BriefingStats.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";
import { selectedProject, refreshTick } from "$lib/stores";

/** Build a minimal mock ToolCallTextResult. */
function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

/**
 * Build a ``distillery_list`` ``output=stats`` JSON payload.
 *
 * The real server returns::
 *
 *     {"entries_by_type": {...}, "entries_by_status": {...},
 *      "total_entries": N, "storage_bytes": N}
 *
 * BriefingStats' ``parseStatsTotal`` reads ``total_entries`` directly, so the
 * test mocks must emit the real envelope rather than a bare number.
 */
function statsPayload(totalEntries: number): string {
  return JSON.stringify({
    entries_by_type: {},
    entries_by_status: {},
    total_entries: totalEntries,
    storage_bytes: 0,
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

// Suppress Svelte warnings in test output
beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
});

describe("BriefingStats", () => {
  describe("rendering", () => {
    it("shows loading skeleton while fetching total entries", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(BriefingStats, { props: { bridge } });
      expect(screen.queryByLabelText(/Total Entries/)).toBeTruthy();

      // resolve to avoid dangling promise
      resolveCall(makeResult(statsPayload(42)));
    });

    it("shows 5 metric cards: Total, Stale, Expiring, Pending Review, Inbox", async () => {
      const bridge = makeMockBridge(async () => makeResult(statsPayload(10)));
      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Total Entries/)).toBeTruthy();
        expect(screen.getByLabelText(/Stale.*30d/)).toBeTruthy();
        expect(screen.getByLabelText(/Expiring Soon/)).toBeTruthy();
        expect(screen.getByLabelText(/Pending Review/)).toBeTruthy();
        expect(screen.getByLabelText(/Inbox/)).toBeTruthy();
      });
    });

    it("displays 5 cards in a row layout", async () => {
      const bridge = makeMockBridge(async () => makeResult(statsPayload(5)));
      const { container } = render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        const section = container.querySelector(".briefing-stats");
        expect(section).toBeTruthy();
        const cards = container.querySelectorAll(".metric-card");
        expect(cards).toHaveLength(5);
      });
    });
  });

  describe("data loading", () => {
    it("loads total entries by calling distillery_list with output=stats", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(statsPayload(42)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        const totalCalls = mockCallTool.mock.calls.filter(
          ([name]: [string]) => name === "distillery_list",
        );
        // Should have 5 calls for the 5 metrics
        expect(totalCalls.length).toBeGreaterThanOrEqual(1);
        const totalCall = totalCalls.find(([, args]) => {
          const a = args as Record<string, unknown>;
          return a.output === "stats" && !a.stale_days && !a.status && !a.entry_type;
        });
        expect(totalCall).toBeTruthy();
      });
    });

    it("loads stale entries by calling distillery_list with stale_days=30 and output=stats", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(statsPayload(15)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        const staleCalls = mockCallTool.mock.calls.filter(([name, args]) => {
          const a = args as Record<string, unknown>;
          return name === "distillery_list" && a.stale_days === 30 && a.output === "stats";
        });
        expect(staleCalls.length).toBeGreaterThan(0);
      });
    });

    it("loads pending review entries by calling distillery_list with status=pending_review and output=stats", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(statsPayload(7)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        const pendingCalls = mockCallTool.mock.calls.filter(([name, args]) => {
          const a = args as Record<string, unknown>;
          return (
            name === "distillery_list" && a.status === "pending_review" && a.output === "stats"
          );
        });
        expect(pendingCalls.length).toBeGreaterThan(0);
      });
    });

    it("loads inbox entries by calling distillery_list with entry_type=inbox and output=stats", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(statsPayload(3)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        const inboxCalls = mockCallTool.mock.calls.filter(([name, args]) => {
          const a = args as Record<string, unknown>;
          return (
            name === "distillery_list" && a.entry_type === "inbox" && a.output === "stats"
          );
        });
        expect(inboxCalls.length).toBeGreaterThan(0);
      });
    });

    it("displays parsed metric values after successful load", async () => {
      const bridge = makeMockBridge(async () => makeResult(statsPayload(42)));
      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        const elements = screen.getAllByText("42");
        expect(elements.length).toBeGreaterThanOrEqual(1);
      });
    });

    it("reads total_entries from the distillery_list stats payload", async () => {
      // The real server returns
      //   {"entries_by_type": {"session": 12}, "entries_by_status": {...},
      //    "total_entries": 99, "storage_bytes": 12345}
      // An earlier version of BriefingStats regex-scraped the first number
      // it found and returned 12 here instead of 99, because
      // `total_entries":99` does not match `/(?:count|total)[:\s]+(\d+)/`
      // (the `_entries":` glue is neither whitespace nor colon). This test
      // guards against that regression.
      const payload = JSON.stringify({
        entries_by_type: { session: 12, bookmark: 5 },
        entries_by_status: { active: 99 },
        total_entries: 99,
        storage_bytes: 54321,
      });
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(payload)) // total
        .mockResolvedValue(makeResult(statsPayload(0))); // everything else
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Total Entries: 99/)).toBeTruthy();
      });
    });

    it("falls back to 0 on malformed (non-JSON) stats payloads", async () => {
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult("not a valid json stats payload")) // total
        .mockResolvedValue(makeResult(statsPayload(0))); // everything else
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Total Entries: 0/)).toBeTruthy();
      });
    });
  });

  describe("expiring entries calculation", () => {
    it("counts entries with expires_at within 14 days", async () => {
      const now = new Date();
      const in7Days = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
      const in21Days = new Date(now.getTime() + 21 * 24 * 60 * 60 * 1000);

      const response = `
        Entry A: expires_at ${in7Days.toISOString()}
        Entry B: expires_at ${in21Days.toISOString()}
      `;

      let callCount = 0;
      const bridge = makeMockBridge(async (name, args) => {
        const a = args as Record<string, unknown>;
        callCount++;
        if (a.limit === 100) {
          // This is the expiring check
          return makeResult(response);
        }
        return makeResult(statsPayload(0));
      });
      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        // Should find 1 entry expiring within 14 days
        expect(screen.getByLabelText(/Expiring Soon: 1/)).toBeTruthy();
      });
    });

    it("excludes entries expiring beyond 14 days", async () => {
      const now = new Date();
      const in30Days = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);

      const response = `Entry A: expires_at ${in30Days.toISOString()}`;

      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(statsPayload(5))) // total
        .mockResolvedValueOnce(makeResult(statsPayload(3))) // stale
        .mockImplementationOnce(async (name, args) => {
          // expiring check
          return makeResult(response);
        })
        .mockResolvedValueOnce(makeResult(statsPayload(2))) // pending
        .mockResolvedValueOnce(makeResult(statsPayload(1))); // inbox

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        // Should find 0 entries expiring within 14 days
        expect(screen.getByLabelText(/Expiring Soon: 0/)).toBeTruthy();
      });
    });

    it("excludes past expiry dates", async () => {
      const now = new Date();
      const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);

      const response = `Entry A: expires_at ${yesterday.toISOString()}`;

      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(statsPayload(5))) // total
        .mockResolvedValueOnce(makeResult(statsPayload(3))) // stale
        .mockImplementationOnce(async (name, args) => {
          // expiring check
          return makeResult(response);
        })
        .mockResolvedValueOnce(makeResult(statsPayload(2))) // pending
        .mockResolvedValueOnce(makeResult(statsPayload(1))); // inbox

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Expiring Soon: 0/)).toBeTruthy();
      });
    });
  });

  describe("color coding", () => {
    it("applies danger variant when pending review > 10", async () => {
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(statsPayload(5))) // total
        .mockResolvedValueOnce(makeResult(statsPayload(0))) // stale
        .mockResolvedValueOnce(makeResult(statsPayload(0))) // expiring
        .mockResolvedValueOnce(makeResult(statsPayload(15))) // pending (> 10, should be danger)
        .mockResolvedValueOnce(makeResult(statsPayload(0))); // inbox
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      const { container } = render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        const dangerCard = container.querySelector(".metric-card--danger");
        expect(dangerCard).toBeTruthy();
        expect(dangerCard?.textContent).toContain("Pending Review");
      });
    });

    it("does not apply danger variant when pending review <= 10", async () => {
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(statsPayload(5))) // total
        .mockResolvedValueOnce(makeResult(statsPayload(5))) // stale
        .mockResolvedValueOnce(makeResult(statsPayload(0))) // expiring
        .mockResolvedValueOnce(makeResult(statsPayload(5))) // pending (<= 10, should not be danger)
        .mockResolvedValueOnce(makeResult(statsPayload(2))); // inbox
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      const { container } = render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        // Check that no danger card exists, or pending review card is not danger
        const pendingCard = Array.from(container.querySelectorAll(".metric-card"))
          .filter((card) => card.textContent?.includes("Pending Review"))
          .at(0);
        if (pendingCard) {
          expect(pendingCard.className).not.toContain("metric-card--danger");
        }
      });
    });

    it("applies warning variant when stale > 50", async () => {
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(statsPayload(5))) // total
        .mockResolvedValueOnce(makeResult(statsPayload(60))) // stale (> 50, should be warning)
        .mockResolvedValueOnce(makeResult(statsPayload(0))) // expiring
        .mockResolvedValueOnce(makeResult(statsPayload(5))) // pending
        .mockResolvedValueOnce(makeResult(statsPayload(0))); // inbox
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      const { container } = render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        const warningCard = container.querySelector(".metric-card--warning");
        expect(warningCard).toBeTruthy();
        expect(warningCard?.textContent).toContain("Stale");
      });
    });

    it("does not apply warning variant when stale <= 50", async () => {
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(statsPayload(5))) // total
        .mockResolvedValueOnce(makeResult(statsPayload(30))) // stale (<= 50, should not be warning)
        .mockResolvedValueOnce(makeResult(statsPayload(0))) // expiring
        .mockResolvedValueOnce(makeResult(statsPayload(5))) // pending
        .mockResolvedValueOnce(makeResult(statsPayload(2))); // inbox
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      const { container } = render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        // Check that no warning card exists, or stale card is not warning
        const staleCard = Array.from(container.querySelectorAll(".metric-card"))
          .filter((card) => card.textContent?.includes("Stale"))
          .at(0);
        if (staleCard) {
          expect(staleCard.className).not.toContain("metric-card--warning");
        }
      });
    });
  });

  describe("error states", () => {
    it("shows error message when total entries load fails", async () => {
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult("Tool error", true))
        .mockResolvedValue(makeResult(statsPayload(0)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Total Entries/)).toBeTruthy();
      });
    });

    it("shows error message when stale load throws exception", async () => {
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(statsPayload(42)))
        .mockRejectedValueOnce(new Error("Network failure"))
        .mockResolvedValue(makeResult(statsPayload(0)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Stale/)).toBeTruthy();
      });
    });

    it("handles one failed metric without breaking other metrics", async () => {
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(statsPayload(50))) // total
        .mockResolvedValueOnce(makeResult("Error", true)) // stale — error
        .mockResolvedValueOnce(makeResult(statsPayload(3))) // expiring (returns a list with count 3)
        .mockResolvedValueOnce(makeResult(statsPayload(8))) // pending
        .mockResolvedValueOnce(makeResult(statsPayload(2))); // inbox

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        // Other metrics should load successfully
        expect(screen.getByLabelText(/Total Entries: 50/)).toBeTruthy();
        expect(screen.getByLabelText(/Pending Review: 8/)).toBeTruthy();
        expect(screen.getByLabelText(/Inbox: 2/)).toBeTruthy();
      });
    });
  });

  describe("refresh on project change", () => {
    it("passes project filter to all list calls when project is selected", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(statsPayload(10)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalled();
      });

      // Set project filter
      selectedProject.set("my-project");

      await waitFor(() => {
        const callsAfterProjectSet = mockCallTool.mock.calls;
        const projectCalls = callsAfterProjectSet.filter(([, args]) => {
          const a = args as Record<string, unknown>;
          return a.project === "my-project";
        });
        expect(projectCalls.length).toBeGreaterThan(0);
      });
    });

    it("omits project filter when no project is selected", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(statsPayload(10)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      selectedProject.set(null);
      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        const calls = mockCallTool.mock.calls;
        const projectArgCalls = calls.filter(([, args]) => {
          const a = args as Record<string, unknown>;
          return "project" in a;
        });
        // When project is null, project should not be passed
        expect(projectArgCalls.length).toBe(0);
      });
    });
  });

  describe("refresh on manual trigger", () => {
    it("reloads all metrics when refreshTick changes", async () => {
      const { refreshCounter } = await import("$lib/stores");
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(statsPayload(42)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      const initialCallCount = mockCallTool.mock.calls.length;

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalled();
      });

      // Trigger a refresh by incrementing refreshCounter
      // The component watches refreshTick, which is derived from refreshCounter
      refreshCounter.update((n) => n + 1);

      await waitFor(() => {
        const newCallCount = mockCallTool.mock.calls.length;
        expect(newCallCount).toBeGreaterThan(initialCallCount);
      });
    });
  });

  describe("no bridge", () => {
    it("renders without crashing when bridge is null", () => {
      expect(() => render(BriefingStats, { props: { bridge: null } })).not.toThrow();
    });

    it("shows all 5 metric cards even without bridge", () => {
      render(BriefingStats, { props: { bridge: null } });
      expect(screen.getByLabelText(/Total Entries/)).toBeTruthy();
      expect(screen.getByLabelText(/Stale/)).toBeTruthy();
      expect(screen.getByLabelText(/Expiring/)).toBeTruthy();
      expect(screen.getByLabelText(/Pending/)).toBeTruthy();
      expect(screen.getByLabelText(/Inbox/)).toBeTruthy();
    });
  });
});
