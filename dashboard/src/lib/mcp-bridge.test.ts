import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { McpBridge, McpBridgeError, DEFAULT_TIMEOUT_MS, callTool } from "./mcp-bridge";

// Mock the @modelcontextprotocol/ext-apps module
vi.mock("@modelcontextprotocol/ext-apps", () => {
  const MockApp = vi.fn().mockImplementation(() => ({
    connect: vi.fn().mockResolvedValue(undefined),
    callServerTool: vi.fn().mockResolvedValue({
      content: [{ type: "text", text: "mock result" }],
      isError: false,
    }),
    close: vi.fn().mockResolvedValue(undefined),
  }));

  const MockPostMessageTransport = vi.fn().mockImplementation(() => ({}));

  return {
    App: MockApp,
    PostMessageTransport: MockPostMessageTransport,
  };
});

describe("McpBridge", () => {
  let bridge: McpBridge;

  beforeEach(() => {
    vi.clearAllMocks();
    bridge = new McpBridge();
  });

  afterEach(async () => {
    if (bridge.isConnected) {
      await bridge.disconnect();
    }
  });

  describe("constructor", () => {
    it("creates bridge with default options", () => {
      expect(bridge.isConnected).toBe(false);
      expect(bridge.appInstance).toBeDefined();
    });

    it("accepts custom options", () => {
      const custom = new McpBridge({
        appName: "TestApp",
        appVersion: "2.0.0",
        timeoutMs: 5000,
      });
      expect(custom.isConnected).toBe(false);
    });
  });

  describe("connect", () => {
    it("connects to the host via postMessage transport", async () => {
      await bridge.connect();
      expect(bridge.isConnected).toBe(true);
      expect(bridge.appInstance.connect).toHaveBeenCalledTimes(1);
    });

    it("is idempotent when already connected", async () => {
      await bridge.connect();
      await bridge.connect();
      expect(bridge.appInstance.connect).toHaveBeenCalledTimes(1);
    });

    it("deduplicates concurrent connect calls", async () => {
      const p1 = bridge.connect();
      const p2 = bridge.connect();
      await Promise.all([p1, p2]);
      expect(bridge.appInstance.connect).toHaveBeenCalledTimes(1);
    });

    it("throws McpBridgeError on connection failure", async () => {
      const failBridge = new McpBridge();
      vi.mocked(failBridge.appInstance.connect).mockRejectedValue(
        new Error("connection refused"),
      );

      await expect(failBridge.connect()).rejects.toThrow(McpBridgeError);
      expect(failBridge.isConnected).toBe(false);

      const error = await failBridge.connect().catch((e: unknown) => e);
      expect(error).toBeInstanceOf(McpBridgeError);
      expect((error as McpBridgeError).message).toContain("Failed to connect to MCP host");
    });

    it("allows retry after connection failure", async () => {
      vi.mocked(bridge.appInstance.connect)
        .mockRejectedValueOnce(new Error("transient error"))
        .mockResolvedValueOnce(undefined);

      await expect(bridge.connect()).rejects.toThrow(McpBridgeError);
      expect(bridge.isConnected).toBe(false);

      await bridge.connect();
      expect(bridge.isConnected).toBe(true);
    });

    it("rejects with McpBridgeError when connect() times out", async () => {
      vi.useFakeTimers();

      // Make app.connect() hang indefinitely
      vi.mocked(bridge.appInstance.connect).mockImplementationOnce(
        () => new Promise<void>(() => {}),
      );

      const timeoutBridge = new McpBridge({ timeoutMs: 1000 });
      // Replace the app instance's connect with the hanging mock
      vi.mocked(timeoutBridge.appInstance.connect).mockImplementationOnce(
        () => new Promise<void>(() => {}),
      );

      const connectPromise = timeoutBridge.connect();
      vi.advanceTimersByTime(1001);
      const error = await connectPromise.catch((e: unknown) => e);

      expect(error).toBeInstanceOf(McpBridgeError);
      expect((error as McpBridgeError).message).toContain("timed out");
      expect(timeoutBridge.isConnected).toBe(false);

      vi.useRealTimers();
    });
  });

  describe("callTool", () => {
    beforeEach(async () => {
      await bridge.connect();
    });

    it("calls tool and returns parsed text result", async () => {
      const result = await bridge.callTool("list", { output: "stats" });
      expect(result.text).toBe("mock result");
      expect(result.isError).toBe(false);
      expect(result.raw).toBeDefined();
      expect(bridge.appInstance.callServerTool).toHaveBeenCalledWith(
        { name: "list", arguments: { output: "stats" } },
        { timeout: DEFAULT_TIMEOUT_MS },
      );
    });

    it("calls tool without arguments", async () => {
      const result = await bridge.callTool("status");
      expect(result.text).toBe("mock result");
      expect(bridge.appInstance.callServerTool).toHaveBeenCalledWith(
        { name: "status", arguments: undefined },
        { timeout: DEFAULT_TIMEOUT_MS },
      );
    });

    it("concatenates multiple text blocks", async () => {
      vi.mocked(bridge.appInstance.callServerTool).mockResolvedValueOnce({
        content: [
          { type: "text", text: "line 1" },
          { type: "text", text: "line 2" },
          { type: "text", text: "line 3" },
        ],
      });
      const result = await bridge.callTool("list");
      expect(result.text).toBe("line 1\nline 2\nline 3");
    });

    it("filters out non-text content blocks", async () => {
      vi.mocked(bridge.appInstance.callServerTool).mockResolvedValueOnce({
        content: [
          { type: "text", text: "text content" },
          { type: "image", data: "base64data", mimeType: "image/png" },
        ],
      });
      const result = await bridge.callTool("list");
      expect(result.text).toBe("text content");
    });

    it("returns empty string when no text content", async () => {
      vi.mocked(bridge.appInstance.callServerTool).mockResolvedValueOnce({
        content: [],
      });
      const result = await bridge.callTool("list");
      expect(result.text).toBe("");
    });

    it("handles content being undefined", async () => {
      vi.mocked(bridge.appInstance.callServerTool).mockResolvedValueOnce({
        content: undefined as unknown as [],
      });
      const result = await bridge.callTool("list");
      expect(result.text).toBe("");
    });

    it("reports isError when tool returns error flag", async () => {
      vi.mocked(bridge.appInstance.callServerTool).mockResolvedValueOnce({
        content: [{ type: "text", text: "something went wrong" }],
        isError: true,
      });
      const result = await bridge.callTool("list");
      expect(result.isError).toBe(true);
      expect(result.text).toBe("something went wrong");
    });

    it("throws McpBridgeError when not connected", async () => {
      const disconnectedBridge = new McpBridge();
      await expect(disconnectedBridge.callTool("list")).rejects.toThrow(McpBridgeError);
      await expect(disconnectedBridge.callTool("list")).rejects.toThrow(
        "Bridge not connected",
      );
    });

    it("wraps timeout errors in McpBridgeError", async () => {
      vi.mocked(bridge.appInstance.callServerTool).mockRejectedValueOnce(
        new Error("Request timed out"),
      );
      const error = await bridge.callTool("slow_tool").catch((e: unknown) => e);
      expect(error).toBeInstanceOf(McpBridgeError);
      expect((error as McpBridgeError).message).toContain("timed out");
      expect((error as McpBridgeError).message).toContain("slow_tool");
    });

    it("wraps generic errors in McpBridgeError", async () => {
      vi.mocked(bridge.appInstance.callServerTool).mockRejectedValueOnce(
        new Error("unknown failure"),
      );
      const error = await bridge.callTool("broken").catch((e: unknown) => e);
      expect(error).toBeInstanceOf(McpBridgeError);
      expect((error as McpBridgeError).message).toContain('Tool call "broken" failed');
    });

    it("handles non-Error thrown values", async () => {
      vi.mocked(bridge.appInstance.callServerTool).mockRejectedValueOnce("string error");
      const error = await bridge.callTool("broken").catch((e: unknown) => e);
      expect(error).toBeInstanceOf(McpBridgeError);
      expect((error as McpBridgeError).message).toContain("string error");
    });

    it("uses custom timeout from constructor options", async () => {
      const customBridge = new McpBridge({ timeoutMs: 5000 });
      await customBridge.connect();
      await customBridge.callTool("list");
      expect(customBridge.appInstance.callServerTool).toHaveBeenCalledWith(
        { name: "list", arguments: undefined },
        { timeout: 5000 },
      );
    });
  });

  describe("disconnect", () => {
    it("disconnects and resets state", async () => {
      await bridge.connect();
      expect(bridge.isConnected).toBe(true);

      await bridge.disconnect();
      expect(bridge.isConnected).toBe(false);
      expect(bridge.appInstance.close).toHaveBeenCalledTimes(1);
    });

    it("is safe to call when not connected", async () => {
      await bridge.disconnect();
      expect(bridge.isConnected).toBe(false);
    });

    it("prevents tool calls after disconnect", async () => {
      await bridge.connect();
      await bridge.disconnect();
      await expect(bridge.callTool("list")).rejects.toThrow("Bridge not connected");
    });

    it("allows reconnect after disconnect", async () => {
      await bridge.connect();
      await bridge.disconnect();
      await bridge.connect();
      expect(bridge.isConnected).toBe(true);
    });
  });

  describe("callTool convenience function", () => {
    it("delegates to bridge.callTool", async () => {
      await bridge.connect();
      const result = await callTool(bridge, "list", { output: "stats" });
      expect(result.text).toBe("mock result");
    });
  });
});

describe("McpBridgeError", () => {
  it("has correct name property", () => {
    const error = new McpBridgeError("test");
    expect(error.name).toBe("McpBridgeError");
  });

  it("defaults isToolError to false", () => {
    const error = new McpBridgeError("test");
    expect(error.isToolError).toBe(false);
  });

  it("accepts isToolError option", () => {
    const error = new McpBridgeError("test", { isToolError: true });
    expect(error.isToolError).toBe(true);
  });

  it("preserves cause", () => {
    const cause = new Error("original");
    const error = new McpBridgeError("wrapped", { cause });
    expect(error.cause).toBe(cause);
  });

  it("is an instance of Error", () => {
    const error = new McpBridgeError("test");
    expect(error).toBeInstanceOf(Error);
  });
});

describe("DEFAULT_TIMEOUT_MS", () => {
  it("is 30 seconds", () => {
    expect(DEFAULT_TIMEOUT_MS).toBe(30_000);
  });
});
