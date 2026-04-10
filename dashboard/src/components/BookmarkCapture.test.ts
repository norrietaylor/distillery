import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import BookmarkCapture from "./BookmarkCapture.svelte";
import type { McpBridge, ToolCallTextResult } from "$lib/mcp-bridge";

/** Build a minimal mock ToolCallTextResult. */
function makeResult(text: string, isError = false): ToolCallTextResult {
  return {
    text,
    isError,
    raw: { content: [{ type: "text", text }] } as ToolCallTextResult["raw"],
  };
}

function makeMockBridge(
  callToolImpl?: (
    name: string,
    args?: Record<string, unknown>,
  ) => Promise<ToolCallTextResult>,
): McpBridge {
  const impl = callToolImpl ?? (async () => makeResult(""));
  return {
    isConnected: true,
    callTool: vi.fn().mockImplementation(impl),
  } as unknown as McpBridge;
}

// Suppress Svelte warnings in test output
beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
  vi.useFakeTimers();
});

describe("BookmarkCapture", () => {
  describe("form display", () => {
    it("renders the bookmark card with all required inputs", () => {
      const bridge = makeMockBridge();
      render(BookmarkCapture, { props: { bridge } });

      expect(screen.getByTestId("bookmark-card")).toBeTruthy();
      expect(screen.getByLabelText("Bookmark URL")).toBeTruthy();
      expect(screen.getByLabelText("Bookmark tags")).toBeTruthy();
      expect(screen.getByLabelText("Bookmark project")).toBeTruthy();
      expect(screen.getByLabelText("Check for duplicates")).toBeTruthy();
      expect(screen.getByLabelText("Save")).toBeTruthy();
    });

    it("shows tags placeholder with #tag1 #tag2 format", () => {
      const bridge = makeMockBridge();
      render(BookmarkCapture, { props: { bridge } });

      const tagsInput = screen.getByLabelText("Bookmark tags") as HTMLInputElement;
      expect(tagsInput.placeholder).toBe("#tag1 #tag2");
    });
  });

  describe("URL validation", () => {
    it("enables buttons for valid https URL", async () => {
      const bridge = makeMockBridge();
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });

      const checkBtn = screen.getByLabelText("Check for duplicates") as HTMLButtonElement;
      const saveBtn = screen.getByLabelText("Save") as HTMLButtonElement;
      expect(checkBtn.disabled).toBe(false);
      expect(saveBtn.disabled).toBe(false);
    });

    it("enables buttons for valid http URL", async () => {
      const bridge = makeMockBridge();
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "http://example.com/article" },
      });

      const checkBtn = screen.getByLabelText("Check for duplicates") as HTMLButtonElement;
      expect(checkBtn.disabled).toBe(false);
    });

    it("disables buttons and shows validation message for invalid URL", async () => {
      const bridge = makeMockBridge();
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, { target: { value: "not-a-url" } });

      const checkBtn = screen.getByLabelText("Check for duplicates") as HTMLButtonElement;
      const saveBtn = screen.getByLabelText("Save") as HTMLButtonElement;
      expect(checkBtn.disabled).toBe(true);
      expect(saveBtn.disabled).toBe(true);
      expect(
        screen.getByText("Enter a valid URL starting with http:// or https://"),
      ).toBeTruthy();
    });

    it("disables buttons when URL is empty", () => {
      const bridge = makeMockBridge();
      render(BookmarkCapture, { props: { bridge } });

      const checkBtn = screen.getByLabelText("Check for duplicates") as HTMLButtonElement;
      const saveBtn = screen.getByLabelText("Save") as HTMLButtonElement;
      expect(checkBtn.disabled).toBe(true);
      expect(saveBtn.disabled).toBe(true);
    });
  });

  describe("dedup check — no duplicates (create)", () => {
    it("shows green indicator when no duplicates found", async () => {
      vi.useRealTimers();
      const bridge = makeMockBridge(async () => makeResult(""));
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/new-article" },
      });

      const checkBtn = screen.getByLabelText("Check for duplicates");
      await fireEvent.click(checkBtn);

      await waitFor(() => {
        expect(screen.getByText("No duplicates found")).toBeTruthy();
        expect(screen.getByTestId("dedup-results")).toBeTruthy();
      });
    });

    it("calls find_similar with correct arguments", async () => {
      vi.useRealTimers();
      const bridge = makeMockBridge(async () => makeResult(""));
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/new-article" },
      });

      await fireEvent.click(screen.getByLabelText("Check for duplicates"));

      await waitFor(() => {
        const calls = (bridge.callTool as ReturnType<typeof vi.fn>).mock
          .calls as Array<[string, Record<string, unknown>]>;
        expect(calls).toHaveLength(1);
        const [name, args] = calls[0]!;
        expect(name).toBe("find_similar");
        expect(args["content"]).toBe("https://example.com/new-article");
        expect(args["threshold"]).toBe(0.8);
        expect(args["dedup_action"]).toBe(true);
      });
    });
  });

  describe("dedup check — skip recommended", () => {
    it("shows warning banner for near-exact duplicate", async () => {
      vi.useRealTimers();
      const skipResult = JSON.stringify([
        {
          id: "existing-1",
          content: "https://example.com/existing",
          similarity: 0.97,
          action: "skip",
        },
      ]);
      const bridge = makeMockBridge(async () => makeResult(skipResult));
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/existing" },
      });
      await fireEvent.click(screen.getByLabelText("Check for duplicates"));

      await waitFor(() => {
        expect(screen.getByText("This entry already exists")).toBeTruthy();
        expect(screen.getByLabelText("Save anyway")).toBeTruthy();
        // Primary Save button should be hidden for skip
        expect(screen.queryByLabelText("Save")).toBeNull();
      });
    });

    it("allows saving anyway despite skip recommendation", async () => {
      vi.useRealTimers();
      const skipResult = JSON.stringify([
        {
          id: "existing-1",
          content: "https://example.com/existing",
          similarity: 0.97,
          action: "skip",
        },
      ]);
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(skipResult)) // find_similar
        .mockResolvedValueOnce(makeResult('{"id": "new-123"}')); // store

      const bridge = {
        isConnected: true,
        callTool: mockCallTool,
      } as unknown as McpBridge;

      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/existing" },
      });
      await fireEvent.click(screen.getByLabelText("Check for duplicates"));
      await waitFor(() => screen.getByLabelText("Save anyway"));

      await fireEvent.click(screen.getByLabelText("Save anyway"));

      await waitFor(() => {
        expect(screen.getByTestId("success-toast")).toBeTruthy();
      });
    });
  });

  describe("dedup check — merge recommended", () => {
    it("shows merge and save-as-new buttons", async () => {
      vi.useRealTimers();
      const mergeResult = JSON.stringify([
        {
          id: "similar-1",
          content: "A similar article about Rust async",
          similarity: 0.9,
          action: "merge",
        },
      ]);
      const bridge = makeMockBridge(async () => makeResult(mergeResult));
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/similar" },
      });
      await fireEvent.click(screen.getByLabelText("Check for duplicates"));

      await waitFor(() => {
        expect(
          screen.getByText("A similar article about Rust async"),
        ).toBeTruthy();
        expect(screen.getByLabelText("Merge with existing")).toBeTruthy();
        expect(screen.getByLabelText("Save as new")).toBeTruthy();
      });
    });

    it("saves as new when user clicks Save as new", async () => {
      vi.useRealTimers();
      const mergeResult = JSON.stringify([
        {
          id: "similar-1",
          content: "Merge target content",
          similarity: 0.9,
          action: "merge",
        },
      ]);
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(mergeResult))
        .mockResolvedValueOnce(makeResult('{"id": "abc-456"}'));

      const bridge = {
        isConnected: true,
        callTool: mockCallTool,
      } as unknown as McpBridge;

      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/similar" },
      });
      await fireEvent.click(screen.getByLabelText("Check for duplicates"));
      await waitFor(() => screen.getByLabelText("Save as new"));

      await fireEvent.click(screen.getByLabelText("Save as new"));

      await waitFor(() => {
        const calls = mockCallTool.mock.calls as Array<
          [string, Record<string, unknown>]
        >;
        const storeCalls = calls.filter(([name]) => name === "store");
        expect(storeCalls).toHaveLength(1);
        expect(storeCalls[0]![1]["entry_type"]).toBe("bookmark");
      });
    });
  });

  describe("dedup check — link recommended", () => {
    it("shows save-and-link and save-without-linking buttons", async () => {
      vi.useRealTimers();
      const linkResult = JSON.stringify([
        {
          id: "related-1",
          content: "A related article on networking",
          similarity: 0.75,
          action: "link",
        },
      ]);
      const bridge = makeMockBridge(async () => makeResult(linkResult));
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/related" },
      });
      await fireEvent.click(screen.getByLabelText("Check for duplicates"));

      await waitFor(() => {
        expect(
          screen.getByText("A related article on networking"),
        ).toBeTruthy();
        expect(screen.getByLabelText("Save and link")).toBeTruthy();
        expect(screen.getByLabelText("Save without linking")).toBeTruthy();
      });
    });

    it("saves without linking when user clicks Save without linking", async () => {
      vi.useRealTimers();
      const linkResult = JSON.stringify([
        {
          id: "related-1",
          content: "Related content",
          similarity: 0.75,
          action: "link",
        },
      ]);
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult(linkResult))
        .mockResolvedValueOnce(makeResult('{"id": "def-789"}'));

      const bridge = {
        isConnected: true,
        callTool: mockCallTool,
      } as unknown as McpBridge;

      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/related" },
      });
      await fireEvent.click(screen.getByLabelText("Check for duplicates"));
      await waitFor(() => screen.getByLabelText("Save without linking"));

      await fireEvent.click(screen.getByLabelText("Save without linking"));

      await waitFor(() => {
        const calls = mockCallTool.mock.calls as Array<
          [string, Record<string, unknown>]
        >;
        const storeCalls = calls.filter(([name]) => name === "store");
        expect(storeCalls).toHaveLength(1);
      });
    });
  });

  describe("save flow", () => {
    it("calls store with correct parameters", async () => {
      vi.useRealTimers();
      const mockCallTool = vi
        .fn()
        .mockResolvedValue(makeResult('{"id": "abc-123"}'));

      const bridge = {
        isConnected: true,
        callTool: mockCallTool,
      } as unknown as McpBridge;

      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });

      const tagsInput = screen.getByLabelText("Bookmark tags");
      await fireEvent.input(tagsInput, { target: { value: "#rust #async" } });

      await fireEvent.click(screen.getByLabelText("Save"));

      await waitFor(() => {
        const calls = mockCallTool.mock.calls as Array<
          [string, Record<string, unknown>]
        >;
        const storeCalls = calls.filter(([name]) => name === "store");
        expect(storeCalls).toHaveLength(1);
        const [, args] = storeCalls[0]!;
        expect(args["content"]).toBe("https://example.com/article");
        expect(args["entry_type"]).toBe("bookmark");
        expect(args["source"]).toBe("claude-code");
        expect(args["tags"]).toEqual(["rust", "async"]);
      });
    });

    it("shows success toast with entry ID after save", async () => {
      vi.useRealTimers();
      const entryId = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";
      const bridge = makeMockBridge(
        async () => makeResult(`Stored entry id: ${entryId}`),
      );
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });
      await fireEvent.click(screen.getByLabelText("Save"));

      await waitFor(() => {
        expect(screen.getByTestId("success-toast")).toBeTruthy();
        expect(screen.getByText(new RegExp(`Bookmark saved: ${entryId}`))).toBeTruthy();
      });
    });

    it("success toast contains View entry link", async () => {
      vi.useRealTimers();
      const entryId = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";
      const bridge = makeMockBridge(
        async () => makeResult(`Stored entry id: ${entryId}`),
      );
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });
      await fireEvent.click(screen.getByLabelText("Save"));

      await waitFor(() => {
        expect(screen.getByText("View entry")).toBeTruthy();
      });
    });

    it("success toast auto-dismisses after 5 seconds", async () => {
      // Use fake timers but allow promises to resolve
      vi.useFakeTimers();
      const entryId = "a1b2c3d4-e5f6-7890-abcd-ef1234567890";

      let resolveStore!: (v: ToolCallTextResult) => void;
      const storePromise = new Promise<ToolCallTextResult>((res) => {
        resolveStore = res;
      });
      const mockCallTool = vi.fn().mockReturnValue(storePromise);
      const bridge = {
        isConnected: true,
        callTool: mockCallTool,
      } as unknown as McpBridge;

      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });
      await fireEvent.click(screen.getByLabelText("Save"));

      // Resolve the store call
      resolveStore(makeResult(`Stored entry id: ${entryId}`));
      // Flush microtasks so the component processes the resolved promise
      await vi.advanceTimersByTimeAsync(250);

      expect(screen.getByTestId("success-toast")).toBeTruthy();

      // Advance past the 5s auto-dismiss
      await vi.advanceTimersByTimeAsync(5000);

      expect(screen.queryByTestId("success-toast")).toBeNull();
      vi.useRealTimers();
    });
  });

  describe("form clear after save", () => {
    it("clears URL and tags inputs after successful save", async () => {
      vi.useRealTimers();
      const bridge = makeMockBridge(
        async () => makeResult('{"id": "abc-123"}'),
      );
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL") as HTMLInputElement;
      const tagsInput = screen.getByLabelText("Bookmark tags") as HTMLInputElement;

      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });
      await fireEvent.input(tagsInput, { target: { value: "#rust" } });
      await fireEvent.click(screen.getByLabelText("Save"));

      await waitFor(() => {
        expect(urlInput.value).toBe("");
        expect(tagsInput.value).toBe("");
      });
    });

    it("hides dedup results after successful save", async () => {
      vi.useRealTimers();
      // First call: find_similar returns empty (no dupes), second: store succeeds
      const mockCallTool = vi
        .fn()
        .mockResolvedValueOnce(makeResult("")) // find_similar
        .mockResolvedValueOnce(makeResult('{"id": "abc-123"}')); // store

      const bridge = {
        isConnected: true,
        callTool: mockCallTool,
      } as unknown as McpBridge;

      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });

      // Run dedup check first
      await fireEvent.click(screen.getByLabelText("Check for duplicates"));
      await waitFor(() => screen.getByTestId("dedup-results"));

      // Now save
      await fireEvent.click(screen.getByLabelText("Save"));

      await waitFor(() => {
        expect(screen.queryByTestId("dedup-results")).toBeNull();
      });
    });
  });

  describe("loading states", () => {
    it("shows loading indicator during dedup check", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });
      await fireEvent.click(screen.getByLabelText("Check for duplicates"));

      expect(screen.getByText("Checking...")).toBeTruthy();

      // Resolve to avoid dangling promise
      resolveCall(makeResult(""));
    });

    it("shows loading indicator during save", async () => {
      let resolveCall!: (v: ToolCallTextResult) => void;
      const pending = new Promise<ToolCallTextResult>((res) => {
        resolveCall = res;
      });
      const bridge = makeMockBridge(() => pending);
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });
      await fireEvent.click(screen.getByLabelText("Save"));

      expect(screen.getByText("Saving...")).toBeTruthy();

      // Resolve to avoid dangling promise
      resolveCall(makeResult(""));
    });
  });

  describe("error handling", () => {
    it("shows error banner when dedup check fails", async () => {
      vi.useRealTimers();
      const bridge = makeMockBridge(async () =>
        makeResult("Connection error", true),
      );
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });
      await fireEvent.click(screen.getByLabelText("Check for duplicates"));

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
      });
    });

    it("shows error banner when save fails", async () => {
      vi.useRealTimers();
      const bridge = makeMockBridge(async () =>
        makeResult("Store error", true),
      );
      render(BookmarkCapture, { props: { bridge } });

      const urlInput = screen.getByLabelText("Bookmark URL");
      await fireEvent.input(urlInput, {
        target: { value: "https://example.com/article" },
      });
      await fireEvent.click(screen.getByLabelText("Save"));

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeTruthy();
      });
    });
  });

  describe("no bridge", () => {
    it("renders without crashing when bridge is null", () => {
      expect(
        () => render(BookmarkCapture, { props: { bridge: null } }),
      ).not.toThrow();
    });
  });
});
