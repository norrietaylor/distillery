import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import ReviewQueue from "./ReviewQueue.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";
import { currentUser } from "$lib/stores";

/** Build a minimal mock ToolCallTextResult. */
function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

/** Build a JSON line representing a review queue entry. */
function entryLine(overrides: Record<string, unknown> = {}): string {
  const entry = {
    id: `id-${Math.random().toString(36).slice(2)}`,
    content: "Test review entry content that is fairly long and descriptive",
    entry_type: "note",
    confidence: 0.55,
    classified_at: "2026-04-01T12:00:00Z",
    reasoning: "Classified by classifier v2",
    suggested_project: null,
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
  currentUser.set({ login: "test-user", displayName: "Test User" });
});

describe("ReviewQueue", () => {
  describe("table rendering", () => {
    it("renders all required column headers", async () => {
      const line = entryLine();
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("Preview")).toBeTruthy();
        expect(screen.getByText("Type")).toBeTruthy();
        expect(screen.getByText("Confidence")).toBeTruthy();
        expect(screen.getByText("Classified At")).toBeTruthy();
        expect(screen.getByText("Actions")).toBeTruthy();
      });
    });

    it("renders a row for each entry", async () => {
      const lines = [
        entryLine({ id: "e1", content: "First entry content here" }),
        entryLine({ id: "e2", content: "Second entry content here" }),
        entryLine({ id: "e3", content: "Third entry content here" }),
      ].join("\n");
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/First entry content/)).toBeTruthy();
        expect(screen.getByText(/Second entry content/)).toBeTruthy();
        expect(screen.getByText(/Third entry content/)).toBeTruthy();
      });
    });

    it("truncates preview to 80 chars", async () => {
      const longContent = "A".repeat(100);
      const line = entryLine({ id: "long-1", content: longContent });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        // 80 chars + ellipsis
        const preview = "A".repeat(80) + "\u2026";
        expect(screen.getByText(preview)).toBeTruthy();
      });
    });

    it("displays entry type", async () => {
      const line = entryLine({ id: "type-1", entry_type: "session" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("session")).toBeTruthy();
      });
    });

    it("shows loading skeleton while fetching", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(ReviewQueue, { props: { bridge } });
      expect(screen.getByRole("status")).toBeTruthy();

      resolveCall(makeResult(""));
    });

    it("shows error banner on tool failure", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult("Internal server error", true),
      );
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Internal server error/)).toBeTruthy();
      });
    });

    it("shows error banner on thrown exception", async () => {
      const bridge = makeMockBridge(async () => {
        throw new Error("Network failure");
      });
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Network failure/)).toBeTruthy();
      });
    });
  });

  describe("confidence badge colors", () => {
    it("renders confidence badge with red tier for confidence < 0.4", async () => {
      const line = entryLine({ id: "conf-low", confidence: 0.25 });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        // There may be multiple badges (header row vs cell) — find the one with data-tier
        const badges = document.querySelectorAll('[data-tier="red"]');
        expect(badges.length).toBeGreaterThan(0);
      });
    });

    it("renders confidence badge with yellow tier for confidence between 0.4 and 0.7", async () => {
      const line = entryLine({ id: "conf-mid", confidence: 0.55 });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        const badges = document.querySelectorAll('[data-tier="yellow"]');
        expect(badges.length).toBeGreaterThan(0);
      });
    });

    it("renders confidence badge with green tier for confidence > 0.7", async () => {
      const line = entryLine({ id: "conf-high", confidence: 0.85 });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        const badges = document.querySelectorAll('[data-tier="green"]');
        expect(badges.length).toBeGreaterThan(0);
      });
    });

    it("displays confidence value formatted to 2 decimal places", async () => {
      const line = entryLine({ id: "conf-fmt", confidence: 0.378 });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getAllByText("0.38").length).toBeGreaterThan(0);
      });
    });

    it("applies red badge at exactly 0.0", async () => {
      const line = entryLine({ id: "conf-zero", confidence: 0.0 });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        const badges = document.querySelectorAll('[data-tier="red"]');
        expect(badges.length).toBeGreaterThan(0);
      });
    });

    it("applies yellow badge at exactly 0.4", async () => {
      const line = entryLine({ id: "conf-boundary-low", confidence: 0.4 });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        const badges = document.querySelectorAll('[data-tier="yellow"]');
        expect(badges.length).toBeGreaterThan(0);
      });
    });

    it("applies yellow badge at exactly 0.7", async () => {
      const line = entryLine({ id: "conf-boundary-high", confidence: 0.7 });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        const badges = document.querySelectorAll('[data-tier="yellow"]');
        expect(badges.length).toBeGreaterThan(0);
      });
    });

    it("applies green badge at confidence above 0.7", async () => {
      const line = entryLine({ id: "conf-above-high", confidence: 0.71 });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        const badges = document.querySelectorAll('[data-tier="green"]');
        expect(badges.length).toBeGreaterThan(0);
      });
    });
  });

  describe("row expansion — classification metadata", () => {
    it("expands metadata panel when preview is clicked", async () => {
      const line = entryLine({
        id: "expand-1",
        content: "Entry to expand for metadata",
        reasoning: "High relevance signal",
        classified_at: "2026-04-01T12:00:00Z",
        suggested_project: "my-project",
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry to expand for metadata/));

      const expandBtn = screen.getByLabelText(/Toggle detail for entry expand-1/);
      fireEvent.click(expandBtn);

      await waitFor(() => {
        expect(document.querySelector('[data-testid="metadata-panel-expand-1"]')).toBeTruthy();
      });
    });

    it("shows reasoning in expanded metadata", async () => {
      const line = entryLine({
        id: "meta-reasoning",
        reasoning: "Classified due to technical content",
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Test review entry/));

      fireEvent.click(screen.getByLabelText(/Toggle detail for entry meta-reasoning/));

      await waitFor(() => {
        expect(screen.getByText("Classified due to technical content")).toBeTruthy();
      });
    });

    it("shows classified_at in expanded metadata", async () => {
      const line = entryLine({
        id: "meta-date",
        classified_at: "2026-04-01T12:00:00Z",
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Test review entry/));

      fireEvent.click(screen.getByLabelText(/Toggle detail for entry meta-date/));

      await waitFor(() => {
        // Check the raw classified_at value appears in metadata panel
        expect(screen.getByText("2026-04-01T12:00:00Z")).toBeTruthy();
      });
    });

    it("shows suggested_project in expanded metadata", async () => {
      const line = entryLine({
        id: "meta-project",
        suggested_project: "distillery-ops",
      });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Test review entry/));

      fireEvent.click(screen.getByLabelText(/Toggle detail for entry meta-project/));

      await waitFor(() => {
        expect(screen.getByText("distillery-ops")).toBeTruthy();
      });
    });

    it("collapses metadata panel when same preview is clicked again", async () => {
      const line = entryLine({ id: "collapse-1" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Test review entry/));

      const expandBtn = screen.getByLabelText(/Toggle detail for entry collapse-1/);
      fireEvent.click(expandBtn);

      await waitFor(() => {
        expect(document.querySelector('[data-testid="metadata-panel-collapse-1"]')).toBeTruthy();
      });

      fireEvent.click(expandBtn);

      await waitFor(() => {
        expect(document.querySelector('[data-testid="metadata-panel-collapse-1"]')).toBeNull();
      });
    });
  });

  describe("approve action", () => {
    it("calls distillery_resolve_review with action=approve", async () => {
      const line = entryLine({ id: "approve-1", content: "Entry to approve" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))  // list call
        .mockResolvedValue(makeResult(""));       // resolve_review call

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry to approve/));

      fireEvent.click(screen.getByLabelText("Approve entry approve-1"));

      await waitFor(() => {
        const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
        const resolveCalls = calls.filter(([name]) => name === "distillery_resolve_review");
        expect(resolveCalls).toHaveLength(1);
        const [, args] = resolveCalls[0]!;
        expect(args["entry_id"]).toBe("approve-1");
        expect(args["action"]).toBe("approve");
        expect(args["reviewer"]).toBe("test-user");
      });
    });

    it("removes row from table after successful approve", async () => {
      const line = entryLine({ id: "approve-rm", content: "Entry to be removed" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))
        .mockResolvedValue(makeResult(""));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry to be removed/));

      fireEvent.click(screen.getByLabelText("Approve entry approve-rm"));

      await waitFor(() => {
        expect(screen.queryByText(/Entry to be removed/)).toBeNull();
      });
    });

    it("shows error toast on failed approve", async () => {
      const line = entryLine({ id: "approve-err", content: "Entry approve error" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))
        .mockResolvedValue(makeResult("Approve tool error", true));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry approve error/));

      fireEvent.click(screen.getByLabelText("Approve entry approve-err"));

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
      });
    });
  });

  describe("reclassify action", () => {
    it("shows inline type selector when Reclassify is clicked", async () => {
      const line = entryLine({ id: "reclassify-1", content: "Entry to reclassify" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry to reclassify/));

      fireEvent.click(screen.getByLabelText("Reclassify entry reclassify-1"));

      await waitFor(() => {
        expect(screen.getByLabelText(/Select new type for entry reclassify-1/)).toBeTruthy();
      });
    });

    it("calls distillery_resolve_review with action=reclassify and selected type", async () => {
      const line = entryLine({ id: "reclassify-2", content: "Entry to reclassify submit" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))
        .mockResolvedValue(makeResult(""));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry to reclassify submit/));

      fireEvent.click(screen.getByLabelText("Reclassify entry reclassify-2"));

      await waitFor(() =>
        screen.getByLabelText(/Select new type for entry reclassify-2/),
      );

      const select = screen.getByLabelText(/Select new type for entry reclassify-2/);
      fireEvent.change(select, { target: { value: "reference" } });

      fireEvent.click(screen.getByLabelText(/Submit reclassify for entry reclassify-2/));

      await waitFor(() => {
        const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
        const resolveCalls = calls.filter(([name]) => name === "distillery_resolve_review");
        expect(resolveCalls).toHaveLength(1);
        const [, args] = resolveCalls[0]!;
        expect(args["action"]).toBe("reclassify");
        expect(args["new_entry_type"]).toBe("reference");
        expect(args["entry_id"]).toBe("reclassify-2");
      });
    });

    it("removes row after successful reclassify", async () => {
      const line = entryLine({ id: "reclassify-rm", content: "Entry reclassify remove" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))
        .mockResolvedValue(makeResult(""));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry reclassify remove/));

      fireEvent.click(screen.getByLabelText("Reclassify entry reclassify-rm"));

      await waitFor(() =>
        screen.getByLabelText(/Select new type for entry reclassify-rm/),
      );

      fireEvent.click(screen.getByLabelText(/Submit reclassify for entry reclassify-rm/));

      await waitFor(() => {
        expect(screen.queryByText(/Entry reclassify remove/)).toBeNull();
      });
    });

    it("can cancel reclassify form", async () => {
      const line = entryLine({ id: "reclassify-cancel", content: "Entry reclassify cancel" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry reclassify cancel/));

      fireEvent.click(screen.getByLabelText("Reclassify entry reclassify-cancel"));

      await waitFor(() =>
        screen.getByLabelText(/Select new type for entry reclassify-cancel/),
      );

      fireEvent.click(screen.getByLabelText(/Cancel reclassify for entry reclassify-cancel/));

      await waitFor(() => {
        expect(
          screen.queryByLabelText(/Select new type for entry reclassify-cancel/),
        ).toBeNull();
      });
    });
  });

  describe("archive action", () => {
    it("shows confirmation before archiving", async () => {
      const line = entryLine({ id: "archive-1", content: "Entry to archive" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry to archive/));

      fireEvent.click(screen.getByLabelText("Archive entry archive-1"));

      await waitFor(() => {
        expect(screen.getByLabelText(/Confirm archive entry archive-1/)).toBeTruthy();
      });
    });

    it("calls distillery_resolve_review with action=archive after confirmation", async () => {
      const line = entryLine({ id: "archive-2", content: "Entry archive confirm" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))
        .mockResolvedValue(makeResult(""));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry archive confirm/));

      fireEvent.click(screen.getByLabelText("Archive entry archive-2"));

      await waitFor(() => screen.getByLabelText(/Confirm archive entry archive-2/));

      fireEvent.click(screen.getByLabelText(/Confirm archive entry archive-2/));

      await waitFor(() => {
        const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
        const resolveCalls = calls.filter(([name]) => name === "distillery_resolve_review");
        expect(resolveCalls).toHaveLength(1);
        const [, args] = resolveCalls[0]!;
        expect(args["action"]).toBe("archive");
        expect(args["entry_id"]).toBe("archive-2");
        expect(args["reviewer"]).toBe("test-user");
      });
    });

    it("removes row after successful archive", async () => {
      const line = entryLine({ id: "archive-rm", content: "Entry archive removed" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))
        .mockResolvedValue(makeResult(""));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry archive removed/));

      fireEvent.click(screen.getByLabelText("Archive entry archive-rm"));
      await waitFor(() => screen.getByLabelText(/Confirm archive entry archive-rm/));
      fireEvent.click(screen.getByLabelText(/Confirm archive entry archive-rm/));

      await waitFor(() => {
        expect(screen.queryByText(/Entry archive removed/)).toBeNull();
      });
    });

    it("can cancel archive confirmation", async () => {
      const line = entryLine({ id: "archive-cancel", content: "Entry archive cancel" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry archive cancel/));

      fireEvent.click(screen.getByLabelText("Archive entry archive-cancel"));
      await waitFor(() => screen.getByLabelText(/Confirm archive entry archive-cancel/));

      fireEvent.click(screen.getByLabelText(/Cancel archive entry archive-cancel/));

      await waitFor(() => {
        expect(
          screen.queryByLabelText(/Confirm archive entry archive-cancel/),
        ).toBeNull();
        // Entry should still be present
        expect(screen.getByText(/Entry archive cancel/)).toBeTruthy();
      });
    });

    it("does not call resolve_review when archive is cancelled", async () => {
      const line = entryLine({ id: "archive-no-call", content: "Entry archive no call" });
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(line));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry archive no call/));

      fireEvent.click(screen.getByLabelText("Archive entry archive-no-call"));
      await waitFor(() => screen.getByLabelText(/Confirm archive entry archive-no-call/));

      fireEvent.click(screen.getByLabelText(/Cancel archive entry archive-no-call/));

      // Only the initial list call should have been made
      const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
      const resolveCalls = calls.filter(([name]) => name === "distillery_resolve_review");
      expect(resolveCalls).toHaveLength(0);
    });
  });

  describe("batch approve", () => {
    it("renders checkbox for each entry", async () => {
      const lines = [
        entryLine({ id: "batch-a", content: "Batch entry alpha" }),
        entryLine({ id: "batch-b", content: "Batch entry beta" }),
      ].join("\n");
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Batch entry alpha/));

      expect(screen.getByLabelText("Select entry batch-a")).toBeTruthy();
      expect(screen.getByLabelText("Select entry batch-b")).toBeTruthy();
    });

    it("shows 'Approve all selected' button when entries are checked", async () => {
      const line = entryLine({ id: "batch-show", content: "Batch show button" });
      const bridge = makeMockBridge(async () => makeResult(line));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Batch show button/));

      fireEvent.click(screen.getByLabelText("Select entry batch-show"));

      await waitFor(() => {
        expect(
          screen.getByLabelText("Approve all selected entries"),
        ).toBeTruthy();
      });
    });

    it("calls resolve_review for each selected entry on batch approve", async () => {
      const lines = [
        entryLine({ id: "bt1", content: "Batch entry one" }),
        entryLine({ id: "bt2", content: "Batch entry two" }),
      ].join("\n");
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(lines)) // list call
        .mockResolvedValue(makeResult(""));       // each approve

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Batch entry one/));

      fireEvent.click(screen.getByLabelText("Select entry bt1"));
      fireEvent.click(screen.getByLabelText("Select entry bt2"));

      await waitFor(() => screen.getByLabelText("Approve all selected entries"));

      fireEvent.click(screen.getByLabelText("Approve all selected entries"));

      await waitFor(() => {
        const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
        const resolveCalls = calls.filter(([name]) => name === "distillery_resolve_review");
        expect(resolveCalls).toHaveLength(2);
        const entryIds = resolveCalls.map(([, args]) => args["entry_id"]);
        expect(entryIds).toContain("bt1");
        expect(entryIds).toContain("bt2");
      });
    });

    it("shows progress indicator during batch approve", async () => {
      const lines = [
        entryLine({ id: "prog1", content: "Progress entry one" }),
        entryLine({ id: "prog2", content: "Progress entry two" }),
      ].join("\n");

      let resolveApprove!: () => void;
      const pending = new Promise<void>((res) => {
        resolveApprove = res;
      });

      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(lines))
        .mockImplementation(async () => {
          await pending;
          return makeResult("");
        });

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Progress entry one/));

      fireEvent.click(screen.getByLabelText("Select entry prog1"));
      fireEvent.click(screen.getByLabelText("Select entry prog2"));

      await waitFor(() => screen.getByLabelText("Approve all selected entries"));

      fireEvent.click(screen.getByLabelText("Approve all selected entries"));

      await waitFor(() => {
        expect(screen.getByRole("status")).toBeTruthy();
        expect(screen.getByText(/Approving/)).toBeTruthy();
      });

      resolveApprove();
    });

    it("removes rows after successful batch approve", async () => {
      const lines = [
        entryLine({ id: "brm1", content: "Batch remove entry one" }),
        entryLine({ id: "brm2", content: "Batch remove entry two" }),
      ].join("\n");
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(lines))
        .mockResolvedValue(makeResult(""));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Batch remove entry one/));

      fireEvent.click(screen.getByLabelText("Select all entries"));

      await waitFor(() => screen.getByLabelText("Approve all selected entries"));

      fireEvent.click(screen.getByLabelText("Approve all selected entries"));

      await waitFor(() => {
        expect(screen.queryByText(/Batch remove entry one/)).toBeNull();
        expect(screen.queryByText(/Batch remove entry two/)).toBeNull();
      });
    });

    it("select all checkbox selects all entries", async () => {
      const lines = [
        entryLine({ id: "sa1", content: "Select all entry alpha" }),
        entryLine({ id: "sa2", content: "Select all entry beta" }),
      ].join("\n");
      const bridge = makeMockBridge(async () => makeResult(lines));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Select all entry alpha/));

      fireEvent.click(screen.getByLabelText("Select all entries"));

      await waitFor(() => {
        const checkbox1 = screen.getByLabelText("Select entry sa1") as HTMLInputElement;
        const checkbox2 = screen.getByLabelText("Select entry sa2") as HTMLInputElement;
        expect(checkbox1.checked).toBe(true);
        expect(checkbox2.checked).toBe(true);
      });
    });
  });

  describe("empty state", () => {
    it("shows empty state message when no entries exist", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("No entries pending review.")).toBeTruthy();
      });
    });

    it("shows empty state after all entries are approved", async () => {
      const line = entryLine({ id: "empty-after", content: "Last entry" });
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(line))
        .mockResolvedValue(makeResult(""));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(ReviewQueue, { props: { bridge } });

      await waitFor(() => screen.getByText(/Last entry/));

      fireEvent.click(screen.getByLabelText("Approve entry empty-after"));

      await waitFor(() => {
        expect(screen.getByText("No entries pending review.")).toBeTruthy();
      });
    });
  });
});
