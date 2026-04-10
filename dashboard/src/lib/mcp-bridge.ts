/**
 * MCP Apps postMessage/JSON-RPC bridge.
 *
 * Wraps the @modelcontextprotocol/ext-apps App class to provide a simplified
 * interface for Svelte components to call Distillery MCP tools and receive
 * responses. Handles connection lifecycle, request timeouts, and error mapping.
 */

import { App, PostMessageTransport } from "@modelcontextprotocol/ext-apps";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";

/** Default timeout for tool calls in milliseconds. */
export const DEFAULT_TIMEOUT_MS = 30_000;

/** Error thrown when a tool call fails. */
export class McpBridgeError extends Error {
  /** Whether the error originated from the MCP tool (vs transport/timeout). */
  public readonly isToolError: boolean;

  constructor(message: string, options?: { isToolError?: boolean; cause?: unknown }) {
    super(message, { cause: options?.cause });
    this.name = "McpBridgeError";
    this.isToolError = options?.isToolError ?? false;
  }
}

/** Parsed text content from a tool call result. */
export interface ToolCallTextResult {
  /** Concatenated text content from the tool response. */
  text: string;
  /** Whether the tool reported an error via isError flag. */
  isError: boolean;
  /** The raw CallToolResult for advanced consumers. */
  raw: CallToolResult;
}

/**
 * Options for configuring the MCP bridge.
 */
export interface McpBridgeOptions {
  /** App name reported during initialization. Defaults to "Distillery Dashboard". */
  appName?: string;
  /** App version reported during initialization. Defaults to "0.1.0". */
  appVersion?: string;
  /** Default timeout in ms for tool calls. Defaults to DEFAULT_TIMEOUT_MS. */
  timeoutMs?: number;
}

/**
 * MCP Apps bridge for the Distillery dashboard.
 *
 * Manages the App instance lifecycle and provides a simple callTool interface
 * for Svelte components.
 */
export class McpBridge {
  private app: App;
  private connected = false;
  private connectPromise: Promise<void> | null = null;
  private readonly timeoutMs: number;

  constructor(options?: McpBridgeOptions) {
    this.timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.app = new App(
      {
        name: options?.appName ?? "Distillery Dashboard",
        version: options?.appVersion ?? "0.1.0",
      },
      {},
    );
  }

  /** Whether the bridge is currently connected to the host. */
  get isConnected(): boolean {
    return this.connected;
  }

  /** The underlying App instance for advanced usage. */
  get appInstance(): App {
    return this.app;
  }

  /**
   * Connect to the MCP host via postMessage transport.
   *
   * Uses window.parent as the transport target (iframe to host communication).
   * Safe to call multiple times; subsequent calls return the same promise.
   *
   * @param transport - Optional custom transport (for testing). Defaults to PostMessageTransport.
   * @throws McpBridgeError if connection fails.
   */
  async connect(transport?: PostMessageTransport): Promise<void> {
    if (this.connected) return;
    if (this.connectPromise) return this.connectPromise;

    this.connectPromise = this._doConnect(transport);
    try {
      await this.connectPromise;
    } catch (error) {
      this.connectPromise = null;
      throw error;
    }
  }

  private async _doConnect(transport?: PostMessageTransport): Promise<void> {
    const t = transport ?? new PostMessageTransport(window.parent, window.parent);

    let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
    const timeoutPromise = new Promise<never>((_, reject) => {
      timeoutHandle = setTimeout(() => {
        reject(
          new McpBridgeError(`connect() timed out after ${this.timeoutMs}ms`),
        );
      }, this.timeoutMs);
    });

    try {
      await Promise.race([this.app.connect(t), timeoutPromise]);
      this.connected = true;
    } catch (error) {
      if (error instanceof McpBridgeError) throw error;
      throw new McpBridgeError("Failed to connect to MCP host", { cause: error });
    } finally {
      clearTimeout(timeoutHandle);
    }
  }

  /**
   * Call a Distillery MCP tool by name.
   *
   * This is the primary interface for Svelte components. It abstracts the
   * postMessage protocol, handles timeouts, and maps errors to McpBridgeError.
   *
   * @param name - The MCP tool name (e.g. "list", "store", "recall").
   * @param args - Tool arguments as a plain object.
   * @returns Parsed text result with convenience accessors.
   * @throws McpBridgeError on connection, timeout, or tool errors.
   */
  async callTool(
    name: string,
    args?: Record<string, unknown>,
  ): Promise<ToolCallTextResult> {
    if (!this.connected) {
      throw new McpBridgeError("Bridge not connected. Call connect() first.");
    }

    try {
      const result = await this.app.callServerTool(
        { name, arguments: args },
        { timeout: this.timeoutMs },
      );

      const text = (result.content ?? [])
        .filter((block): block is { type: "text"; text: string } => block.type === "text")
        .map((block) => block.text)
        .join("\n");

      return {
        text,
        isError: result.isError ?? false,
        raw: result,
      };
    } catch (error) {
      if (error instanceof Error && error.message.includes("timed out")) {
        throw new McpBridgeError(
          `Tool call "${name}" timed out after ${this.timeoutMs}ms`,
          { cause: error },
        );
      }
      throw new McpBridgeError(
        `Tool call "${name}" failed: ${error instanceof Error ? error.message : String(error)}`,
        { cause: error },
      );
    }
  }

  /**
   * Disconnect from the MCP host.
   *
   * Closes the underlying transport. After disconnect, connect() must be
   * called again before making tool calls.
   */
  async disconnect(): Promise<void> {
    if (!this.connected) return;
    try {
      await this.app.close();
    } finally {
      this.connected = false;
      this.connectPromise = null;
    }
  }
}

/**
 * Convenience function to call a tool without managing bridge lifecycle.
 *
 * For one-off calls in simple scenarios. Most components should use the
 * McpBridge class directly for connection reuse.
 */
export async function callTool(
  bridge: McpBridge,
  name: string,
  args?: Record<string, unknown>,
): Promise<ToolCallTextResult> {
  return bridge.callTool(name, args);
}
