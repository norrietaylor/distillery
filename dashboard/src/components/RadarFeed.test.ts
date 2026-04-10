import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import RadarFeed from "./RadarFeed.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";

/** Build a minimal mock ToolCallTextResult. */
function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

/** Build a JSON line representing a feed entry. */
function entryLine(overrides: Record<string, unknown> = {}): string {
  const entry = {
    id: `id-${Math.random().toString(36).slice(2)}`,
    content: "Test feed entry content",
    source: "github.com/example",
    score: 0.75,
    created_at: "2026-04-01T12:00:00Z",
    tags: ["typescript", "svelte"],
    ...overrides,
  };
  return JSON.stringify(entry);
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

describe("RadarFeed", () => {
  describe("rendering", () => {
    it("shows loading skeleton while fetching", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(RadarFeed, { props: { bridge } });
      expect(screen.getByRole("status")).toBeTruthy();

      // resolve to avoid dangling promise
      resolveCall(makeResult(""));
    });

    it("shows the section heading", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));
      render(RadarFeed, { props: { bridge } });
      await waitFor(() => {
        expect(screen.getByText("Radar Feed")).toBeTruthy();
      });
    });

    it("shows filter input", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));
      render(RadarFeed, { props: { bridge } });
      await waitFor(() => {
        expect(screen.getByPlaceholderText("Filter entries...")).toBeTruthy();
      });
    });

    it("renders table rows for each feed entry", async () => {
      const lines = [
        entryLine({ content: "Alpha entry item", score: 0.9 }),
        entryLine({ content: "Beta entry item", score: 0.6 }),
        entryLine({ content: "Gamma entry item", score: 0.3 }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/Alpha entry item/)).toBeTruthy();
        expect(screen.getByText(/Beta entry item/)).toBeTruthy();
        expect(screen.getByText(/Gamma entry item/)).toBeTruthy();
      });
    });

    it("shows all required column headers", async () => {
      const bridge = makeMockBridge(async () => makeResult(entryLine()));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("Title")).toBeTruthy();
        expect(screen.getByText("Source")).toBeTruthy();
        // Score header includes sort indicator arrow when it is the default sort column
        expect(screen.getByText(/^Score/)).toBeTruthy();
        expect(screen.getByText("Published Date")).toBeTruthy();
        expect(screen.getByText("Tags")).toBeTruthy();
      });
    });

    it("shows empty state when no entries found", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/No radar feed entries found/)).toBeTruthy();
      });
    });

    it("shows error banner on tool failure", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult("Internal server error", true),
      );
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Internal server error/)).toBeTruthy();
      });
    });

    it("shows error banner on thrown exception", async () => {
      const bridge = makeMockBridge(async () => {
        throw new Error("Network failure");
      });
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Network failure/)).toBeTruthy();
      });
    });
  });

  describe("sorting", () => {
    it("sorts by score descending by default (highest score first)", async () => {
      const lines = [
        entryLine({ content: "Low scorer content", score: 0.3 }),
        entryLine({ content: "High scorer content", score: 0.9 }),
        entryLine({ content: "Mid scorer content", score: 0.6 }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText("High scorer content"));

      // rows[0] is the header row; data rows follow
      const rows = screen.getAllByRole("row");
      expect(rows.length).toBeGreaterThan(1);
      expect(rows[1]?.textContent).toContain("High scorer content");
    });

    it("allows sorting by Published Date column", async () => {
      const lines = [
        entryLine({ content: "Newer article", score: 0.5, created_at: "2026-04-09T00:00:00Z" }),
        entryLine({ content: "Older article", score: 0.5, created_at: "2026-03-01T00:00:00Z" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText("Newer article"));

      const dateHeader = screen.getByText("Published Date");
      // First click: sort by date descending (newest first)
      fireEvent.click(dateHeader);

      await waitFor(() => {
        const rows = screen.getAllByRole("row");
        expect(rows[1]?.textContent).toContain("Newer article");
      });

      // Second click: sort by date ascending (oldest first)
      fireEvent.click(dateHeader);

      await waitFor(() => {
        const rows = screen.getAllByRole("row");
        expect(rows[1]?.textContent).toContain("Older article");
      });
    });
  });

  describe("filtering", () => {
    it("filters entries by content when user types in the filter input", async () => {
      const lines = [
        entryLine({ content: "kubernetes deployment guide" }),
        entryLine({ content: "react hooks tutorial text" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/kubernetes deployment/));

      const filterInput = screen.getByPlaceholderText("Filter entries...");
      fireEvent.input(filterInput, { target: { value: "kubernetes" } });

      await waitFor(() => {
        expect(screen.getByText(/kubernetes deployment/)).toBeTruthy();
        expect(screen.queryByText(/react hooks tutorial/)).toBeNull();
      });
    });

    it("filters entries by source", async () => {
      const lines = [
        entryLine({ content: "Article from alpha org", source: "github.com/alpha" }),
        entryLine({ content: "Article from rss feed", source: "rss.example.com" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/Article from alpha/));

      const filterInput = screen.getByPlaceholderText("Filter entries...");
      fireEvent.input(filterInput, { target: { value: "alpha" } });

      await waitFor(() => {
        expect(screen.getByText(/Article from alpha/)).toBeTruthy();
        expect(screen.queryByText(/Article from rss/)).toBeNull();
      });
    });

    it("shows all entries when filter is cleared", async () => {
      const lines = [
        entryLine({ content: "AAAA unique content" }),
        entryLine({ content: "BBBB unique content" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/AAAA unique/));

      const filterInput = screen.getByPlaceholderText("Filter entries...");
      fireEvent.input(filterInput, { target: { value: "AAAA" } });
      await waitFor(() => expect(screen.queryByText(/BBBB unique/)).toBeNull());

      fireEvent.input(filterInput, { target: { value: "" } });
      await waitFor(() => {
        expect(screen.getByText(/AAAA unique/)).toBeTruthy();
        expect(screen.getByText(/BBBB unique/)).toBeTruthy();
      });
    });
  });

  describe("row expand detail panel", () => {
    it("expands a detail panel when a row is clicked", async () => {
      const line = entryLine({ content: "Full detail content here", source: "test.com" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/Full detail content here/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);

      await waitFor(() => {
        expect(screen.getByLabelText("Entry detail")).toBeTruthy();
        expect(screen.getByLabelText("Bookmark this entry")).toBeTruthy();
      });
    });

    it("collapses the detail panel when the same row is clicked again", async () => {
      const line = entryLine({ content: "Toggle panel content" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/Toggle panel content/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);
      await waitFor(() => screen.getByLabelText("Entry detail"));

      fireEvent.click(dataRow);
      await waitFor(() => {
        expect(screen.queryByLabelText("Entry detail")).toBeNull();
      });
    });

    it("shows close button in detail panel", async () => {
      const line = entryLine({ content: "Closeable panel detail" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/Closeable panel detail/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);
      await waitFor(() => screen.getByLabelText("Close detail panel"));

      fireEvent.click(screen.getByLabelText("Close detail panel"));
      await waitFor(() => {
        expect(screen.queryByLabelText("Entry detail")).toBeNull();
      });
    });
  });

  describe("bookmark action", () => {
    it("calls distillery_store when Bookmark button is clicked", async () => {
      // The mock needs to return data on the first (list) call
      const feedLine = entryLine({ id: "bm-1", content: "Entry to bookmark now" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(feedLine)) // first call: distillery_list
        .mockResolvedValue(makeResult(""));          // subsequent calls: distillery_store

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry to bookmark now/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);
      await waitFor(() => screen.getByLabelText("Bookmark this entry"));

      fireEvent.click(screen.getByLabelText("Bookmark this entry"));

      await waitFor(() => {
        const allCalls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
        const storeCalls = allCalls.filter(([name]) => name === "distillery_store");
        expect(storeCalls).toHaveLength(1);
        const [, args] = storeCalls[0]!;
        expect(args["content"]).toBe("Entry to bookmark now");
        expect(args["entry_type"]).toBe("bookmark");
      });
    });

    it("shows success confirmation after successful bookmark", async () => {
      const feedLine = entryLine({ id: "bm-2", content: "Entry for success test" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(feedLine))
        .mockResolvedValue(makeResult(""));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry for success test/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);
      await waitFor(() => screen.getByLabelText("Bookmark this entry"));

      fireEvent.click(screen.getByLabelText("Bookmark this entry"));

      await waitFor(() => {
        expect(screen.getByText("Bookmarked!")).toBeTruthy();
      });
    });

    it("shows error state after failed bookmark", async () => {
      const feedLine = entryLine({ id: "bm-3", content: "Entry for error test" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(feedLine))           // list call
        .mockResolvedValueOnce(makeResult("Tool error", true)); // store call fails

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry for error test/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);
      await waitFor(() => screen.getByLabelText("Bookmark this entry"));

      fireEvent.click(screen.getByLabelText("Bookmark this entry"));

      await waitFor(() => {
        expect(screen.getByText(/Bookmark failed/)).toBeTruthy();
      });
    });
  });

  describe("pagination", () => {
    function makeNEntries(n: number): string {
      return Array.from({ length: n }, (_, i) =>
        entryLine({
          id: `pg-${i}`,
          content: `Paginated item number ${String(i + 1).padStart(3, "0")}`,
          score: 1 - i * 0.01,
        }),
      ).join("\n");
    }

    it("does not show pagination controls for 20 or fewer entries", async () => {
      const lines = makeNEntries(10);
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/Paginated item number 001/));
      expect(screen.queryByLabelText("Pagination")).toBeNull();
    });

    it("shows pagination controls for more than 20 entries", async () => {
      const lines = makeNEntries(25);
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByRole("navigation", { name: "Pagination" }));
      expect(screen.getByLabelText("Next page")).toBeTruthy();
    });

    it("displays only 20 rows on the first page when 25 entries exist", async () => {
      const lines = makeNEntries(25);
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/Paginated item number 001/));

      // rows includes header row — expect 20 data rows
      const dataRows = screen.getAllByRole("row").slice(1);
      expect(dataRows).toHaveLength(20);
    });

    it("navigates to the next page when Next is clicked", async () => {
      const lines = makeNEntries(25);
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByLabelText("Next page"));
      fireEvent.click(screen.getByLabelText("Next page"));

      await waitFor(() => {
        // On page 2, expect item 21 visible (padded: "021")
        expect(screen.getByText(/Paginated item number 021/)).toBeTruthy();
      });
    });
  });

  describe("score badge colors", () => {
    it("renders score values in the table cells", async () => {
      const lines = [
        entryLine({ id: "sc-a", content: "High relevance item", score: 0.85 }),
        entryLine({ id: "sc-b", content: "Medium relevance item", score: 0.65 }),
        entryLine({ id: "sc-c", content: "Low relevance item", score: 0.4 }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(RadarFeed, { props: { bridge } });

      await waitFor(() => screen.getByText(/High relevance item/));

      // Score values should appear in the table (formatted to 2 decimal places)
      expect(screen.getByText("0.85")).toBeTruthy();
      expect(screen.getByText("0.65")).toBeTruthy();
      expect(screen.getByText("0.40")).toBeTruthy();
    });
  });

  describe("no bridge", () => {
    it("renders without crashing when bridge is null", () => {
      expect(() => render(RadarFeed, { props: { bridge: null } })).not.toThrow();
    });

    it("shows section heading even without bridge", () => {
      render(RadarFeed, { props: { bridge: null } });
      expect(screen.getByText("Radar Feed")).toBeTruthy();
    });
  });
});
