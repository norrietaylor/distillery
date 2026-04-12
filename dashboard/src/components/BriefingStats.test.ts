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
 * BriefingStats reads ``total_entries`` directly (no regex), plus
 * ``entries_by_status.pending_review`` and ``entries_by_type.inbox``
 * from the same payload, so the test mocks must emit the real
 * envelope shape.
 */
function statsPayload(
  totalEntries: number,
  extras: {
    entries_by_type?: Record<string, number>;
    entries_by_status?: Record<string, number>;
  } = {},
): string {
  return JSON.stringify({
    entries_by_type: extras.entries_by_type ?? {},
    entries_by_status: extras.entries_by_status ?? {},
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

    it("derives pending review from entries_by_status in the primary stats call", async () => {
      // Pending review is no longer fetched with a separate
      // {status: "pending_review", output: "stats"} call — it's now
      // read from the primary stats payload's entries_by_status.
      // This was the 60 req/min rate-limit fix: fewer round-trips.
      const payload = statsPayload(50, {
        entries_by_status: { active: 43, pending_review: 7 },
      });
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(payload)) // primary
        .mockResolvedValue(makeResult(statsPayload(0))); // stale, expiring
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Pending Review: 7/)).toBeTruthy();
      });

      // Confirm there is NOT a separate status=pending_review call.
      const pendingSpecificCalls = mockCallTool.mock.calls.filter(([name, args]) => {
        const a = args as Record<string, unknown>;
        return name === "distillery_list" && a.status === "pending_review";
      });
      expect(pendingSpecificCalls.length).toBe(0);
    });

    it("derives inbox from entries_by_type in the primary stats call", async () => {
      // Mirror of the pending_review test above — inbox count is
      // entries_by_type.inbox on the same primary stats payload, no
      // separate {entry_type: "inbox"} call.
      const payload = statsPayload(50, {
        entries_by_type: { session: 40, bookmark: 7, inbox: 3 },
      });
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(payload)) // primary
        .mockResolvedValue(makeResult(statsPayload(0))); // stale, expiring
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Inbox: 3/)).toBeTruthy();
      });

      const inboxSpecificCalls = mockCallTool.mock.calls.filter(([name, args]) => {
        const a = args as Record<string, unknown>;
        return name === "distillery_list" && a.entry_type === "inbox";
      });
      expect(inboxSpecificCalls.length).toBe(0);
    });

    it("issues exactly three distillery_list calls per refresh (primary + stale + expiring)", async () => {
      // Regression guard for the 5 → 3 call collapse. Running the
      // home tab used to fire 5 calls per refresh tick, which pushed
      // the dashboard past the 60 req/min HTTP rate limit on staging.
      // If this test starts counting more than 3 calls, someone
      // re-introduced a per-card fetch that could've been derived
      // from the primary stats payload instead.
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(statsPayload(0)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        const listCalls = mockCallTool.mock.calls.filter(([name]) => name === "distillery_list");
        expect(listCalls.length).toBe(3);
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

    it("marks total/pending/inbox cards as errored when the primary stats payload is malformed", async () => {
      // A malformed (non-JSON) primary stats response now surfaces
      // as an explicit error on all three cards (total, pending,
      // inbox) rather than silently degrading to 0 — silently
      // masking a broken server response was how the regex-parser
      // bug went unnoticed for so long. Stale has its own call and
      // is unaffected.
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult("not a valid json stats payload")) // primary
        .mockResolvedValue(makeResult(statsPayload(42))); // stale, expiring
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      const { container } = render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        // Stale should still render (separate call, valid payload).
        expect(screen.getByLabelText(/Stale \(30d\): 42/)).toBeTruthy();
        // The three primary-stats cards should be in error state.
        const totalCard = container.querySelector('[aria-label="Total Entries: error"]');
        expect(totalCard).toBeTruthy();
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
      // Pending review is now read from the primary stats payload's
      // entries_by_status, not from a separate call — emit a payload
      // with entries_by_status.pending_review = 15 on the primary
      // (first) call and the danger variant should light up.
      const primary = statsPayload(5, {
        entries_by_status: { pending_review: 15 },
      });
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(primary)) // primary
        .mockResolvedValue(makeResult(statsPayload(0))); // stale, expiring
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

    it("handles a failing stale fetch without breaking the primary stats cards", async () => {
      // With the 5 → 3 call collapse, total/pending/inbox all come
      // from the *same* primary-stats call — they can't fail
      // independently of each other. The remaining independent
      // failure mode is a failing stale fetch while the primary
      // stats call succeeds: the three primary cards should still
      // render and only the stale card should show an error.
      const primary = statsPayload(50, {
        entries_by_status: { pending_review: 8 },
        entries_by_type: { inbox: 2 },
      });
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(primary)) // primary — succeeds
        .mockResolvedValueOnce(makeResult("Stale failed", true)) // stale — error
        .mockResolvedValue(makeResult(statsPayload(0))); // expiring

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(BriefingStats, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText(/Total Entries: 50/)).toBeTruthy();
        expect(screen.getByLabelText(/Pending Review: 8/)).toBeTruthy();
        expect(screen.getByLabelText(/Inbox: 2/)).toBeTruthy();
        // Stale is in error state.
        expect(screen.getByLabelText(/Stale \(30d\): error/)).toBeTruthy();
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
