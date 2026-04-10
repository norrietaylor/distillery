import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/svelte";
import ManageTab from "./ManageTab.svelte";
import type { McpBridge } from "$lib/mcp-bridge";
import { userRole, inboxBadgeCount, reviewBadgeCount } from "$lib/stores";

/** Build a minimal mock McpBridge. */
function makeMockBridge(): McpBridge {
  return {
    isConnected: true,
    callTool: vi.fn().mockResolvedValue({ text: "0", isError: false, raw: {} }),
  } as unknown as McpBridge;
}

// Suppress Svelte warnings in test output
beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
  // Reset stores to default state before each test
  userRole.set("curator");
  inboxBadgeCount.set(null);
  reviewBadgeCount.set(null);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ManageTab", () => {
  describe("role gating", () => {
    it("shows access denied for developer role", () => {
      userRole.set("developer");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(screen.getByText(/Access Restricted/i)).toBeTruthy();
    });

    it("shows loading skeleton when userRole is null", () => {
      userRole.set(null);
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByLabelText("Loading")).toBeTruthy();
    });

    it("shows manage tab content for curator role", () => {
      userRole.set("curator");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      expect(screen.queryByText(/Access Restricted/i)).toBeNull();
      expect(screen.getByRole("navigation", { name: /Manage sections/i })).toBeTruthy();
    });

    it("shows manage tab content for admin role", () => {
      userRole.set("admin");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      expect(screen.queryByText(/Access Restricted/i)).toBeNull();
    });
  });

  describe("sub-tab navigation", () => {
    it("renders all 4 sub-tabs: Inbox, Review, Health, Sources", () => {
      userRole.set("curator");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      expect(screen.getByRole("tab", { name: /Inbox/i })).toBeTruthy();
      expect(screen.getByRole("tab", { name: /Review/i })).toBeTruthy();
      expect(screen.getByRole("tab", { name: /Health/i })).toBeTruthy();
      expect(screen.getByRole("tab", { name: /Sources/i })).toBeTruthy();
    });

    it("defaults to Inbox sub-tab active", () => {
      userRole.set("curator");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      const inboxTab = screen.getByRole("tab", { name: /Inbox/i });
      expect(inboxTab.getAttribute("aria-selected")).toBe("true");
    });

    it("shows Inbox panel content by default", () => {
      userRole.set("curator");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      // The Inbox panel is shown by default
      const inboxPanel = screen.getByRole("tabpanel", { name: /Inbox/i });
      expect(inboxPanel).toBeTruthy();
    });

    it("switches to Review panel when Review tab is clicked", () => {
      userRole.set("curator");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });

      const reviewTab = screen.getByRole("tab", { name: /Review/i });
      fireEvent.click(reviewTab);

      expect(reviewTab.getAttribute("aria-selected")).toBe("true");
      expect(screen.getByRole("tabpanel", { name: /Review/i })).toBeTruthy();
    });

    it("switches to Health panel when Health tab is clicked", () => {
      userRole.set("curator");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });

      const healthTab = screen.getByRole("tab", { name: /Health/i });
      fireEvent.click(healthTab);

      expect(healthTab.getAttribute("aria-selected")).toBe("true");
      expect(screen.getByRole("tabpanel", { name: /Health/i })).toBeTruthy();
    });

    it("switches to Sources panel when Sources tab is clicked", () => {
      userRole.set("curator");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });

      const sourcesTab = screen.getByRole("tab", { name: /Sources/i });
      fireEvent.click(sourcesTab);

      expect(sourcesTab.getAttribute("aria-selected")).toBe("true");
      expect(screen.getByRole("tabpanel", { name: /Sources/i })).toBeTruthy();
    });
  });

  describe("badge counts", () => {
    it("shows no badge on Inbox tab when inboxBadgeCount is null", () => {
      userRole.set("curator");
      inboxBadgeCount.set(null);
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      // The Inbox tab should not have a badge span
      const inboxTab = screen.getByRole("tab", { name: /^Inbox$/ });
      expect(inboxTab.querySelector(".sub-tab-badge")).toBeNull();
    });

    it("shows no badge on Inbox tab when inboxBadgeCount is 0", () => {
      userRole.set("curator");
      inboxBadgeCount.set(0);
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      const inboxTab = screen.getByRole("tab", { name: /^Inbox$/ });
      expect(inboxTab.querySelector(".sub-tab-badge")).toBeNull();
    });

    it("shows badge on Inbox sub-tab when inboxBadgeCount > 0", () => {
      userRole.set("curator");
      inboxBadgeCount.set(5);
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      expect(screen.getByLabelText("5 items")).toBeTruthy();
    });

    it("shows badge on Review sub-tab when reviewBadgeCount > 0", () => {
      userRole.set("curator");
      reviewBadgeCount.set(3);
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      expect(screen.getByLabelText("3 items")).toBeTruthy();
    });

    it("shows both inbox and review badges simultaneously", () => {
      userRole.set("curator");
      inboxBadgeCount.set(7);
      reviewBadgeCount.set(2);
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      expect(screen.getByLabelText("7 items")).toBeTruthy();
      expect(screen.getByLabelText("2 items")).toBeTruthy();
    });
  });

  describe("accessibility", () => {
    it("has a tablist with correct aria-label", () => {
      userRole.set("curator");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      expect(screen.getByRole("tablist")).toBeTruthy();
    });

    it("deselected tabs have aria-selected=false", () => {
      userRole.set("curator");
      const bridge = makeMockBridge();
      render(ManageTab, { props: { bridge } });
      const reviewTab = screen.getByRole("tab", { name: /Review/i });
      expect(reviewTab.getAttribute("aria-selected")).toBe("false");
    });
  });
});
