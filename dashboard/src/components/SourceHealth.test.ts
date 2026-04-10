import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import SourceHealth from "./SourceHealth.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";
import { activeTab, refreshCounter } from "$lib/stores";

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
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

/** Build a JSON line for a feed source. */
function sourceLine(overrides: Record<string, unknown> = {}): string {
  const now = new Date().toISOString();
  const src = {
    url: "https://example.com/feed.rss",
    source_type: "rss",
    label: "Example Feed",
    last_poll_at: now,
    items_stored: 10,
    error_count: 0,
    poll_interval_minutes: 60,
    trust_weight: 1.0,
    added_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
  return JSON.stringify(src);
}

/** Build an ISO timestamp that is a given number of minutes ago. */
function minutesAgo(n: number): string {
  return new Date(Date.now() - n * 60 * 1000).toISOString();
}

// Suppress Svelte warnings in test output
beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
  activeTab.set("manage");
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("SourceHealth", () => {
  describe("table rendering", () => {
    it("renders all required column headers", async () => {
      const line = sourceLine();
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("Source")).toBeTruthy();
        expect(screen.getByText("Type")).toBeTruthy();
        expect(screen.getByText("Label")).toBeTruthy();
        expect(screen.getByText("Last Poll")).toBeTruthy();
        expect(screen.getByText("Items Stored")).toBeTruthy();
        expect(screen.getByText("Errors")).toBeTruthy();
        expect(screen.getByText("Status")).toBeTruthy();
      });
    });

    it("renders a row for each source", async () => {
      const lines = [
        sourceLine({ url: "https://alpha.com/feed", label: "Alpha Feed" }),
        sourceLine({ url: "https://beta.com/feed", label: "Beta Feed" }),
        sourceLine({ url: "https://gamma.com/feed", label: "Gamma Feed" }),
      ].join("\n");
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("Alpha Feed")).toBeTruthy();
        expect(screen.getByText("Beta Feed")).toBeTruthy();
        expect(screen.getByText("Gamma Feed")).toBeTruthy();
      });
    });

    it("displays source type badge", async () => {
      const line = sourceLine({ source_type: "github", url: "https://github.com/org/repo" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("github")).toBeTruthy();
      });
    });

    it("shows loading skeleton while fetching", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(SourceHealth, { props: { bridge } });
      expect(screen.getByRole("status")).toBeTruthy();

      resolveCall(makeResult(""));
    });

    it("shows error banner on tool failure", async () => {
      const bridge = makeMockBridge(async () => makeResult("Internal server error", true));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Internal server error/)).toBeTruthy();
      });
    });

    it("shows error banner on thrown exception", async () => {
      const bridge = makeMockBridge(async () => {
        throw new Error("Network failure");
      });
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Network failure/)).toBeTruthy();
      });
    });

    it("calls watch(action=list) on mount", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(""));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
        const watchCalls = calls.filter(([name]) => name === "distillery_watch");
        expect(watchCalls.length).toBeGreaterThan(0);
        const [, args] = watchCalls[0]!;
        expect(args["action"]).toBe("list");
      });
    });
  });

  describe("status derivation", () => {
    it("shows Green (Healthy) when polled within the interval", async () => {
      // polled 30 min ago, interval 60 min → within interval
      const line = sourceLine({
        url: "https://healthy.com/feed",
        last_poll_at: minutesAgo(30),
        poll_interval_minutes: 60,
        error_count: 0,
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        const badge = document.querySelector('[data-status="healthy"]');
        expect(badge).toBeTruthy();
        expect(badge?.textContent?.trim()).toBe("Healthy");
      });
    });

    it("shows Yellow (Overdue) when last poll older than 1.5x interval", async () => {
      // polled 100 min ago, interval 60 min → 100/60 ≈ 1.67x → overdue
      const line = sourceLine({
        url: "https://overdue.com/feed",
        last_poll_at: minutesAgo(100),
        poll_interval_minutes: 60,
        error_count: 0,
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        const badge = document.querySelector('[data-status="overdue"]');
        expect(badge).toBeTruthy();
        expect(badge?.textContent?.trim()).toBe("Overdue");
      });
    });

    it("shows Red (Error) when errors are present", async () => {
      const line = sourceLine({
        url: "https://error.com/feed",
        last_poll_at: minutesAgo(30),
        poll_interval_minutes: 60,
        error_count: 3,
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        const badge = document.querySelector('[data-status="error"]');
        expect(badge).toBeTruthy();
        expect(badge?.textContent?.trim()).toBe("Error");
      });
    });

    it("shows Red (Error) when last poll older than 3x interval", async () => {
      // polled 200 min ago, interval 60 min → >3x → error
      const line = sourceLine({
        url: "https://stale.com/feed",
        last_poll_at: minutesAgo(200),
        poll_interval_minutes: 60,
        error_count: 0,
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        const badge = document.querySelector('[data-status="error"]');
        expect(badge).toBeTruthy();
      });
    });

    it("shows Gray (Never polled) when last_poll_at is null", async () => {
      const line = sourceLine({
        url: "https://never.com/feed",
        last_poll_at: null,
        error_count: 0,
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        const badge = document.querySelector('[data-status="never"]');
        expect(badge).toBeTruthy();
        expect(badge?.textContent?.trim()).toBe("Never polled");
      });
    });
  });

  describe("relative time display", () => {
    it("displays last poll as relative time (minutes)", async () => {
      const line = sourceLine({
        url: "https://recent.com/feed",
        last_poll_at: minutesAgo(5),
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        const cell = document.querySelector('[data-testid="last-poll-https://recent.com/feed"]');
        expect(cell?.textContent).toMatch(/\d+ minutes? ago/);
      });
    });

    it("displays last poll as relative time (hours)", async () => {
      const line = sourceLine({
        url: "https://hourly.com/feed",
        last_poll_at: minutesAgo(130),
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        const cell = document.querySelector('[data-testid="last-poll-https://hourly.com/feed"]');
        expect(cell?.textContent).toMatch(/\d+ hours? ago/);
      });
    });

    it("displays em-dash when last_poll_at is null", async () => {
      const line = sourceLine({
        url: "https://null-poll.com/feed",
        last_poll_at: null,
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        const cell = document.querySelector('[data-testid="last-poll-https://null-poll.com/feed"]');
        expect(cell?.textContent?.trim()).toBe("\u2014");
      });
    });
  });

  describe("row expansion", () => {
    it("expands detail panel when source URL is clicked", async () => {
      const url = "https://expand.com/feed";
      const line = sourceLine({
        url,
        trust_weight: 0.9,
        poll_interval_minutes: 30,
        added_at: "2026-01-15T10:00:00Z",
        last_poll_at: minutesAgo(10),
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));

      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));

      await waitFor(() => {
        expect(document.querySelector(`[data-testid="detail-panel-${url}"]`)).toBeTruthy();
      });
    });

    it("shows full URL in expanded row", async () => {
      const url = "https://full-url.com/feed.xml";
      const line = sourceLine({ url });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));
      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));

      await waitFor(() => {
        expect(document.querySelector(`[data-testid="detail-panel-${url}"]`)).toBeTruthy();
        // Full URL shown in detail
        const panel = document.querySelector(`[data-testid="detail-panel-${url}"]`);
        expect(panel?.textContent).toContain(url);
      });
    });

    it("shows trust weight in expanded row", async () => {
      const url = "https://trust.com/feed";
      const line = sourceLine({ url, trust_weight: 0.75 });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));
      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));

      await waitFor(() => {
        const panel = document.querySelector(`[data-testid="detail-panel-${url}"]`);
        expect(panel?.textContent).toContain("0.75");
      });
    });

    it("shows poll interval in expanded row", async () => {
      const url = "https://interval.com/feed";
      const line = sourceLine({ url, poll_interval_minutes: 120 });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));
      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));

      await waitFor(() => {
        const panel = document.querySelector(`[data-testid="detail-panel-${url}"]`);
        expect(panel?.textContent).toContain("120");
      });
    });

    it("shows added date in expanded row", async () => {
      const url = "https://added.com/feed";
      const addedAt = "2026-02-20T00:00:00Z";
      const line = sourceLine({ url, added_at: addedAt });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));
      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));

      await waitFor(() => {
        const panel = document.querySelector(`[data-testid="detail-panel-${url}"]`);
        // Added date formatted as a date — check it contains 2026
        expect(panel?.textContent).toMatch(/2026/);
        // Also verify the panel is showing something for the Added field
        expect(panel?.textContent).toContain("Added");
      });
    });

    it("shows absolute last poll timestamp in expanded row", async () => {
      const url = "https://abs-ts.com/feed";
      const absTs = "2026-04-01T08:30:00Z";
      const line = sourceLine({ url, last_poll_at: absTs });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));
      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));

      await waitFor(() => {
        const panel = document.querySelector(`[data-testid="detail-panel-${url}"]`);
        expect(panel?.textContent).toContain(absTs);
      });
    });

    it("collapses detail panel when same source is clicked again", async () => {
      const url = "https://collapse.com/feed";
      const line = sourceLine({ url });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));

      const btn = screen.getByLabelText(`Toggle detail for source ${url}`);
      fireEvent.click(btn);

      await waitFor(() => {
        expect(document.querySelector(`[data-testid="detail-panel-${url}"]`)).toBeTruthy();
      });

      fireEvent.click(btn);

      await waitFor(() => {
        expect(document.querySelector(`[data-testid="detail-panel-${url}"]`)).toBeNull();
      });
    });
  });

  describe("remove action", () => {
    it("shows Remove button in expanded row", async () => {
      const url = "https://remove.com/feed";
      const line = sourceLine({ url });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));
      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));

      await waitFor(() => {
        expect(screen.getByLabelText(`Remove source ${url}`)).toBeTruthy();
      });
    });

    it("shows confirmation prompt when Remove is clicked", async () => {
      const url = "https://remove-confirm.com/feed";
      const line = sourceLine({ url });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));
      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));

      await waitFor(() => screen.getByLabelText(`Remove source ${url}`));
      fireEvent.click(screen.getByLabelText(`Remove source ${url}`));

      await waitFor(() => {
        expect(screen.getByLabelText(`Confirm remove source ${url}`)).toBeTruthy();
      });
    });

    it("calls watch(action=remove) with url after confirmation", async () => {
      const url = "https://remove-call.com/feed";
      const line = sourceLine({ url });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))   // list call
        .mockResolvedValue(makeResult(""));         // remove call

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));
      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));

      await waitFor(() => screen.getByLabelText(`Remove source ${url}`));
      fireEvent.click(screen.getByLabelText(`Remove source ${url}`));

      await waitFor(() => screen.getByLabelText(`Confirm remove source ${url}`));
      fireEvent.click(screen.getByLabelText(`Confirm remove source ${url}`));

      await waitFor(() => {
        const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
        const removeCalls = calls.filter(
          ([name, args]) => name === "distillery_watch" && args?.["action"] === "remove",
        );
        expect(removeCalls).toHaveLength(1);
        const [, args] = removeCalls[0]!;
        expect(args["url"]).toBe(url);
      });
    });

    it("removes source row from table after successful remove", async () => {
      const url = "https://remove-rm.com/feed";
      const line = sourceLine({ url, label: "Source to Remove" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))
        .mockResolvedValue(makeResult(""));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByText("Source to Remove"));

      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));
      await waitFor(() => screen.getByLabelText(`Remove source ${url}`));
      fireEvent.click(screen.getByLabelText(`Remove source ${url}`));
      await waitFor(() => screen.getByLabelText(`Confirm remove source ${url}`));
      fireEvent.click(screen.getByLabelText(`Confirm remove source ${url}`));

      await waitFor(() => {
        expect(screen.queryByText("Source to Remove")).toBeNull();
      });
    });

    it("can cancel remove confirmation", async () => {
      const url = "https://remove-cancel.com/feed";
      const line = sourceLine({ url, label: "Source Cancel" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByText("Source Cancel"));

      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));
      await waitFor(() => screen.getByLabelText(`Remove source ${url}`));
      fireEvent.click(screen.getByLabelText(`Remove source ${url}`));
      await waitFor(() => screen.getByLabelText(`Confirm remove source ${url}`));

      fireEvent.click(screen.getByLabelText(`Cancel remove source ${url}`));

      await waitFor(() => {
        expect(screen.queryByLabelText(`Confirm remove source ${url}`)).toBeNull();
        // Source row should still be visible
        expect(screen.getByText("Source Cancel")).toBeTruthy();
      });
    });

    it("does not call watch(remove) when cancel is clicked", async () => {
      const url = "https://remove-no-call.com/feed";
      const line = sourceLine({ url });
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(line));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText(`Toggle detail for source ${url}`));
      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));
      await waitFor(() => screen.getByLabelText(`Remove source ${url}`));
      fireEvent.click(screen.getByLabelText(`Remove source ${url}`));
      await waitFor(() => screen.getByLabelText(`Confirm remove source ${url}`));
      fireEvent.click(screen.getByLabelText(`Cancel remove source ${url}`));

      const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
      const removeCalls = calls.filter(
        ([name, args]) => name === "distillery_watch" && args?.["action"] === "remove",
      );
      expect(removeCalls).toHaveLength(0);
    });
  });

  describe("empty state", () => {
    it("shows empty state message when no sources configured", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByTestId("empty-state")).toBeTruthy();
        expect(screen.getByText(/No feed sources configured/)).toBeTruthy();
      });
    });

    it("shows navigation link to Capture tab in empty state", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText("Go to Capture tab to add sources")).toBeTruthy();
      });
    });

    it("navigates to Capture tab when empty state link is clicked", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByLabelText("Go to Capture tab to add sources"));

      fireEvent.click(screen.getByLabelText("Go to Capture tab to add sources"));

      // The activeTab store should be updated to "capture"
      let tab: string | undefined;
      const unsub = activeTab.subscribe((v) => { tab = v; });
      unsub();
      expect(tab).toBe("capture");
    });

    it("shows empty state after all sources are removed", async () => {
      const url = "https://last.com/feed";
      const line = sourceLine({ url, label: "Last Source" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))
        .mockResolvedValue(makeResult(""));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => screen.getByText("Last Source"));

      fireEvent.click(screen.getByLabelText(`Toggle detail for source ${url}`));
      await waitFor(() => screen.getByLabelText(`Remove source ${url}`));
      fireEvent.click(screen.getByLabelText(`Remove source ${url}`));
      await waitFor(() => screen.getByLabelText(`Confirm remove source ${url}`));
      fireEvent.click(screen.getByLabelText(`Confirm remove source ${url}`));

      await waitFor(() => {
        expect(screen.getByTestId("empty-state")).toBeTruthy();
      });
    });
  });

  describe("auto-refresh", () => {
    it("re-fetches data when refreshCounter is incremented", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(""));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(SourceHealth, { props: { bridge } });

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledTimes(1);
      });

      refreshCounter.update((n) => n + 1);

      await waitFor(() => {
        expect(mockCallTool.mock.calls.length).toBeGreaterThan(1);
      });
    });
  });
});
