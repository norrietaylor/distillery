import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";
import RecentCorrections from "./RecentCorrections.svelte";
import { selectedProject, refreshTick } from "$lib/stores";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";

/**
 * Build a mock McpBridge that returns configurable responses per tool name.
 */
function makeMockBridge(
  toolResponses: Record<string, ToolCallTextResult | (() => ToolCallTextResult)>,
): McpBridge {
  const callTool = vi.fn(
    async (name: string, _args?: Record<string, unknown>): Promise<ToolCallTextResult> => {
      const entry = toolResponses[name];
      if (!entry) {
        return { text: "", isError: false, raw: { content: [] } as never };
      }
      return typeof entry === "function" ? entry() : entry;
    },
  );
  return { callTool } as unknown as McpBridge;
}

/** Construct a successful ToolCallTextResult. */
function ok(text: string): ToolCallTextResult {
  return { text, isError: false, raw: { content: [{ type: "text", text }] } as never };
}

/** Construct an error ToolCallTextResult. */
function err(text: string): ToolCallTextResult {
  return { text, isError: true, raw: { content: [{ type: "text", text }] } as never };
}

/** Build a JSON list response with session entries. */
function listResponse(
  entries: Array<{ id: string; content: string; created_at?: string }>,
): ToolCallTextResult {
  return ok(JSON.stringify(entries));
}

/** Build a JSON relations response with related IDs. */
function relationsResponse(targetIds: string[]): ToolCallTextResult {
  return ok(JSON.stringify(targetIds.map((id) => ({ target_id: id }))));
}

/** Build a JSON get-entry response. */
function getEntryResponse(content: string): ToolCallTextResult {
  return ok(JSON.stringify({ id: "orig-1", content }));
}

describe("RecentCorrections", () => {
  beforeEach(() => {
    selectedProject.set(null);
  });

  describe("loading state", () => {
    it("shows loading skeleton while fetching", async () => {
      // Bridge never resolves — stays loading
      let resolveList: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveList = res;
      });
      const bridge = { callTool: vi.fn().mockReturnValue(pending) } as unknown as McpBridge;

      render(RecentCorrections, { props: { bridge } });

      expect(screen.getByRole("status")).toBeTruthy();
      expect(screen.getByLabelText("Loading recent corrections...")).toBeTruthy();

      // Resolve so the component can unmount cleanly
      resolveList!(ok("[]"));
    });
  });

  describe("empty state", () => {
    it("shows helpful message when no session entries exist", async () => {
      const bridge = makeMockBridge({ distillery_list: ok("[]") });
      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/No corrections found/i)).toBeTruthy();
      });
    });

    it("shows helpful message when entries have no corrects relations", async () => {
      const bridge = makeMockBridge({
        distillery_list: listResponse([{ id: "entry-1", content: "some session" }]),
        distillery_relations: ok("[]"), // No relations
      });

      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/No corrections found/i)).toBeTruthy();
      });
    });
  });

  describe("correction display", () => {
    it("displays correction cards for entries with corrects relations", async () => {
      const bridge = makeMockBridge({
        distillery_list: listResponse([
          { id: "session-1", content: "The correct answer is 42", created_at: "2026-04-01T10:00:00Z" },
          { id: "session-2", content: "Another correction here", created_at: "2026-04-02T10:00:00Z" },
        ]),
        distillery_relations: relationsResponse(["orig-1"]),
        distillery_get: getEntryResponse("The original wrong answer was 41"),
      });

      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        // Both entries have relations, so 2 correction cards should appear
        expect(screen.getAllByRole("button").length).toBeGreaterThanOrEqual(2);
      });
    });

    it("renders section heading", async () => {
      const bridge = makeMockBridge({ distillery_list: ok("[]") });
      render(RecentCorrections, { props: { bridge } });

      expect(screen.getByText("Recent Corrections")).toBeTruthy();
    });

    it("skips entries that have no corrects relations", async () => {
      // entry-1 has relations, entry-2 does not
      let callCount = 0;
      const bridge = {
        callTool: vi.fn(async (name: string, args?: Record<string, unknown>) => {
          if (name === "distillery_list") {
            return listResponse([
              { id: "entry-1", content: "Has correction", created_at: "2026-04-01T10:00:00Z" },
              { id: "entry-2", content: "No correction", created_at: "2026-04-02T10:00:00Z" },
            ]);
          }
          if (name === "distillery_relations") {
            callCount++;
            // First entry has a relation, second does not
            if (args?.entry_id === "entry-1") return relationsResponse(["orig-1"]);
            return ok("[]");
          }
          if (name === "distillery_get") {
            return getEntryResponse("Original content");
          }
          return ok("");
        }),
      } as unknown as McpBridge;

      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        const buttons = screen.getAllByRole("button");
        // Only 1 correction card (entry-1), not 2
        expect(buttons.length).toBe(1);
      });
    });
  });

  describe("error state", () => {
    it("shows error message when list tool returns error", async () => {
      const bridge = makeMockBridge({
        distillery_list: err("Database connection failed"),
      });

      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Database connection failed/i)).toBeTruthy();
      });
    });

    it("shows error message when list tool throws", async () => {
      const bridge = {
        callTool: vi.fn().mockRejectedValue(new Error("Network error")),
      } as unknown as McpBridge;

      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Network error/i)).toBeTruthy();
      });
    });

    it("continues loading other entries if one relations lookup fails", async () => {
      const bridge = {
        callTool: vi.fn(async (name: string, args?: Record<string, unknown>) => {
          if (name === "distillery_list") {
            return listResponse([
              { id: "entry-1", content: "First correction", created_at: "2026-04-01T10:00:00Z" },
              { id: "entry-2", content: "Second correction", created_at: "2026-04-02T10:00:00Z" },
            ]);
          }
          if (name === "distillery_relations") {
            if (args?.entry_id === "entry-1") throw new Error("Lookup failed");
            return relationsResponse(["orig-2"]);
          }
          if (name === "distillery_get") return getEntryResponse("Original for entry-2");
          return ok("");
        }),
      } as unknown as McpBridge;

      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        // entry-2 should still be displayed despite entry-1 failing
        const buttons = screen.getAllByRole("button");
        expect(buttons.length).toBe(1);
      });
    });
  });

  describe("project scoping", () => {
    it("passes project filter to list tool call", async () => {
      selectedProject.set("alpha");

      const bridge = makeMockBridge({ distillery_list: ok("[]") });
      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        expect(bridge.callTool).toHaveBeenCalledWith(
          "distillery_list",
          expect.objectContaining({ project: "alpha" }),
        );
      });
    });

    it("omits project filter when no project selected", async () => {
      selectedProject.set(null);

      const bridge = makeMockBridge({ distillery_list: ok("[]") });
      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        const call = vi.mocked(bridge.callTool).mock.calls.find((c) => c[0] === "distillery_list");
        expect(call).toBeDefined();
        const args = call![1] as Record<string, unknown>;
        expect(args.project).toBeUndefined();
      });
    });
  });

  describe("date filtering", () => {
    it("passes date_from 7 days ago to list call", async () => {
      const bridge = makeMockBridge({ distillery_list: ok("[]") });
      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        const call = vi.mocked(bridge.callTool).mock.calls.find((c) => c[0] === "distillery_list");
        expect(call).toBeDefined();
        const args = call![1] as Record<string, unknown>;
        expect(args.date_from).toBeDefined();
        // Verify date is within the last 8 days (allow a second of slop)
        const dateFrom = new Date(args.date_from as string);
        const eightDaysAgo = new Date();
        eightDaysAgo.setDate(eightDaysAgo.getDate() - 8);
        expect(dateFrom.getTime()).toBeGreaterThan(eightDaysAgo.getTime());
      });
    });
  });

  describe("CorrectionCard expand/collapse", () => {
    async function renderWithOneCorrection() {
      const bridge = makeMockBridge({
        distillery_list: listResponse([
          { id: "s1", content: "The corrected fact", created_at: "2026-04-01T10:00:00Z" },
        ]),
        distillery_relations: relationsResponse(["orig-1"]),
        distillery_get: getEntryResponse("The original wrong fact"),
      });

      render(RecentCorrections, { props: { bridge } });

      // Wait for card to appear
      await waitFor(() => {
        expect(screen.getAllByRole("button").length).toBe(1);
      });
    }

    it("correction card is collapsed by default", async () => {
      await renderWithOneCorrection();
      const card = screen.getByRole("button");
      expect(card.getAttribute("aria-expanded")).toBe("false");
    });

    it("correction card expands when clicked", async () => {
      await renderWithOneCorrection();
      const user = userEvent.setup();
      const card = screen.getByRole("button");

      await user.click(card);

      expect(card.getAttribute("aria-expanded")).toBe("true");
      expect(screen.getByText("Original")).toBeTruthy();
      expect(screen.getByText("Corrected")).toBeTruthy();
    });

    it("correction card shows original and corrected content side by side", async () => {
      await renderWithOneCorrection();
      const user = userEvent.setup();
      const card = screen.getByRole("button");

      await user.click(card);

      // After expanding, the original content appears in the body panel
      expect(screen.getByText("The original wrong fact")).toBeTruthy();
      // The corrected content appears in both the summary and the expanded panel
      // Use getAllByText since the summary also shows the corrected content
      const correctedElements = screen.getAllByText("The corrected fact");
      expect(correctedElements.length).toBeGreaterThanOrEqual(1);
    });

    it("correction card collapses when clicked again", async () => {
      await renderWithOneCorrection();
      const user = userEvent.setup();
      const card = screen.getByRole("button");

      await user.click(card);
      expect(card.getAttribute("aria-expanded")).toBe("true");

      await user.click(card);
      expect(card.getAttribute("aria-expanded")).toBe("false");
    });
  });

  describe("plain text response parsing", () => {
    it("handles plain text list response with pipe-separated format", async () => {
      // Non-JSON response: "id | content | date"
      const plainTextResponse = ok(
        "entry-1 | Content of session | 2026-04-01T10:00:00Z\nentry-2 | Another session | 2026-04-02T10:00:00Z",
      );

      const bridge = makeMockBridge({
        distillery_list: plainTextResponse,
        distillery_relations: ok("[]"),
      });

      render(RecentCorrections, { props: { bridge } });

      await waitFor(() => {
        expect(screen.getByText(/No corrections found/i)).toBeTruthy();
      });
    });
  });
});
