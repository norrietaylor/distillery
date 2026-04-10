import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import EntryDetail from "./EntryDetail.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

interface EntryOverrides {
  id?: string;
  content?: string;
  entry_type?: string;
  source?: string;
  author?: string;
  project?: string;
  status?: string;
  tags?: string[];
  created_at?: string;
  updated_at?: string;
  expires_at?: string;
}

function makeEntry(overrides: EntryOverrides = {}): string {
  return JSON.stringify({
    id: "entry-abc-123",
    content: "This is the full entry content.",
    entry_type: "note",
    source: "github.com/example/repo",
    author: "jane.doe",
    project: "my-project",
    status: "verified",
    tags: ["typescript", "testing"],
    created_at: "2026-03-15T10:00:00Z",
    updated_at: "2026-03-20T12:00:00Z",
    expires_at: null,
    ...overrides,
  });
}

function makeRelation(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "rel-1",
    related_id: "entry-related-456",
    relation_type: "references",
    ...overrides,
  };
}

/**
 * Build a mock McpBridge that responds to distillery_get and
 * distillery_relations with the provided text/error values.
 */
function makeMockBridge(opts: {
  entryText?: string;
  entryError?: boolean;
  relationsText?: string;
  relationsError?: boolean;
  /** Override the full callTool implementation. */
  callToolImpl?: (name: string, args?: Record<string, unknown>) => Promise<ToolCallTextResult>;
}): McpBridge {
  const {
    entryText = makeEntry(),
    entryError = false,
    relationsText = "[]",
    relationsError = false,
    callToolImpl,
  } = opts;

  const impl =
    callToolImpl ??
    ((name: string) => {
      if (name === "distillery_get") {
        return Promise.resolve(makeResult(entryText, entryError));
      }
      if (name === "distillery_relations") {
        return Promise.resolve(makeResult(relationsText, relationsError));
      }
      return Promise.resolve(makeResult(""));
    });

  return {
    isConnected: true,
    callTool: vi.fn().mockImplementation(impl),
  } as unknown as McpBridge;
}

beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EntryDetail", () => {
  describe("empty / no selection state", () => {
    it("shows a placeholder when no entryId is provided", () => {
      render(EntryDetail, { props: { bridge: null } });
      expect(screen.getByText(/Select an entry/)).toBeTruthy();
    });

    it("renders without crashing when bridge is null", () => {
      expect(() => render(EntryDetail, { props: { bridge: null } })).not.toThrow();
    });

    it("wraps content in an aria-labelled region", () => {
      render(EntryDetail, { props: { bridge: null } });
      expect(screen.getByLabelText("Entry detail panel")).toBeTruthy();
    });
  });

  describe("loading state", () => {
    it("shows LoadingSkeleton while fetching", async () => {
      let resolveGet!: (v: ToolCallTextResult) => void;
      const pendingGet = new Promise<ToolCallTextResult>((res) => {
        resolveGet = res;
      });

      const bridge = makeMockBridge({
        callToolImpl: (name) => {
          if (name === "distillery_get") return pendingGet;
          return Promise.resolve(makeResult("[]"));
        },
      });

      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });
      expect(screen.getByRole("status")).toBeTruthy();

      // Resolve to avoid dangling promise.
      resolveGet(makeResult(makeEntry()));
    });

    it("hides LoadingSkeleton after data loads", async () => {
      const bridge = makeMockBridge({});
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.queryByRole("status")).toBeNull();
      });
    });
  });

  describe("data display", () => {
    it("renders the full entry content in a pre block", async () => {
      const bridge = makeMockBridge({
        entryText: makeEntry({ content: "Full content displayed here." }),
      });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.getByText("Full content displayed here.")).toBeTruthy();
      });
    });

    it("shows entry_type badge", async () => {
      const bridge = makeMockBridge({ entryText: makeEntry({ entry_type: "insight" }) });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.getByText("insight")).toBeTruthy();
      });
    });

    it("shows author in metadata", async () => {
      const bridge = makeMockBridge({ entryText: makeEntry({ author: "alice.smith" }) });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.getByText("alice.smith")).toBeTruthy();
      });
    });

    it("shows project in metadata", async () => {
      const bridge = makeMockBridge({ entryText: makeEntry({ project: "distillery-core" }) });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.getByText("distillery-core")).toBeTruthy();
      });
    });

    it("shows source in metadata", async () => {
      const bridge = makeMockBridge({
        entryText: makeEntry({ source: "github.com/example/repo" }),
      });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.getByText("github.com/example/repo")).toBeTruthy();
      });
    });

    it("shows created date in metadata", async () => {
      const bridge = makeMockBridge({
        entryText: makeEntry({ created_at: "2026-03-15T10:00:00Z" }),
      });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        // Intl.DateTimeFormat with en-US format: "Mar 15, 2026"
        expect(screen.getByText("Mar 15, 2026")).toBeTruthy();
      });
    });

    it("shows expiry date when expires_at is set", async () => {
      const bridge = makeMockBridge({
        entryText: makeEntry({ expires_at: "2027-06-15T12:00:00Z" }),
      });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.getByText("Jun 15, 2027")).toBeTruthy();
      });
    });

    it("does not show expiry when expires_at is null", async () => {
      const bridge = makeMockBridge({ entryText: makeEntry({ expires_at: undefined }) });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.queryByText("Expires")).toBeNull();
      });
    });
  });

  describe("verification badges", () => {
    it("shows verified badge for status=verified", async () => {
      const bridge = makeMockBridge({ entryText: makeEntry({ status: "verified" }) });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        const badge = screen.getByLabelText("Verification status");
        expect(badge.textContent?.trim()).toBe("Verified");
        expect(badge.className).toContain("badge--verified");
      });
    });

    it("shows testing badge for status=testing", async () => {
      const bridge = makeMockBridge({ entryText: makeEntry({ status: "testing" }) });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        const badge = screen.getByLabelText("Verification status");
        expect(badge.textContent?.trim()).toBe("Testing");
        expect(badge.className).toContain("badge--testing");
      });
    });

    it("shows unverified badge for status=unverified", async () => {
      const bridge = makeMockBridge({ entryText: makeEntry({ status: "unverified" }) });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        const badge = screen.getByLabelText("Verification status");
        expect(badge.textContent?.trim()).toBe("Unverified");
        expect(badge.className).toContain("badge--unverified");
      });
    });

    it("defaults to unverified badge for unknown status", async () => {
      const bridge = makeMockBridge({ entryText: makeEntry({ status: "draft" }) });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        const badge = screen.getByLabelText("Verification status");
        expect(badge.className).toContain("badge--unverified");
      });
    });
  });

  describe("tags as clickable badges", () => {
    it("renders each tag as a button", async () => {
      const bridge = makeMockBridge({
        entryText: makeEntry({ tags: ["alpha", "beta", "gamma"] }),
      });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.getByLabelText("Filter by tag alpha")).toBeTruthy();
        expect(screen.getByLabelText("Filter by tag beta")).toBeTruthy();
        expect(screen.getByLabelText("Filter by tag gamma")).toBeTruthy();
      });
    });

    it("calls onTagClick with the tag name when a tag is clicked", async () => {
      const onTagClick = vi.fn();
      const bridge = makeMockBridge({
        entryText: makeEntry({ tags: ["typescript"] }),
      });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123", onTagClick } });

      await waitFor(() => screen.getByLabelText("Filter by tag typescript"));
      fireEvent.click(screen.getByLabelText("Filter by tag typescript"));

      expect(onTagClick).toHaveBeenCalledWith("typescript");
    });

    it("renders no tag buttons when tags array is empty", async () => {
      const bridge = makeMockBridge({ entryText: makeEntry({ tags: [] }) });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.queryByLabelText(/Filter by tag/)).toBeNull();
      });
    });
  });

  describe("MCP tool calls", () => {
    it("calls distillery_get with the entry_id", async () => {
      const callTool = vi.fn().mockImplementation((name: string) => {
        if (name === "distillery_get") return Promise.resolve(makeResult(makeEntry()));
        return Promise.resolve(makeResult("[]"));
      });
      const bridge = { isConnected: true, callTool } as unknown as McpBridge;

      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(callTool).toHaveBeenCalledWith("distillery_get", { entry_id: "entry-abc-123" });
      });
    });

    it("calls distillery_relations with action=get and entry_id", async () => {
      const callTool = vi.fn().mockImplementation((name: string) => {
        if (name === "distillery_get") return Promise.resolve(makeResult(makeEntry()));
        return Promise.resolve(makeResult("[]"));
      });
      const bridge = { isConnected: true, callTool } as unknown as McpBridge;

      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(callTool).toHaveBeenCalledWith("distillery_relations", {
          action: "get",
          entry_id: "entry-abc-123",
        });
      });
    });

    it("calls both tools in parallel (both called before either resolves)", async () => {
      const callOrder: string[] = [];
      let resolveGet!: (v: ToolCallTextResult) => void;
      let resolveRel!: (v: ToolCallTextResult) => void;

      const bridge = makeMockBridge({
        callToolImpl: (name) => {
          callOrder.push(name);
          if (name === "distillery_get") {
            return new Promise<ToolCallTextResult>((res) => { resolveGet = res; });
          }
          return new Promise<ToolCallTextResult>((res) => { resolveRel = res; });
        },
      });

      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(callOrder).toContain("distillery_get");
        expect(callOrder).toContain("distillery_relations");
      });

      resolveGet(makeResult(makeEntry()));
      resolveRel(makeResult("[]"));
    });
  });

  describe("error handling", () => {
    it("shows error banner when distillery_get returns isError", async () => {
      const bridge = makeMockBridge({ entryError: true, entryText: "Entry not found" });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Entry not found/)).toBeTruthy();
      });
    });

    it("shows error banner when callTool throws", async () => {
      const bridge = makeMockBridge({
        callToolImpl: async () => {
          throw new Error("Network error");
        },
      });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Network error/)).toBeTruthy();
      });
    });

    it("clears error and entry when entryId is set to null", async () => {
      const bridge = makeMockBridge({ entryError: true, entryText: "Error loading" });

      const { rerender } = render(EntryDetail, {
        props: { bridge, entryId: "entry-abc-123" },
      });

      await waitFor(() => screen.getByRole("alert"));

      rerender({ bridge, entryId: null });

      await waitFor(() => {
        expect(screen.queryByRole("alert")).toBeNull();
        expect(screen.getByText(/Select an entry/)).toBeTruthy();
      });
    });
  });

  describe("relations", () => {
    it("renders relation links when relations are present", async () => {
      const relData = JSON.stringify([makeRelation({ related_id: "entry-related-456", relation_type: "references" })]);
      const bridge = makeMockBridge({ relationsText: relData });
      const onNavigate = vi.fn();

      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123", onNavigate } });

      await waitFor(() => {
        expect(screen.getByLabelText("View related entry entry-related-456")).toBeTruthy();
      });
    });

    it("calls onNavigate when a relation link is clicked", async () => {
      const relData = JSON.stringify([makeRelation({ related_id: "entry-related-456" })]);
      const bridge = makeMockBridge({ relationsText: relData });
      const onNavigate = vi.fn();

      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123", onNavigate } });

      await waitFor(() => screen.getByLabelText("View related entry entry-related-456"));
      fireEvent.click(screen.getByLabelText("View related entry entry-related-456"));

      expect(onNavigate).toHaveBeenCalledWith("entry-related-456");
    });

    it("shows the relation type label", async () => {
      const relData = JSON.stringify([makeRelation({ relation_type: "supersedes" })]);
      const bridge = makeMockBridge({ relationsText: relData });

      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123", onNavigate: vi.fn() } });

      await waitFor(() => {
        expect(screen.getByText("supersedes")).toBeTruthy();
      });
    });

    it("renders no relations section when relations are empty", async () => {
      const bridge = makeMockBridge({ relationsText: "[]" });
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123" } });

      await waitFor(() => {
        expect(screen.queryByText("Relations")).toBeNull();
      });
    });
  });

  describe("investigate action", () => {
    it("shows Investigate button when onInvestigate is provided", async () => {
      const bridge = makeMockBridge({});
      render(EntryDetail, {
        props: { bridge, entryId: "entry-abc-123", onInvestigate: vi.fn() },
      });

      await waitFor(() => {
        expect(screen.getByLabelText("Investigate entry")).toBeTruthy();
      });
    });

    it("calls onInvestigate with entry id when Investigate is clicked", async () => {
      const onInvestigate = vi.fn();
      const bridge = makeMockBridge({});
      render(EntryDetail, { props: { bridge, entryId: "entry-abc-123", onInvestigate } });

      await waitFor(() => screen.getByLabelText("Investigate entry"));
      fireEvent.click(screen.getByLabelText("Investigate entry"));

      expect(onInvestigate).toHaveBeenCalledWith("entry-abc-123");
    });
  });
});
