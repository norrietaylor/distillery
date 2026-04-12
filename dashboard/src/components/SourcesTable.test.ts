import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import SourcesTable from "./SourcesTable.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";

/** Build a minimal mock ToolCallTextResult. */
function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

function makeSources(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    url: `https://feed${i + 1}.example.com/feed.xml`,
    source_type: i % 2 === 0 ? "rss" : "github",
    label: `Feed ${i + 1}`,
    trust_weight: 0.8,
    poll_interval: "1h",
    added_at: "2026-01-01T00:00:00Z",
  }));
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

describe("SourcesTable", () => {
  describe("table loading", () => {
    it("calls watch list on mount", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(JSON.stringify([])));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledWith("distillery_watch", { action: "list" });
      });
    });

    it("renders the Current Sources heading", async () => {
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify([])));
      render(SourcesTable, { props: { bridge } });
      expect(screen.getByText("Current Sources")).toBeTruthy();
    });

    it("reloads when refreshToken changes", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(JSON.stringify([])));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      const { rerender } = render(SourcesTable, { props: { bridge, refreshToken: 0 } });

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledTimes(1);
      });

      await rerender({ bridge, refreshToken: 1 });

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledTimes(2);
      });
    });
  });

  describe("table rendering", () => {
    it("renders rows for returned sources", async () => {
      const sources = makeSources(2);
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("feed1.example.com/feed.xml", { exact: false })).toBeTruthy();
        expect(screen.getByText("feed2.example.com/feed.xml", { exact: false })).toBeTruthy();
      });
    });

    it("renders Source, Type, Label, Trust Weight, Poll Interval, Added Date columns", async () => {
      const sources = makeSources(1);
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("Source")).toBeTruthy();
        expect(screen.getByText("Type")).toBeTruthy();
        expect(screen.getByText("Label")).toBeTruthy();
        expect(screen.getByText("Trust Weight")).toBeTruthy();
        expect(screen.getByText("Poll Interval")).toBeTruthy();
        // "Added Date" column header may include sort arrow suffix
        expect(screen.getByText(/Added Date/)).toBeTruthy();
      });
    });

    it("displays source type as uppercase badge text", async () => {
      const sources = [
        {
          url: "https://rss-feed.example.com/feed.xml",
          source_type: "rss",
          label: "RSS Feed",
          trust_weight: 1.0,
        },
        {
          url: "https://github.com/example/repo",
          source_type: "github",
          label: "GitHub Repo",
          trust_weight: 0.9,
        },
      ];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("RSS")).toBeTruthy();
        expect(screen.getByText("GITHUB")).toBeTruthy();
      });
    });

    it("displays trust weight as one decimal number", async () => {
      const sources = [
        {
          url: "https://example.com/feed.xml",
          source_type: "rss",
          label: "Test",
          trust_weight: 0.7,
        },
      ];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("0.7")).toBeTruthy();
      });
    });

    it("truncates long URLs in the Source column", async () => {
      const longUrl =
        "https://very-long-domain.example.com/extremely/deep/nested/path/to/feed.xml";
      const sources = [
        { url: longUrl, source_type: "rss", label: "Long URL Feed", trust_weight: 1.0 },
      ];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        // The truncated cell should show a shortened version ending with ellipsis
        expect(screen.getByText(/…$/)).toBeTruthy();
        // The full URL should not appear as plain cell text (only after expansion in detail row)
        const exactMatches = screen.queryAllByText(longUrl, { exact: true });
        expect(exactMatches.length).toBe(0);
      });
    });
  });

  describe("empty state", () => {
    it("shows empty state message when no sources exist", async () => {
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify([])));

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        expect(
          screen.getByText("No sources configured. Add an RSS feed or GitHub repo above."),
        ).toBeTruthy();
      });
    });

    it("does not show empty state when sources exist", async () => {
      const sources = makeSources(1);
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        expect(
          screen.queryByText("No sources configured. Add an RSS feed or GitHub repo above."),
        ).toBeNull();
      });
    });
  });

  describe("row expansion", () => {
    /** Find the first clickable data row (excludes the header row). */
    async function findFirstDataRow() {
      // Wait for data rows to appear
      await waitFor(() => {
        const clickableRows = document
          .querySelectorAll("tr.datatable-row");
        expect(clickableRows.length).toBeGreaterThan(0);
      });
      return document.querySelector("tr.datatable-row") as HTMLElement;
    }

    it("expands detail row when a row is clicked", async () => {
      const sources = makeSources(1);
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        expect(screen.queryByTestId("detail-row")).toBeNull();
      });

      const row = await findFirstDataRow();
      fireEvent.click(row);

      await waitFor(() => {
        expect(screen.getByTestId("detail-row")).toBeTruthy();
      });
    });

    it("shows full URL in expanded detail row", async () => {
      const fullUrl = "https://feed1.example.com/feed.xml";
      const sources = [{ url: fullUrl, source_type: "rss", label: "Feed 1", trust_weight: 1.0 }];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      const row = await findFirstDataRow();
      fireEvent.click(row);

      await waitFor(() => {
        const detailRow = screen.getByTestId("detail-row");
        expect(detailRow.textContent).toContain(fullUrl);
      });
    });

    it("shows Remove button in expanded detail row", async () => {
      const sources = makeSources(1);
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      const row = await findFirstDataRow();
      fireEvent.click(row);

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Remove source/i })).toBeTruthy();
      });
    });

    it("collapses detail row when same row is clicked again", async () => {
      const sources = makeSources(1);
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      const row = await findFirstDataRow();
      fireEvent.click(row);

      await waitFor(() => {
        expect(screen.getByTestId("detail-row")).toBeTruthy();
      });

      fireEvent.click(row);

      await waitFor(() => {
        expect(screen.queryByTestId("detail-row")).toBeNull();
      });
    });
  });

  describe("remove source", () => {
    /** Find the first clickable data row. */
    async function findFirstDataRow() {
      await waitFor(() => {
        expect(document.querySelectorAll("tr.datatable-row").length).toBeGreaterThan(0);
      });
      return document.querySelector("tr.datatable-row") as HTMLElement;
    }

    it("shows confirmation dialog when Remove is clicked", async () => {
      const sources = makeSources(1);
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      const row = await findFirstDataRow();
      fireEvent.click(row);

      const removeBtn = await screen.findByRole("button", { name: /Remove source/i });
      fireEvent.click(removeBtn);

      await waitFor(() => {
        expect(
          screen.getByText("Remove this source? Feed items already stored will remain."),
        ).toBeTruthy();
      });
    });

    it("calls watch remove with correct URL when confirmed", async () => {
      const sourceUrl = "https://feed1.example.com/feed.xml";
      const sources = [{ url: sourceUrl, source_type: "rss", label: "Feed 1", trust_weight: 1.0 }];

      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(JSON.stringify(sources))) // list
        .mockResolvedValueOnce(makeResult("")); // remove

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SourcesTable, { props: { bridge } });

      const row = await findFirstDataRow();
      fireEvent.click(row);

      const removeBtn = await screen.findByRole("button", { name: /Remove source/i });
      fireEvent.click(removeBtn);

      const confirmBtn = await screen.findByRole("button", { name: /Confirm remove/i });
      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledWith("distillery_watch", {
          action: "remove",
          url: sourceUrl,
        });
      });
    });

    it("removes row immediately (optimistic) on confirm", async () => {
      const sources = makeSources(3);
      const removeUrl = sources[0]!.url;

      let resolveRemove!: (v: ToolCallTextResult) => void;
      const pendingRemove = new Promise<ToolCallTextResult>((res) => {
        resolveRemove = res;
      });

      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(JSON.stringify(sources))) // list
        .mockReturnValueOnce(pendingRemove); // remove — still in flight

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SourcesTable, { props: { bridge } });

      // Wait for 3 rows
      await waitFor(() => {
        const rows = screen.getAllByRole("row");
        // thead row + 3 data rows
        expect(rows.length).toBeGreaterThanOrEqual(4);
      });

      // Expand first row
      const dataRows = screen.getAllByRole("row").filter((r) => r.className.includes("datatable-row"));
      fireEvent.click(dataRows[0]!);

      const removeBtn = await screen.findByRole("button", { name: /Remove source/i });
      fireEvent.click(removeBtn);

      const confirmBtn = await screen.findByRole("button", { name: /Confirm remove/i });
      fireEvent.click(confirmBtn);

      // Optimistic removal: 2 data rows remain
      await waitFor(() => {
        const remaining = screen.getAllByRole("row").filter((r) =>
          r.className.includes("datatable-row"),
        );
        expect(remaining.length).toBe(2);
      });

      // Cleanup — resolve the pending remove
      resolveRemove(makeResult(""));
    });

    it("rolls back row on failed removal", async () => {
      const sources = makeSources(2);
      const removeUrl = sources[0]!.url;

      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(JSON.stringify(sources))) // list
        .mockResolvedValueOnce(makeResult("Internal error", true)); // remove fails

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        const rows = screen.getAllByRole("row").filter((r) => r.className.includes("datatable-row"));
        expect(rows.length).toBe(2);
      });

      const dataRows = screen.getAllByRole("row").filter((r) => r.className.includes("datatable-row"));
      fireEvent.click(dataRows[0]!);

      const removeBtn = await screen.findByRole("button", { name: /Remove source/i });
      fireEvent.click(removeBtn);

      const confirmBtn = await screen.findByRole("button", { name: /Confirm remove/i });
      fireEvent.click(confirmBtn);

      // After rollback, both rows should be back
      await waitFor(() => {
        const remaining = screen.getAllByRole("row").filter((r) =>
          r.className.includes("datatable-row"),
        );
        expect(remaining.length).toBe(2);
      });

      // Error message should be shown
      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
      });
    });

    it("keeps source when cancel is clicked", async () => {
      const sources = makeSources(1);
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(sources)));

      render(SourcesTable, { props: { bridge } });

      const row = await findFirstDataRow();
      fireEvent.click(row);

      const removeBtn = await screen.findByRole("button", { name: /Remove source/i });
      fireEvent.click(removeBtn);

      const cancelBtn = await screen.findByRole("button", { name: /Cancel remove/i });
      fireEvent.click(cancelBtn);

      await waitFor(() => {
        // Confirmation dialog gone
        expect(
          screen.queryByText("Remove this source? Feed items already stored will remain."),
        ).toBeNull();
        // Row still there — use getAllByText since URL can appear in table + detail row
        const urlMatches = screen.getAllByText("https://feed1.example.com/feed.xml", { exact: false });
        expect(urlMatches.length).toBeGreaterThan(0);
      });
    });

    it("does not call watch remove when cancel is clicked", async () => {
      const sources = makeSources(1);
      const mockCallTool = vi
        .fn()
        .mockResolvedValue(makeResult(JSON.stringify(sources)));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SourcesTable, { props: { bridge } });

      const row = await findFirstDataRow();
      fireEvent.click(row);

      const removeBtn = await screen.findByRole("button", { name: /Remove source/i });
      fireEvent.click(removeBtn);

      const cancelBtn = await screen.findByRole("button", { name: /Cancel remove/i });
      fireEvent.click(cancelBtn);

      await waitFor(() => {
        // Only the initial list call — no remove call
        const removeCalls = mockCallTool.mock.calls.filter(
          ([, args]) => (args as Record<string, unknown>)["action"] === "remove",
        );
        expect(removeCalls.length).toBe(0);
      });
    });
  });

  describe("null bridge", () => {
    it("renders without crashing when bridge is null", () => {
      expect(() => render(SourcesTable, { props: { bridge: null } })).not.toThrow();
    });

    it("shows Current Sources heading even without bridge", () => {
      render(SourcesTable, { props: { bridge: null } });
      expect(screen.getByText("Current Sources")).toBeTruthy();
    });

    it("shows empty state when bridge is null", () => {
      render(SourcesTable, { props: { bridge: null } });
      expect(
        screen.getByText("No sources configured. Add an RSS feed or GitHub repo above."),
      ).toBeTruthy();
    });
  });

  describe("error handling", () => {
    it("shows error banner when list call returns isError", async () => {
      const bridge = makeMockBridge(async () => makeResult("Server error", true));

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Server error/)).toBeTruthy();
      });
    });

    it("shows error banner when list call throws", async () => {
      const bridge = makeMockBridge(async () => {
        throw new Error("Network failure");
      });

      render(SourcesTable, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Network failure/)).toBeTruthy();
      });
    });
  });
});
