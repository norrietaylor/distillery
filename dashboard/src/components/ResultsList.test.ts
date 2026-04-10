import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import ResultsList from "./ResultsList.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";
import { workingSet, clearWorkingSet } from "$lib/stores";

/** Build a minimal mock ToolCallTextResult. */
function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

/** Build a JSON line representing a search result. */
function resultLine(overrides: Record<string, unknown> = {}): string {
  const entry = {
    id: `id-${Math.random().toString(36).slice(2)}`,
    content: "Test search result content",
    entry_type: "note",
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

// sessionStorage mock for workingSet persistence
const sessionStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

// Suppress Svelte warnings in test output
beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
  vi.stubGlobal("sessionStorage", sessionStorageMock);
  sessionStorageMock.clear();
  clearWorkingSet();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ResultsList", () => {
  describe("rendering", () => {
    it("shows the section heading", () => {
      render(ResultsList, { props: { bridge: null } });
      expect(screen.getByText("Search Results")).toBeTruthy();
    });

    it("shows prompt when no query is given", () => {
      render(ResultsList, { props: { bridge: null, query: "" } });
      expect(screen.getByText(/Enter a query above/)).toBeTruthy();
    });

    it("shows loading skeleton while fetching", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(ResultsList, { props: { bridge, query: "svelte" } });
      expect(screen.getByRole("status")).toBeTruthy();

      // resolve to avoid dangling promise
      resolveCall(makeResult(""));
    });

    it("calls distillery_recall with the query", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(""));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(ResultsList, { props: { bridge, query: "machine learning" } });

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledWith("distillery_recall", expect.objectContaining({
          query: "machine learning",
        }));
      });
    });

    it("renders table rows for each result", async () => {
      const lines = [
        resultLine({ content: "Alpha result item", score: 0.9 }),
        resultLine({ content: "Beta result item", score: 0.6 }),
        resultLine({ content: "Gamma result item", score: 0.3 }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "item" } });

      await waitFor(() => {
        expect(screen.getByText(/Alpha result item/)).toBeTruthy();
        expect(screen.getByText(/Beta result item/)).toBeTruthy();
        expect(screen.getByText(/Gamma result item/)).toBeTruthy();
      });
    });

    it("shows all required column headers", async () => {
      const bridge = makeMockBridge(async () => makeResult(resultLine()));
      render(ResultsList, { props: { bridge, query: "test" } });

      await waitFor(() => {
        expect(screen.getByText("Content")).toBeTruthy();
        expect(screen.getByText("Type")).toBeTruthy();
        expect(screen.getByText(/^Score/)).toBeTruthy();
        expect(screen.getByText("Tags")).toBeTruthy();
        expect(screen.getByText("Date")).toBeTruthy();
      });
    });

    it("shows empty state when no results found", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));
      render(ResultsList, { props: { bridge, query: "nothing" } });

      await waitFor(() => {
        expect(screen.getByText(/No results found/)).toBeTruthy();
      });
    });

    it("shows error banner on tool failure", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult("Internal server error", true),
      );
      render(ResultsList, { props: { bridge, query: "test" } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Internal server error/)).toBeTruthy();
      });
    });

    it("shows error banner on thrown exception", async () => {
      const bridge = makeMockBridge(async () => {
        throw new Error("Network failure");
      });
      render(ResultsList, { props: { bridge, query: "test" } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Network failure/)).toBeTruthy();
      });
    });

    it("shows filter input when results are present", async () => {
      const bridge = makeMockBridge(async () => makeResult(resultLine()));
      render(ResultsList, { props: { bridge, query: "test" } });

      await waitFor(() => {
        expect(screen.getByPlaceholderText("Filter results...")).toBeTruthy();
      });
    });

    it("does not show filter input when there are no results", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));
      render(ResultsList, { props: { bridge, query: "nothing" } });

      await waitFor(() => {
        expect(screen.queryByPlaceholderText("Filter results...")).toBeNull();
      });
    });
  });

  describe("sorting", () => {
    it("sorts by score descending by default (highest score first)", async () => {
      const lines = [
        resultLine({ content: "Low scorer content", score: 0.3 }),
        resultLine({ content: "High scorer content", score: 0.9 }),
        resultLine({ content: "Mid scorer content", score: 0.6 }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "content" } });

      await waitFor(() => screen.getByText("High scorer content"));

      const rows = screen.getAllByRole("row");
      expect(rows.length).toBeGreaterThan(1);
      expect(rows[1]?.textContent).toContain("High scorer content");
    });

    it("allows sorting by Type column", async () => {
      const lines = [
        resultLine({ content: "Z type article", entry_type: "insight" }),
        resultLine({ content: "A type article", entry_type: "bookmark" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "article" } });

      await waitFor(() => screen.getByText("Type"));

      const typeHeader = screen.getByText("Type");
      fireEvent.click(typeHeader);

      await waitFor(() => {
        const rows = screen.getAllByRole("row");
        // After clicking once (desc), "insight" > "bookmark" alphabetically
        expect(rows[1]?.textContent).toContain("Z type article");
      });

      fireEvent.click(typeHeader);

      await waitFor(() => {
        const rows = screen.getAllByRole("row");
        // After clicking twice (asc), "bookmark" < "insight"
        expect(rows[1]?.textContent).toContain("A type article");
      });
    });
  });

  describe("filtering", () => {
    it("filters results by content when user types in filter input", async () => {
      const lines = [
        resultLine({ content: "kubernetes deployment guide" }),
        resultLine({ content: "react hooks tutorial text" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "guide" } });

      await waitFor(() => screen.getByText(/kubernetes deployment/));

      const filterInput = screen.getByPlaceholderText("Filter results...");
      fireEvent.input(filterInput, { target: { value: "kubernetes" } });

      await waitFor(() => {
        expect(screen.getByText(/kubernetes deployment/)).toBeTruthy();
        expect(screen.queryByText(/react hooks tutorial/)).toBeNull();
      });
    });

    it("filters results by entry_type", async () => {
      const lines = [
        resultLine({ content: "First article text", entry_type: "note" }),
        resultLine({ content: "Second article text", entry_type: "bookmark" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "article" } });

      await waitFor(() => screen.getByText(/First article text/));

      const filterInput = screen.getByPlaceholderText("Filter results...");
      fireEvent.input(filterInput, { target: { value: "note" } });

      await waitFor(() => {
        expect(screen.getByText(/First article text/)).toBeTruthy();
        expect(screen.queryByText(/Second article text/)).toBeNull();
      });
    });

    it("filters results by source", async () => {
      const lines = [
        resultLine({ content: "Article from alpha org", source: "github.com/alpha" }),
        resultLine({ content: "Article from rss feed", source: "rss.example.com" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "article" } });

      await waitFor(() => screen.getByText(/Article from alpha/));

      const filterInput = screen.getByPlaceholderText("Filter results...");
      fireEvent.input(filterInput, { target: { value: "alpha" } });

      await waitFor(() => {
        expect(screen.getByText(/Article from alpha/)).toBeTruthy();
        expect(screen.queryByText(/Article from rss/)).toBeNull();
      });
    });

    it("shows all results when filter is cleared", async () => {
      const lines = [
        resultLine({ content: "AAAA unique content" }),
        resultLine({ content: "BBBB unique content" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "content" } });

      await waitFor(() => screen.getByText(/AAAA unique/));

      const filterInput = screen.getByPlaceholderText("Filter results...");
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
      const line = resultLine({ content: "Full detail content here", source: "test.com" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ResultsList, { props: { bridge, query: "detail" } });

      await waitFor(() => screen.getByText(/Full detail content here/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);

      await waitFor(() => {
        expect(screen.getByLabelText("Result detail")).toBeTruthy();
      });
    });

    it("collapses the detail panel when the same row is clicked again", async () => {
      const line = resultLine({ content: "Toggle panel content" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ResultsList, { props: { bridge, query: "toggle" } });

      await waitFor(() => screen.getByText(/Toggle panel content/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);
      await waitFor(() => screen.getByLabelText("Result detail"));

      fireEvent.click(dataRow);
      await waitFor(() => {
        expect(screen.queryByLabelText("Result detail")).toBeNull();
      });
    });

    it("shows close button in detail panel", async () => {
      const line = resultLine({ content: "Closeable panel detail" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ResultsList, { props: { bridge, query: "close" } });

      await waitFor(() => screen.getByText(/Closeable panel detail/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);
      await waitFor(() => screen.getByLabelText("Close detail panel"));

      fireEvent.click(screen.getByLabelText("Close detail panel"));
      await waitFor(() => {
        expect(screen.queryByLabelText("Result detail")).toBeNull();
      });
    });

    it("shows tags in the detail panel", async () => {
      const line = resultLine({ content: "Tagged entry", tags: ["alpha", "beta", "gamma"] });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ResultsList, { props: { bridge, query: "tagged" } });

      await waitFor(() => screen.getByText(/Tagged entry/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);

      await waitFor(() => {
        expect(screen.getByLabelText("Result detail")).toBeTruthy();
        // Tags appear in the table row as comma-separated text AND in the detail panel
        const allAlphaMatches = screen.getAllByText(/alpha/);
        expect(allAlphaMatches.length).toBeGreaterThan(0);
      });
    });

    it("shows entry_type badge in the detail panel", async () => {
      const line = resultLine({ content: "Typed entry", entry_type: "insight" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ResultsList, { props: { bridge, query: "typed" } });

      await waitFor(() => screen.getByText(/Typed entry/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);

      await waitFor(() => {
        expect(screen.getByLabelText("Result detail")).toBeTruthy();
        // entry_type appears both in table cell and detail panel
        const insightMatches = screen.getAllByText("insight");
        expect(insightMatches.length).toBeGreaterThan(0);
      });
    });
  });

  describe("pagination", () => {
    function makeNResults(n: number): string {
      return Array.from({ length: n }, (_, i) =>
        resultLine({
          id: `pg-${i}`,
          content: `Paginated result number ${String(i + 1).padStart(3, "0")}`,
          score: 1 - i * 0.01,
        }),
      ).join("\n");
    }

    it("does not show pagination controls for 20 or fewer results", async () => {
      const lines = makeNResults(10);
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "paginated" } });

      await waitFor(() => screen.getByText(/Paginated result number 001/));
      expect(screen.queryByLabelText("Pagination")).toBeNull();
    });

    it("shows pagination controls for more than 20 results", async () => {
      const lines = makeNResults(25);
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "paginated" } });

      await waitFor(() => screen.getByRole("navigation", { name: "Pagination" }));
      expect(screen.getByLabelText("Next page")).toBeTruthy();
    });

    it("displays only 20 rows on the first page when 25 results exist", async () => {
      const lines = makeNResults(25);
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "paginated" } });

      await waitFor(() => screen.getByText(/Paginated result number 001/));

      const dataRows = screen.getAllByRole("row").slice(1);
      expect(dataRows).toHaveLength(20);
    });

    it("navigates to the next page when Next is clicked", async () => {
      const lines = makeNResults(25);
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "paginated" } });

      await waitFor(() => screen.getByLabelText("Next page"));
      fireEvent.click(screen.getByLabelText("Next page"));

      await waitFor(() => {
        expect(screen.getByText(/Paginated result number 021/)).toBeTruthy();
      });
    });
  });

  describe("score badge colors", () => {
    it("renders score values in the table cells", async () => {
      const lines = [
        resultLine({ id: "sc-a", content: "High relevance item", score: 0.85 }),
        resultLine({ id: "sc-b", content: "Medium relevance item", score: 0.65 }),
        resultLine({ id: "sc-c", content: "Low relevance item", score: 0.4 }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "relevance" } });

      await waitFor(() => screen.getByText(/High relevance item/));

      expect(screen.getByText("0.85")).toBeTruthy();
      expect(screen.getByText("0.65")).toBeTruthy();
      expect(screen.getByText("0.40")).toBeTruthy();
    });
  });

  describe("no bridge", () => {
    it("renders without crashing when bridge is null", () => {
      expect(() => render(ResultsList, { props: { bridge: null } })).not.toThrow();
    });

    it("shows section heading even without bridge", () => {
      render(ResultsList, { props: { bridge: null } });
      expect(screen.getByText("Search Results")).toBeTruthy();
    });

    it("shows prompt state when bridge is null and query is provided", () => {
      render(ResultsList, { props: { bridge: null, query: "test" } });
      // With no connected bridge, results stay empty and query is not empty
      // Component will try to search but skip since bridge is null
      expect(screen.getByText("Search Results")).toBeTruthy();
    });
  });

  describe("JSON parsing", () => {
    it("parses a JSON array response", async () => {
      const entries = [
        { id: "arr-1", content: "Array entry one", entry_type: "note", source: "src", score: 0.8, tags: [], created_at: "" },
        { id: "arr-2", content: "Array entry two", entry_type: "note", source: "src", score: 0.7, tags: [], created_at: "" },
      ];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(entries)));
      render(ResultsList, { props: { bridge, query: "array" } });

      await waitFor(() => {
        expect(screen.getByText(/Array entry one/)).toBeTruthy();
        expect(screen.getByText(/Array entry two/)).toBeTruthy();
      });
    });

    it("handles missing optional fields gracefully", async () => {
      const minimal = JSON.stringify({ id: "min-1", content: "Minimal result entry" });
      const bridge = makeMockBridge(async () => makeResult(minimal));
      render(ResultsList, { props: { bridge, query: "minimal" } });

      await waitFor(() => {
        expect(screen.getByText(/Minimal result entry/)).toBeTruthy();
      });
    });

    it("skips unparseable lines", async () => {
      const mixed = [
        "not valid json at all",
        resultLine({ content: "Valid result entry here" }),
        "also not json",
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(mixed));
      render(ResultsList, { props: { bridge, query: "valid" } });

      await waitFor(() => {
        expect(screen.getByText(/Valid result entry here/)).toBeTruthy();
      });
    });
  });

  // ---------------------------------------------------------------------------
  // Pin buttons
  // ---------------------------------------------------------------------------

  describe("pin buttons", () => {
    it("renders a Pin button for each result row", async () => {
      const lines = [
        resultLine({ id: "pin-row-1", content: "Pinnable result one" }),
        resultLine({ id: "pin-row-2", content: "Pinnable result two" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ResultsList, { props: { bridge, query: "pinnable" } });

      await waitFor(() => screen.getByText(/Pinnable result one/));

      const pinBtns = screen.getAllByRole("button", { name: /^Pin / });
      expect(pinBtns.length).toBeGreaterThanOrEqual(2);
    });

    it("pins an entry when Pin button is clicked", async () => {
      const line = resultLine({ id: "row-pin-test", content: "Row pin test content" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ResultsList, { props: { bridge, query: "row pin" } });

      await waitFor(() => screen.getByText(/Row pin test content/));

      const pinBtn = screen.getByRole("button", { name: /^Pin Row pin test/ });
      fireEvent.click(pinBtn);

      await waitFor(() => {
        const ws = get(workingSet);
        expect(ws.some((e) => e.id === "row-pin-test")).toBe(true);
      });
    });

    it("shows Unpin button after pinning", async () => {
      const line = resultLine({ id: "row-unpin-test", content: "Row unpin test content" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ResultsList, { props: { bridge, query: "row unpin" } });

      await waitFor(() => screen.getByText(/Row unpin test content/));

      const pinBtn = screen.getByRole("button", { name: /^Pin Row unpin test/ });
      fireEvent.click(pinBtn);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /^Unpin Row unpin test/ })).toBeTruthy();
      });
    });

    it("shows a pin button in the expanded detail panel", async () => {
      const line = resultLine({ id: "detail-pin-test", content: "Detail panel pin content" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ResultsList, { props: { bridge, query: "detail pin" } });

      await waitFor(() => screen.getByText(/Detail panel pin content/));

      const dataRow = screen.getAllByRole("row")[1]!;
      fireEvent.click(dataRow);

      await waitFor(() => {
        expect(screen.getByLabelText("Pin entry")).toBeTruthy();
      });
    });
  });
});
