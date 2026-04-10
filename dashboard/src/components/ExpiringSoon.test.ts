import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/svelte";
import ExpiringSoon from "./ExpiringSoon.svelte";
import type { McpBridge } from "$lib/mcp-bridge";

// Helper to build an ISO date offset from now by N days
function futureDate(daysFromNow: number): string {
  const d = new Date();
  d.setDate(d.getDate() + daysFromNow);
  return d.toISOString();
}

function pastDate(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  return d.toISOString();
}

function makeMockBridge(listResponse: object | string, updateResponse?: object): McpBridge {
  const listText =
    typeof listResponse === "string" ? listResponse : JSON.stringify(listResponse);
  const updateText =
    updateResponse !== undefined ? JSON.stringify(updateResponse) : JSON.stringify({ ok: true });

  return {
    callTool: vi.fn().mockImplementation((name: string) => {
      if (name === "distillery_list") {
        return Promise.resolve({ text: listText, isError: false, raw: {} });
      }
      if (name === "distillery_update") {
        return Promise.resolve({ text: updateText, isError: false, raw: {} });
      }
      return Promise.resolve({ text: "", isError: true, raw: {} });
    }),
  } as unknown as McpBridge;
}

describe("ExpiringSoon", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("empty state", () => {
    it("shows empty state when no entries are expiring within 14 days", async () => {
      const bridge = makeMockBridge([
        { id: "e1", title: "Far future entry", expires_at: futureDate(30) },
        { id: "e2", title: "Past entry", expires_at: pastDate(1) },
        { id: "e3", title: "No expiry", expires_at: null },
      ]);

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/No entries expiring in the next 14 days/)).toBeTruthy();
      });
    });

    it("shows empty state with helpful hint text", async () => {
      const bridge = makeMockBridge([]);

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/Entries with expiry dates approaching will appear here/i)).toBeTruthy();
      });
    });
  });

  describe("display", () => {
    it("shows section heading", async () => {
      const bridge = makeMockBridge([]);

      render(ExpiringSoon, { props: { bridge } });

      expect(screen.getByText("Expiring Soon")).toBeTruthy();
    });

    it("renders expiring entries within 14 days", async () => {
      const bridge = makeMockBridge([
        { id: "e1", title: "Soon entry", expires_at: futureDate(5) },
        { id: "e2", title: "Far entry", expires_at: futureDate(20) },
      ]);

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("Soon entry")).toBeTruthy();
      });
      expect(screen.queryByText("Far entry")).toBeNull();
    });

    it("shows days remaining for each entry", async () => {
      const bridge = makeMockBridge([
        { id: "e1", title: "Three days", expires_at: futureDate(3) },
      ]);

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/3d/)).toBeTruthy();
      });
    });

    it("shows expiry date for each entry", async () => {
      const bridge = makeMockBridge([
        { id: "e1", title: "Entry with date", expires_at: futureDate(7) },
      ]);

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/Expires/)).toBeTruthy();
      });
    });

    it("sorts entries by days remaining ascending", async () => {
      const bridge = makeMockBridge([
        { id: "e2", title: "Ten days", expires_at: futureDate(10) },
        { id: "e1", title: "Two days", expires_at: futureDate(2) },
        { id: "e3", title: "Seven days", expires_at: futureDate(7) },
      ]);

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => {
        const titles = screen
          .getAllByRole("listitem")
          .map((el) => el.textContent ?? "");
        const twoIdx = titles.findIndex((t) => t.includes("Two days"));
        const sevenIdx = titles.findIndex((t) => t.includes("Seven days"));
        const tenIdx = titles.findIndex((t) => t.includes("Ten days"));
        expect(twoIdx).toBeLessThan(sevenIdx);
        expect(sevenIdx).toBeLessThan(tenIdx);
      });
    });

    it("handles entries array nested under 'entries' key", async () => {
      const bridge = makeMockBridge({
        entries: [{ id: "e1", title: "Nested entry", expires_at: futureDate(4) }],
        total: 1,
      });

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText("Nested entry")).toBeTruthy();
      });
    });

    it("shows loading skeleton during fetch", () => {
      const bridge = makeMockBridge([]);
      // Don't await — check immediately
      render(ExpiringSoon, { props: { bridge } });

      expect(screen.getByRole("status", { name: /Loading expiring entries/i })).toBeTruthy();
    });
  });

  describe("error state", () => {
    it("shows error message when list call fails", async () => {
      const bridge = {
        callTool: vi.fn().mockResolvedValue({ text: "", isError: true, raw: {} }),
      } as unknown as McpBridge;

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Failed to load expiring entries/)).toBeTruthy();
      });
    });

    it("shows error when bridge throws", async () => {
      const bridge = {
        callTool: vi.fn().mockRejectedValue(new Error("network error")),
      } as unknown as McpBridge;

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/network error/)).toBeTruthy();
      });
    });
  });

  describe("action buttons", () => {
    it("renders Archive and Extend buttons for each entry", async () => {
      const bridge = makeMockBridge([
        { id: "e1", title: "Entry one", expires_at: futureDate(5) },
      ]);

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("button", { name: /Archive/i })).toBeTruthy();
        expect(screen.getByRole("button", { name: /Extend/i })).toBeTruthy();
      });
    });

    it("calls distillery_update with status archived on archive click", async () => {
      const bridge = makeMockBridge([
        { id: "entry-abc", title: "Will archive", expires_at: futureDate(6) },
      ]);

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => screen.getByRole("button", { name: "Archive Will archive" }));
      await fireEvent.click(screen.getByRole("button", { name: "Archive Will archive" }));

      await waitFor(() => {
        expect(bridge.callTool).toHaveBeenCalledWith("distillery_update", {
          entry_id: "entry-abc",
          status: "archived",
        });
      });
    });

    it("calls distillery_update with expires_at +30 days on extend click", async () => {
      const bridge = makeMockBridge([
        { id: "entry-def", title: "Will extend", expires_at: futureDate(8) },
      ]);

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => screen.getByRole("button", { name: "Extend Will extend" }));
      await fireEvent.click(screen.getByRole("button", { name: "Extend Will extend" }));

      await waitFor(() => {
        expect(bridge.callTool).toHaveBeenCalledWith(
          "distillery_update",
          expect.objectContaining({
            entry_id: "entry-def",
            expires_at: expect.stringMatching(/^\d{4}-\d{2}-\d{2}T/),
          }),
        );
      });
    });

    it("refreshes the list after a successful action", async () => {
      const entryList = JSON.stringify([
        { id: "e1", title: "Entry", expires_at: futureDate(5) },
      ]);
      const callToolMock = vi.fn().mockImplementation((name: string) => {
        if (name === "distillery_list") {
          return Promise.resolve({ text: entryList, isError: false, raw: {} });
        }
        // distillery_update succeeds
        return Promise.resolve({ text: "{}", isError: false, raw: {} });
      });

      const bridge = { callTool: callToolMock } as unknown as McpBridge;

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => screen.getByRole("button", { name: "Archive Entry" }));
      const listCallsBefore = callToolMock.mock.calls.filter(
        (c: unknown[]) => c[0] === "distillery_list",
      ).length;

      await fireEvent.click(screen.getByRole("button", { name: "Archive Entry" }));

      await waitFor(() => {
        const listCallsAfter = callToolMock.mock.calls.filter(
          (c: unknown[]) => c[0] === "distillery_list",
        ).length;
        expect(listCallsAfter).toBeGreaterThan(listCallsBefore);
      });
    });

    it("shows error message when archive action fails", async () => {
      const entryList = JSON.stringify([
        { id: "e1", title: "Entry", expires_at: futureDate(5) },
      ]);
      const callToolMock = vi.fn().mockImplementation((name: string) => {
        if (name === "distillery_list") {
          return Promise.resolve({ text: entryList, isError: false, raw: {} });
        }
        // distillery_update fails
        return Promise.resolve({ text: "", isError: true, raw: {} });
      });

      const bridge = { callTool: callToolMock } as unknown as McpBridge;

      render(ExpiringSoon, { props: { bridge } });

      await waitFor(() => screen.getByRole("button", { name: "Archive Entry" }));
      await fireEvent.click(screen.getByRole("button", { name: "Archive Entry" }));

      await waitFor(() => {
        expect(screen.getByText(/Failed to archive entry/)).toBeTruthy();
      });
    });
  });
});
