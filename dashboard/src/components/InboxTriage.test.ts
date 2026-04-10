import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import InboxTriage from "./InboxTriage.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";
import { activeTab } from "$lib/stores";
import { get } from "svelte/store";

/** Build a minimal mock ToolCallTextResult. */
function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

/** Build a JSON entry representing an inbox entry. */
function makeEntry(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: `entry-${Math.random().toString(36).slice(2)}`,
    content: "Test inbox entry content for triage",
    source: "rss.example.com",
    created_at: "2026-04-01T12:00:00Z",
    tags: ["imported"],
    ...overrides,
  };
}

function makeMockBridge(
  callToolImpl?: (name: string, args?: Record<string, unknown>) => Promise<ToolCallTextResult>,
): McpBridge {
  const defaultImpl = async () => makeResult("");
  return {
    isConnected: true,
    callTool: vi.fn().mockImplementation(callToolImpl ?? defaultImpl),
  } as unknown as McpBridge;
}

// Suppress Svelte warnings in test output
beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
});

describe("InboxTriage", () => {
  describe("table rendering", () => {
    it("shows loading skeleton while fetching", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(InboxTriage, { props: { bridge } });
      expect(screen.getByRole("status")).toBeTruthy();

      resolveCall(makeResult(""));
    });

    it("renders the section heading", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));
      render(InboxTriage, { props: { bridge } });
      await waitFor(() => {
        expect(screen.getByText("Inbox Triage")).toBeTruthy();
      });
    });

    it("renders table rows for inbox entries", async () => {
      const data = JSON.stringify([
        makeEntry({ id: "e1", content: "Alpha inbox item content" }),
        makeEntry({ id: "e2", content: "Beta inbox item content" }),
      ]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/Alpha inbox item/)).toBeTruthy();
        expect(screen.getByText(/Beta inbox item/)).toBeTruthy();
      });
    });

    it("shows all required column headers", async () => {
      const data = JSON.stringify([makeEntry()]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("Preview")).toBeTruthy();
        expect(screen.getByText("Source")).toBeTruthy();
        expect(screen.getByText("Created Date")).toBeTruthy();
        expect(screen.getByText("Tags")).toBeTruthy();
        expect(screen.getByText("Actions")).toBeTruthy();
      });
    });

    it("calls list tool with entry_type=inbox and status=active", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult(""));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledWith("distillery_list", expect.objectContaining({
          entry_type: "inbox",
          status: "active",
          limit: 50,
        }));
      });
    });
  });

  describe("empty state", () => {
    it("shows empty message when no entries exist", async () => {
      const bridge = makeMockBridge(async () => makeResult("[]"));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => {
        expect(
          screen.getByText(/Inbox is empty\. New feed items and imports will appear here\./)
        ).toBeTruthy();
      });
    });
  });

  describe("inline classify form", () => {
    it("opens classify form when Classify button is clicked", async () => {
      const data = JSON.stringify([makeEntry({ id: "cf-1", content: "Classify me now" })]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Classify me now/));
      fireEvent.click(screen.getByLabelText("Classify entry"));

      await waitFor(() => {
        expect(screen.getByLabelText("Classify form")).toBeTruthy();
        expect(screen.getByLabelText("Entry type")).toBeTruthy();
        expect(screen.getByLabelText("Confidence")).toBeTruthy();
        expect(screen.getByLabelText("Reasoning")).toBeTruthy();
        expect(screen.getByLabelText("Apply classification")).toBeTruthy();
      });
    });

    it("only one classify form open at a time", async () => {
      const data = JSON.stringify([
        makeEntry({ id: "cf-a", content: "Entry A for classify" }),
        makeEntry({ id: "cf-b", content: "Entry B for classify" }),
      ]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry A for classify/));

      // Open form for first entry
      const classifyBtns = screen.getAllByLabelText("Classify entry");
      fireEvent.click(classifyBtns[0]!);
      await waitFor(() => screen.getByLabelText("Classify form"));

      // Open form for second entry — should replace the first
      fireEvent.click(classifyBtns[1]!);
      await waitFor(() => {
        const forms = screen.getAllByLabelText("Classify form");
        expect(forms).toHaveLength(1);
      });
    });

    it("confidence slider defaults to 0.7", async () => {
      const data = JSON.stringify([makeEntry({ id: "cs-1", content: "Slider test entry" })]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Slider test entry/));
      fireEvent.click(screen.getByLabelText("Classify entry"));

      await waitFor(() => {
        const slider = screen.getByLabelText("Confidence") as HTMLInputElement;
        expect(slider.value).toBe("0.7");
        expect(screen.getByText("0.70")).toBeTruthy();
      });
    });

    it("confidence slider has step=0.05 and range 0-1", async () => {
      const data = JSON.stringify([makeEntry({ id: "cs-2", content: "Range test entry" })]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Range test entry/));
      fireEvent.click(screen.getByLabelText("Classify entry"));

      await waitFor(() => {
        const slider = screen.getByLabelText("Confidence") as HTMLInputElement;
        expect(slider.min).toBe("0");
        expect(slider.max).toBe("1");
        expect(slider.step).toBe("0.05");
      });
    });
  });

  describe("classify action", () => {
    it("calls classify tool and removes row on success", async () => {
      const entryData = JSON.stringify([
        makeEntry({ id: "cl-1", content: "Entry to classify now" }),
      ]);
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(entryData)) // list call
        .mockResolvedValueOnce(makeResult("OK"));     // classify call

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Entry to classify now/));

      // Open classify form
      fireEvent.click(screen.getByLabelText("Classify entry"));
      await waitFor(() => screen.getByLabelText("Apply classification"));

      // Apply
      fireEvent.click(screen.getByLabelText("Apply classification"));

      await waitFor(() => {
        // Verify classify tool was called
        const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
        const classifyCalls = calls.filter(([name]) => name === "distillery_classify");
        expect(classifyCalls).toHaveLength(1);
        const [, args] = classifyCalls[0]!;
        expect(args["entry_id"]).toBe("cl-1");
        expect(args["entry_type"]).toBe("session");
        expect(args["confidence"]).toBe(0.7);
      });

      // Row should be removed
      await waitFor(() => {
        expect(screen.queryByText(/Entry to classify now/)).toBeNull();
      });
    });

    it("shows success toast with type and status after classification", async () => {
      const entryData = JSON.stringify([
        makeEntry({ id: "cl-2", content: "Toast test entry now" }),
      ]);
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(entryData))
        .mockResolvedValueOnce(makeResult("OK"));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Toast test entry now/));
      fireEvent.click(screen.getByLabelText("Classify entry"));
      await waitFor(() => screen.getByLabelText("Apply classification"));
      fireEvent.click(screen.getByLabelText("Apply classification"));

      await waitFor(() => {
        expect(screen.getByRole("status")).toBeTruthy();
        expect(screen.getByText(/Classified as session \(active\)/)).toBeTruthy();
      });
    });
  });

  describe("investigate action", () => {
    it("navigates to explore tab when Investigate is clicked", async () => {
      const data = JSON.stringify([
        makeEntry({ id: "inv-1", content: "Investigate this entry" }),
      ]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Investigate this entry/));
      fireEvent.click(screen.getByLabelText("Investigate entry"));

      expect(get(activeTab)).toBe("explore");
    });
  });

  describe("archive action", () => {
    it("shows confirmation prompt when Archive is clicked", async () => {
      const data = JSON.stringify([
        makeEntry({ id: "ar-1", content: "Archive this entry" }),
      ]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Archive this entry/));
      fireEvent.click(screen.getByLabelText("Archive entry"));

      await waitFor(() => {
        expect(screen.getByText("Archive?")).toBeTruthy();
        expect(screen.getByLabelText("Confirm archive")).toBeTruthy();
        expect(screen.getByLabelText("Cancel archive")).toBeTruthy();
      });
    });

    it("calls resolve_review with action=archive on confirm", async () => {
      const data = JSON.stringify([
        makeEntry({ id: "ar-2", content: "Confirm archive entry" }),
      ]);
      const mockCallTool = vi.fn()
        .mockResolvedValueOnce(makeResult(data))
        .mockResolvedValueOnce(makeResult("OK"));

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Confirm archive entry/));
      fireEvent.click(screen.getByLabelText("Archive entry"));
      await waitFor(() => screen.getByLabelText("Confirm archive"));
      fireEvent.click(screen.getByLabelText("Confirm archive"));

      await waitFor(() => {
        const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
        const archiveCalls = calls.filter(([name]) => name === "distillery_resolve_review");
        expect(archiveCalls).toHaveLength(1);
        const [, args] = archiveCalls[0]!;
        expect(args["entry_id"]).toBe("ar-2");
        expect(args["action"]).toBe("archive");
      });

      // Row should be removed
      await waitFor(() => {
        expect(screen.queryByText(/Confirm archive entry/)).toBeNull();
      });
    });

    it("cancels archive when No is clicked", async () => {
      const data = JSON.stringify([
        makeEntry({ id: "ar-3", content: "Cancel archive entry" }),
      ]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Cancel archive entry/));
      fireEvent.click(screen.getByLabelText("Archive entry"));
      await waitFor(() => screen.getByLabelText("Cancel archive"));
      fireEvent.click(screen.getByLabelText("Cancel archive"));

      await waitFor(() => {
        expect(screen.queryByText("Archive?")).toBeNull();
        // Entry should still be there
        expect(screen.getByText(/Cancel archive entry/)).toBeTruthy();
      });
    });
  });

  describe("batch mode", () => {
    it("renders checkbox column for entry selection", async () => {
      const data = JSON.stringify([
        makeEntry({ id: "b-1", content: "Batch entry one" }),
        makeEntry({ id: "b-2", content: "Batch entry two" }),
      ]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText("Select all entries")).toBeTruthy();
        expect(screen.getByLabelText("Select entry b-1")).toBeTruthy();
        expect(screen.getByLabelText("Select entry b-2")).toBeTruthy();
      });
    });

    it("shows batch classify controls", async () => {
      const data = JSON.stringify([makeEntry({ id: "b-3", content: "Batch control entry" })]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByLabelText("Batch classify type")).toBeTruthy();
        expect(screen.getByText(/Apply to \d+ selected/)).toBeTruthy();
      });
    });

    it("select all checkbox toggles all entries", async () => {
      const data = JSON.stringify([
        makeEntry({ id: "b-4", content: "Toggle all A" }),
        makeEntry({ id: "b-5", content: "Toggle all B" }),
      ]);
      const bridge = makeMockBridge(async () => makeResult(data));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByLabelText("Select all entries"));

      const selectAll = screen.getByLabelText("Select all entries") as HTMLInputElement;
      fireEvent.change(selectAll, { target: { checked: true } });

      await waitFor(() => {
        const cb1 = screen.getByLabelText("Select entry b-4") as HTMLInputElement;
        const cb2 = screen.getByLabelText("Select entry b-5") as HTMLInputElement;
        expect(cb1.checked).toBe(true);
        expect(cb2.checked).toBe(true);
      });
    });
  });

  describe("batch processing progress", () => {
    it("processes batch sequentially and shows progress", async () => {
      const data = JSON.stringify([
        makeEntry({ id: "bp-1", content: "Batch progress A" }),
        makeEntry({ id: "bp-2", content: "Batch progress B" }),
      ]);

      let callCount = 0;
      const mockCallTool = vi.fn().mockImplementation(async (name: string) => {
        callCount++;
        if (callCount === 1) return makeResult(data); // list call
        return makeResult("OK"); // classify calls
      });

      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => screen.getByText(/Batch progress A/));

      // Select all
      const selectAll = screen.getByLabelText("Select all entries") as HTMLInputElement;
      fireEvent.change(selectAll, { target: { checked: true } });

      // Select batch type
      const typeSelect = screen.getByLabelText("Batch classify type") as HTMLSelectElement;
      fireEvent.change(typeSelect, { target: { value: "bookmark" } });

      // Click apply
      const applyBtn = screen.getByText(/Apply to 2 selected/);
      fireEvent.click(applyBtn);

      // Wait for batch completion (entries removed, toast shown)
      await waitFor(() => {
        expect(screen.queryByText(/Batch progress A/)).toBeNull();
        expect(screen.queryByText(/Batch progress B/)).toBeNull();
      });

      // Verify classify calls were made
      const calls = mockCallTool.mock.calls as Array<[string, Record<string, unknown>]>;
      const classifyCalls = calls.filter(([name]) => name === "distillery_classify");
      expect(classifyCalls).toHaveLength(2);
    });
  });

  describe("error handling", () => {
    it("shows error banner on load failure", async () => {
      const bridge = makeMockBridge(async () => makeResult("Server error", true));
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Server error/)).toBeTruthy();
      });
    });

    it("shows error banner on thrown exception", async () => {
      const bridge = makeMockBridge(async () => {
        throw new Error("Network failure");
      });
      render(InboxTriage, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Network failure/)).toBeTruthy();
      });
    });
  });
});
