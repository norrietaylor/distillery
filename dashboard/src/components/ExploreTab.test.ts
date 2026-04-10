/**
 * ExploreTab.test.ts
 *
 * Tests for:
 *  - WorkingSet wiring in ExploreTab (entries passed, callbacks wired)
 *  - Export dialog: open/close, clipboard copy, download .md
 *  - Export markdown generation (title, type, content, separator)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import ExploreTab from "./ExploreTab.svelte";
import { clearWorkingSet, pinEntry, type PinnedEntry } from "$lib/stores";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePinned(overrides: Partial<PinnedEntry> = {}): PinnedEntry {
  return {
    id: `id-${Math.random().toString(36).slice(2)}`,
    title: "Test Pinned Entry",
    type: "note",
    content: "Content of the pinned entry.",
    pinnedAt: new Date().toISOString(),
    ...overrides,
  };
}

// sessionStorage mock
const sessionStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

beforeEach(() => {
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
  vi.stubGlobal("sessionStorage", sessionStorageMock);
  sessionStorageMock.clear();
  clearWorkingSet();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ExploreTab", () => {
  describe("rendering", () => {
    it("renders without crashing", () => {
      expect(() => render(ExploreTab, { props: { bridge: null } })).not.toThrow();
    });

    it("shows the search knowledge base heading", () => {
      render(ExploreTab, { props: { bridge: null } });
      expect(screen.getByText("Search Knowledge Base")).toBeTruthy();
    });

    it("renders the WorkingSet panel", () => {
      render(ExploreTab, { props: { bridge: null } });
      // WorkingSet toggle button is always present
      expect(screen.getByText("Working Set")).toBeTruthy();
    });
  });

  describe("WorkingSet integration", () => {
    it("shows pinned entry count in WorkingSet badge after pinning", async () => {
      render(ExploreTab, { props: { bridge: null } });

      // Initially 0 entries
      expect(screen.getByLabelText("0 entries")).toBeTruthy();

      // Pin an entry directly via store
      pinEntry(makePinned({ id: "explore-pin-1", title: "Explore Pin Entry" }));

      await waitFor(() => {
        expect(screen.getByLabelText("1 entries")).toBeTruthy();
      });
    });

    it("removes entry from WorkingSet when Remove is clicked", async () => {
      const entry = makePinned({ id: "explore-remove-1", title: "Entry to Remove" });
      // Pin before render so auto-expand fires
      pinEntry(entry);

      render(ExploreTab, { props: { bridge: null } });

      // Wait for the panel to auto-expand (entries.length > 0 on first render)
      await waitFor(() => screen.getByRole("button", { name: /Remove Entry to Remove/ }));
      fireEvent.click(screen.getByRole("button", { name: /Remove Entry to Remove/ }));

      await waitFor(() => {
        expect(screen.getByLabelText("0 entries")).toBeTruthy();
      });
    });
  });

  describe("export dialog", () => {
    /** Helper: pin entries before render, open working set, click Export. */
    async function openExportDialog(entry: PinnedEntry) {
      pinEntry(entry);
      render(ExploreTab, { props: { bridge: null } });

      // Auto-expand fires because entries present on first render
      await waitFor(() => screen.getByRole("button", { name: "Export working set" }));
      fireEvent.click(screen.getByRole("button", { name: "Export working set" }));

      await waitFor(() => screen.getByRole("dialog", { name: "Export working set" }));
    }

    it("opens export dialog when Export is clicked", async () => {
      await openExportDialog(makePinned({ id: "export-test-1", title: "Export Entry One" }));
      expect(screen.getByRole("dialog", { name: "Export working set" })).toBeTruthy();
    });

    it("shows exported markdown content in preview", async () => {
      await openExportDialog(makePinned({ id: "export-md-1", title: "MD Preview Entry", type: "note", content: "Preview content here." }));

      // Preview should contain title and content
      const dialog = screen.getByRole("dialog", { name: "Export working set" });
      expect(dialog.textContent).toContain("MD Preview Entry");
      expect(dialog.textContent).toContain("Preview content here.");
    });

    it("closes export dialog when close button is clicked", async () => {
      await openExportDialog(makePinned({ id: "export-close-1" }));
      fireEvent.click(screen.getByLabelText("Close export dialog"));

      await waitFor(() => {
        expect(screen.queryByRole("dialog", { name: "Export working set" })).toBeNull();
      });
    });

    it("shows Copy to Clipboard button in export dialog", async () => {
      await openExportDialog(makePinned({ id: "export-copy-1" }));
      expect(screen.getByLabelText("Copy to clipboard")).toBeTruthy();
    });

    it("shows Download .md button in export dialog", async () => {
      await openExportDialog(makePinned({ id: "export-dl-1" }));
      expect(screen.getByLabelText("Download as markdown")).toBeTruthy();
    });

    it("calls clipboard.writeText when Copy to Clipboard is clicked", async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      vi.stubGlobal("navigator", {
        ...navigator,
        clipboard: { writeText },
      });

      await openExportDialog(makePinned({ id: "export-clip-1", title: "Clipboard Entry", content: "Clip content." }));

      fireEvent.click(screen.getByLabelText("Copy to clipboard"));

      await waitFor(() => {
        expect(writeText).toHaveBeenCalledOnce();
        const arg: string = writeText.mock.calls[0][0] as string;
        expect(arg).toContain("Clipboard Entry");
        expect(arg).toContain("Clip content.");
      });
    });

    it("markdown export includes entry title, type, and content", async () => {
      const writeText = vi.fn().mockResolvedValue(undefined);
      vi.stubGlobal("navigator", {
        ...navigator,
        clipboard: { writeText },
      });

      await openExportDialog(makePinned({ id: "export-fmt-1", title: "Formatted Title", type: "knowledge", content: "Formatted content here." }));

      fireEvent.click(screen.getByLabelText("Copy to clipboard"));

      await waitFor(() => expect(writeText).toHaveBeenCalled());

      const md: string = writeText.mock.calls[0][0] as string;
      expect(md).toContain("## Formatted Title");
      expect(md).toContain("**Type:** knowledge");
      expect(md).toContain("Formatted content here.");
      expect(md).toContain("---");
    });
  });
});
