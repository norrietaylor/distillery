import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import SearchBar from "./SearchBar.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";
import { selectedProject } from "$lib/stores";

/** Build a minimal mock ToolCallTextResult. */
function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

/** Build a JSON line representing a search result entry. */
function resultLine(overrides: Record<string, unknown> = {}): string {
  const entry = {
    id: `id-${Math.random().toString(36).slice(2)}`,
    content: "Test search result content",
    source: "github.com/example",
    entry_type: "knowledge",
    score: 0.82,
    tags: ["typescript", "test"],
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
  // Reset project selection between tests
  selectedProject.set(null);
});

describe("SearchBar", () => {
  describe("rendering", () => {
    it("renders without crashing when bridge is null", () => {
      expect(() => render(SearchBar, { props: { bridge: null } })).not.toThrow();
    });

    it("shows section heading", () => {
      render(SearchBar, { props: { bridge: null } });
      expect(screen.getByText("Search Knowledge Base")).toBeTruthy();
    });

    it("shows search input with placeholder", () => {
      render(SearchBar, { props: { bridge: null } });
      expect(screen.getByPlaceholderText("Search entries...")).toBeTruthy();
    });

    it("shows Search button", () => {
      render(SearchBar, { props: { bridge: null } });
      expect(screen.getByRole("button", { name: "Run search" })).toBeTruthy();
    });

    it("does not show results list before a search is performed", () => {
      render(SearchBar, { props: { bridge: null } });
      expect(screen.queryByRole("list", { name: "Search results" })).toBeNull();
    });

    it("has a search form with role=search", () => {
      render(SearchBar, { props: { bridge: null } });
      expect(screen.getByRole("search", { name: "Knowledge base search" })).toBeTruthy();
    });
  });

  describe("search submission", () => {
    it("calls distillery_recall with the entered query when Search is clicked", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("[]"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "svelte components" } });
      fireEvent.click(screen.getByRole("button", { name: "Run search" }));

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledWith(
          "distillery_recall",
          expect.objectContaining({ query: "svelte components" }),
        );
      });
    });

    it("calls distillery_recall when form is submitted (Enter key / submit button)", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("[]"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "knowledge query" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledWith(
          "distillery_recall",
          expect.objectContaining({ query: "knowledge query" }),
        );
      });
    });

    it("does not call distillery_recall when query is empty", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("[]"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SearchBar, { props: { bridge } });

      fireEvent.click(screen.getByRole("button", { name: "Run search" }));

      // Brief wait to confirm no call was made
      await new Promise((r) => setTimeout(r, 20));
      expect(mockCallTool).not.toHaveBeenCalled();
    });

    it("does not call distillery_recall when query is only whitespace", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("[]"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "   " } });
      fireEvent.submit(input.closest("form")!);

      await new Promise((r) => setTimeout(r, 20));
      expect(mockCallTool).not.toHaveBeenCalled();
    });

    it("passes limit=20 to the tool call", async () => {
      const mockCallTool = vi.fn().mockResolvedValue(makeResult("[]"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "typescript" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledWith(
          "distillery_recall",
          expect.objectContaining({ limit: 20 }),
        );
      });
    });
  });

  describe("loading state", () => {
    it("shows loading indicator while search is in progress", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "test query" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.getByRole("status", { name: "Searching" })).toBeTruthy();
      });

      // Resolve to avoid dangling promise
      resolveCall(makeResult("[]"));
    });

    it("disables the search button while loading", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "test query" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        const btn = screen.getByRole("button", { name: "Run search" });
        expect((btn as HTMLButtonElement).disabled).toBe(true);
      });

      resolveCall(makeResult("[]"));
    });

    it("disables the search input while loading", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "test query" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        const el = screen.getByPlaceholderText("Search entries...");
        expect((el as HTMLInputElement).disabled).toBe(true);
      });

      resolveCall(makeResult("[]"));
    });

    it("clears loading indicator after search completes", async () => {
      const bridge = makeMockBridge(async () => makeResult("[]"));

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "test query" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.queryByRole("status", { name: "Searching" })).toBeNull();
      });
    });
  });

  describe("results rendering", () => {
    it("renders search results as a list after a successful search", async () => {
      const lines = [
        resultLine({ content: "First result about Svelte", entry_type: "knowledge" }),
        resultLine({ content: "Second result about TypeScript", entry_type: "note" }),
      ].join("\n");

      const bridge = makeMockBridge(async () => makeResult(lines));

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "svelte" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.getByRole("list", { name: "Search results" })).toBeTruthy();
        expect(screen.getByText(/First result about Svelte/)).toBeTruthy();
        expect(screen.getByText(/Second result about TypeScript/)).toBeTruthy();
      });
    });

    it("renders JSON array responses correctly", async () => {
      const results = [
        { id: "a1", content: "Array result alpha", source: "src-a", entry_type: "knowledge", score: 0.9, tags: [] },
        { id: "b2", content: "Array result beta", source: "src-b", entry_type: "note", score: 0.7, tags: [] },
      ];
      const bridge = makeMockBridge(async () => makeResult(JSON.stringify(results)));

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "array" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.getByText(/Array result alpha/)).toBeTruthy();
        expect(screen.getByText(/Array result beta/)).toBeTruthy();
      });
    });

    it("shows entry_type badge for each result", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(resultLine({ content: "Sample entry", entry_type: "bookmark" })),
      );

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "sample" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.getByText("bookmark")).toBeTruthy();
      });
    });

    it("shows source for each result", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(resultLine({ content: "Entry with source", source: "rss.example.com" })),
      );

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "source" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.getByText("rss.example.com")).toBeTruthy();
      });
    });

    it("shows formatted relevance score for each result", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(resultLine({ content: "Scored entry", score: 0.75 })),
      );

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "score" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        // 0.75 → "75%"
        expect(screen.getByText("75%")).toBeTruthy();
      });
    });

    it("shows tags for results that have them", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult(resultLine({ content: "Tagged entry", tags: ["svelte", "ui"] })),
      );

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "tagged" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.getByText("svelte")).toBeTruthy();
        expect(screen.getByText("ui")).toBeTruthy();
      });
    });

    it("truncates content preview to 120 characters", async () => {
      const longContent = "A".repeat(130);
      const bridge = makeMockBridge(async () =>
        makeResult(resultLine({ content: longContent })),
      );

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "long" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        // Should show first 120 chars + ellipsis, not the full 130
        const preview = `${"A".repeat(120)}…`;
        expect(screen.getByText(preview)).toBeTruthy();
      });
    });
  });

  describe("error state", () => {
    it("shows error banner when tool returns isError=true", async () => {
      const bridge = makeMockBridge(async () =>
        makeResult("Tool execution failed", true),
      );

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "query" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Tool execution failed/)).toBeTruthy();
      });
    });

    it("shows error banner when tool call throws an exception", async () => {
      const bridge = makeMockBridge(async () => {
        throw new Error("Network failure");
      });

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "query" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
        expect(screen.getByText(/Network failure/)).toBeTruthy();
      });
    });

    it("clears previous error when a new search starts", async () => {
      let callCount = 0;
      const mockCallTool = vi.fn().mockImplementation(async () => {
        callCount++;
        if (callCount === 1) return makeResult("Error", true);
        return makeResult(resultLine({ content: "Success result" }));
      });
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "first" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => screen.getByRole("alert"));

      // Second search — should clear error
      fireEvent.input(input, { target: { value: "second" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.queryByRole("alert")).toBeNull();
        expect(screen.getByText(/Success result/)).toBeTruthy();
      });
    });
  });

  describe("empty state", () => {
    it("shows empty state message when search returns no results", async () => {
      const bridge = makeMockBridge(async () => makeResult("[]"));

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "obscure query" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.getByText(/No results found/)).toBeTruthy();
      });
    });

    it("does not show empty state before any search is performed", () => {
      const bridge = makeMockBridge(async () => makeResult("[]"));
      render(SearchBar, { props: { bridge } });
      expect(screen.queryByText(/No results found/)).toBeNull();
    });

    it("shows empty state when tool returns empty text", async () => {
      const bridge = makeMockBridge(async () => makeResult(""));

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "nothing" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(screen.getByText(/No results found/)).toBeTruthy();
      });
    });
  });

  describe("project scoping", () => {
    it("passes project filter when a project is selected", async () => {
      selectedProject.set("my-project");

      const mockCallTool = vi.fn().mockResolvedValue(makeResult("[]"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "svelte" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        expect(mockCallTool).toHaveBeenCalledWith(
          "distillery_recall",
          expect.objectContaining({ project: "my-project" }),
        );
      });
    });

    it("omits project filter when no project is selected", async () => {
      selectedProject.set(null);

      const mockCallTool = vi.fn().mockResolvedValue(makeResult("[]"));
      const bridge = { isConnected: true, callTool: mockCallTool } as unknown as McpBridge;

      render(SearchBar, { props: { bridge } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "svelte" } });
      fireEvent.submit(input.closest("form")!);

      await waitFor(() => {
        const [, args] = mockCallTool.mock.calls[0] as [string, Record<string, unknown>];
        expect(args["project"]).toBeUndefined();
      });
    });
  });

  describe("no bridge", () => {
    it("renders heading and form even with no bridge", () => {
      render(SearchBar, { props: { bridge: null } });
      expect(screen.getByText("Search Knowledge Base")).toBeTruthy();
      expect(screen.getByRole("search")).toBeTruthy();
    });

    it("does not call any tool when bridge is null and search is submitted", async () => {
      // With null bridge, the component simply skips the search
      render(SearchBar, { props: { bridge: null } });

      const input = screen.getByPlaceholderText("Search entries...");
      fireEvent.input(input, { target: { value: "test" } });
      fireEvent.submit(input.closest("form")!);

      // No crash; just confirm no error state appears
      await new Promise((r) => setTimeout(r, 20));
      expect(screen.queryByRole("alert")).toBeNull();
    });
  });
});
