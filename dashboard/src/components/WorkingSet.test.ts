/**
 * WorkingSet.test.ts
 *
 * Tests for:
 *  - workingSet store: pin/unpin, duplicate prevention, reorder, clear
 *  - sessionStorage persistence
 *  - WorkingSet.svelte component: rendering, badges, DnD, confirmation flow
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/svelte";
import { get } from "svelte/store";
import {
  workingSet,
  pinEntry,
  unpinEntry,
  isEntryPinned,
  clearWorkingSet,
  reorderEntries,
  type PinnedEntry,
} from "$lib/stores";
import WorkingSet from "./WorkingSet.svelte";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeEntry(overrides: Partial<PinnedEntry> = {}): PinnedEntry {
  return {
    id: `id-${Math.random().toString(36).slice(2)}`,
    title: "Test Entry Title",
    type: "knowledge",
    content: "Test entry content.",
    pinnedAt: new Date().toISOString(),
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// sessionStorage mock
// ---------------------------------------------------------------------------

const sessionStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

beforeEach(() => {
  // Reset store and sessionStorage before each test.
  vi.stubGlobal("sessionStorage", sessionStorageMock);
  sessionStorageMock.clear();
  clearWorkingSet();
  vi.stubGlobal("console", { ...console, warn: vi.fn(), error: vi.fn() });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Store tests
// ---------------------------------------------------------------------------

describe("workingSet store", () => {
  describe("pinEntry", () => {
    it("adds an entry to the working set", () => {
      const entry = makeEntry({ title: "My first entry" });
      pinEntry(entry);
      expect(get(workingSet)).toHaveLength(1);
      expect(get(workingSet)[0].id).toBe(entry.id);
    });

    it("prevents duplicate entries (same id is ignored)", () => {
      const entry = makeEntry({ id: "fixed-id" });
      pinEntry(entry);
      pinEntry(entry);
      expect(get(workingSet)).toHaveLength(1);
    });

    it("appends multiple distinct entries in order", () => {
      const a = makeEntry({ id: "a", title: "Alpha" });
      const b = makeEntry({ id: "b", title: "Beta" });
      pinEntry(a);
      pinEntry(b);
      const ws = get(workingSet);
      expect(ws).toHaveLength(2);
      expect(ws[0].id).toBe("a");
      expect(ws[1].id).toBe("b");
    });

    it("assigns pinnedAt timestamp if not provided", () => {
      const entry = makeEntry({ pinnedAt: "" });
      pinEntry(entry);
      const pinned = get(workingSet)[0];
      expect(pinned.pinnedAt).toBeTruthy();
      expect(() => new Date(pinned.pinnedAt)).not.toThrow();
    });
  });

  describe("unpinEntry", () => {
    it("removes an entry by id", () => {
      const entry = makeEntry({ id: "remove-me" });
      pinEntry(entry);
      unpinEntry("remove-me");
      expect(get(workingSet)).toHaveLength(0);
    });

    it("is a no-op for unknown ids", () => {
      const entry = makeEntry({ id: "keep-me" });
      pinEntry(entry);
      unpinEntry("nonexistent");
      expect(get(workingSet)).toHaveLength(1);
    });

    it("only removes the targeted entry when multiple entries are present", () => {
      const a = makeEntry({ id: "a" });
      const b = makeEntry({ id: "b" });
      const c = makeEntry({ id: "c" });
      pinEntry(a);
      pinEntry(b);
      pinEntry(c);
      unpinEntry("b");
      const ws = get(workingSet);
      expect(ws).toHaveLength(2);
      expect(ws.map((e) => e.id)).toEqual(["a", "c"]);
    });
  });

  describe("isEntryPinned", () => {
    it("returns true when entry is in the set", () => {
      const entry = makeEntry({ id: "pinned-id" });
      pinEntry(entry);
      expect(isEntryPinned("pinned-id", get(workingSet))).toBe(true);
    });

    it("returns false when entry is not in the set", () => {
      expect(isEntryPinned("absent-id", get(workingSet))).toBe(false);
    });

    it("returns false after unpinning", () => {
      const entry = makeEntry({ id: "was-pinned" });
      pinEntry(entry);
      unpinEntry("was-pinned");
      expect(isEntryPinned("was-pinned", get(workingSet))).toBe(false);
    });
  });

  describe("clearWorkingSet", () => {
    it("removes all entries", () => {
      pinEntry(makeEntry());
      pinEntry(makeEntry());
      clearWorkingSet();
      expect(get(workingSet)).toHaveLength(0);
    });

    it("is safe to call on an already-empty set", () => {
      expect(() => clearWorkingSet()).not.toThrow();
      expect(get(workingSet)).toHaveLength(0);
    });
  });

  describe("reorderEntries", () => {
    it("moves an entry from one index to another", () => {
      pinEntry(makeEntry({ id: "a" }));
      pinEntry(makeEntry({ id: "b" }));
      pinEntry(makeEntry({ id: "c" }));
      reorderEntries(0, 2); // move "a" to the end
      expect(get(workingSet).map((e) => e.id)).toEqual(["b", "c", "a"]);
    });

    it("is a no-op when fromIndex === toIndex", () => {
      pinEntry(makeEntry({ id: "a" }));
      pinEntry(makeEntry({ id: "b" }));
      reorderEntries(1, 1);
      expect(get(workingSet).map((e) => e.id)).toEqual(["a", "b"]);
    });

    it("is a no-op for out-of-range indices", () => {
      pinEntry(makeEntry({ id: "a" }));
      pinEntry(makeEntry({ id: "b" }));
      reorderEntries(-1, 1);
      reorderEntries(0, 99);
      expect(get(workingSet).map((e) => e.id)).toEqual(["a", "b"]);
    });

    it("supports moving from higher to lower index", () => {
      pinEntry(makeEntry({ id: "a" }));
      pinEntry(makeEntry({ id: "b" }));
      pinEntry(makeEntry({ id: "c" }));
      reorderEntries(2, 0); // move "c" to the front
      expect(get(workingSet).map((e) => e.id)).toEqual(["c", "a", "b"]);
    });
  });
});

// ---------------------------------------------------------------------------
// sessionStorage persistence tests
// ---------------------------------------------------------------------------

describe("sessionStorage persistence", () => {
  it("persists entries to sessionStorage on pin", () => {
    const entry = makeEntry({ id: "persist-me", title: "Persistent" });
    pinEntry(entry);
    const raw = sessionStorageMock.getItem("distillery.workingSet");
    expect(raw).not.toBeNull();
    const parsed: PinnedEntry[] = JSON.parse(raw!);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].id).toBe("persist-me");
  });

  it("removes entry from sessionStorage on unpin", () => {
    const entry = makeEntry({ id: "temp" });
    pinEntry(entry);
    unpinEntry("temp");
    const raw = sessionStorageMock.getItem("distillery.workingSet");
    const parsed: PinnedEntry[] = JSON.parse(raw!);
    expect(parsed).toHaveLength(0);
  });

  it("clears sessionStorage on clearWorkingSet", () => {
    pinEntry(makeEntry());
    clearWorkingSet();
    const raw = sessionStorageMock.getItem("distillery.workingSet");
    const parsed: PinnedEntry[] = JSON.parse(raw!);
    expect(parsed).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// WorkingSet.svelte component tests
// ---------------------------------------------------------------------------

describe("WorkingSet component", () => {
  const noop = () => {};

  function renderWS(entries: PinnedEntry[] = [], overrides: Partial<{
    onRemove: (id: string) => void;
    onReorder: (from: number, to: number) => void;
    onExport: () => void;
    onClear: () => void;
  }> = {}) {
    return render(WorkingSet, {
      props: {
        entries,
        onRemove: overrides.onRemove ?? noop,
        onReorder: overrides.onReorder ?? noop,
        onExport: overrides.onExport ?? noop,
        onClear: overrides.onClear ?? noop,
      },
    });
  }

  describe("rendering", () => {
    it("renders without crashing with empty entries", () => {
      expect(() => renderWS([])).not.toThrow();
    });

    it("shows 'Working Set' text in the toggle button", () => {
      renderWS([]);
      expect(screen.getByText("Working Set")).toBeTruthy();
    });

    it("shows count badge with 0 when empty", () => {
      renderWS([]);
      // aria-label on badge
      expect(screen.getByLabelText("0 entries")).toBeTruthy();
    });

    it("shows count badge with correct count when entries present", () => {
      const entries = [makeEntry(), makeEntry()];
      renderWS(entries);
      expect(screen.getByLabelText("2 entries")).toBeTruthy();
    });

    it("toggle button has aria-expanded=false when collapsed", () => {
      renderWS([]);
      const btn = screen.getByRole("button", { name: /Working Set \(0\)/i });
      expect(btn.getAttribute("aria-expanded")).toBe("false");
    });

    it("toggle button is disabled when entries list is empty", () => {
      renderWS([]);
      const btn = screen.getByRole("button", { name: /Working Set \(0\)/i });
      expect((btn as HTMLButtonElement).disabled).toBe(true);
    });
  });

  describe("expand/collapse", () => {
    it("expands panel when toggle clicked with entries present", async () => {
      const entries = [makeEntry({ title: "Svelte Entry" })];
      renderWS(entries);
      const btn = screen.getByRole("button", { name: /Working Set \(1\)/i });
      // Initially expanded (because entries.length > 0 and it's initialized to true)
      // The panel body should be visible
      expect(screen.getByRole("list", { name: "Pinned entries" })).toBeTruthy();
    });

    it("collapses panel when toggle clicked again", async () => {
      const entries = [makeEntry({ title: "Some Entry" })];
      renderWS(entries);
      const btn = screen.getByRole("button", { name: /Working Set \(1\)/i });
      // Click once to collapse
      fireEvent.click(btn);
      expect(screen.queryByRole("list", { name: "Pinned entries" })).toBeNull();
    });

    it("shows entry cards when expanded", () => {
      const entries = [
        makeEntry({ id: "e1", title: "Alpha Entry", type: "knowledge" }),
        makeEntry({ id: "e2", title: "Beta Entry", type: "note" }),
      ];
      renderWS(entries);
      expect(screen.getByText("Alpha Entry")).toBeTruthy();
      expect(screen.getByText("Beta Entry")).toBeTruthy();
    });

    it("shows type badge on each card", () => {
      const entries = [makeEntry({ type: "bookmark", title: "Bookmarked" })];
      renderWS(entries);
      expect(screen.getByText("bookmark")).toBeTruthy();
    });

    it("shows Export and Clear all buttons when expanded with entries", () => {
      const entries = [makeEntry()];
      renderWS(entries);
      expect(screen.getByRole("button", { name: "Export working set" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "Clear all entries" })).toBeTruthy();
    });
  });

  describe("remove entry", () => {
    it("calls onRemove with the entry id when remove button is clicked", () => {
      const onRemove = vi.fn();
      const entry = makeEntry({ id: "target-id", title: "To Remove" });
      renderWS([entry], { onRemove });
      const removeBtn = screen.getByRole("button", { name: /Remove To Remove/ });
      fireEvent.click(removeBtn);
      expect(onRemove).toHaveBeenCalledWith("target-id");
    });

    it("renders remove button for each entry", () => {
      const entries = [
        makeEntry({ title: "First" }),
        makeEntry({ title: "Second" }),
      ];
      renderWS(entries);
      const removeBtns = screen.getAllByRole("button", { name: /Remove/ });
      expect(removeBtns).toHaveLength(2);
    });
  });

  describe("clear all with confirmation", () => {
    it("shows confirmation prompt when Clear all is clicked", async () => {
      const entries = [makeEntry()];
      renderWS(entries);
      const clearBtn = screen.getByRole("button", { name: "Clear all entries" });
      fireEvent.click(clearBtn);
      expect(screen.getByText("Clear all?")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Confirm clear all" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "Cancel clear" })).toBeTruthy();
    });

    it("calls onClear when Yes is clicked after confirmation prompt", async () => {
      const onClear = vi.fn();
      const entries = [makeEntry()];
      renderWS(entries, { onClear });
      const clearBtn = screen.getByRole("button", { name: "Clear all entries" });
      fireEvent.click(clearBtn);
      const yesBtn = screen.getByRole("button", { name: "Confirm clear all" });
      fireEvent.click(yesBtn);
      expect(onClear).toHaveBeenCalledOnce();
    });

    it("does not call onClear when No is clicked", async () => {
      const onClear = vi.fn();
      const entries = [makeEntry()];
      renderWS(entries, { onClear });
      fireEvent.click(screen.getByRole("button", { name: "Clear all entries" }));
      fireEvent.click(screen.getByRole("button", { name: "Cancel clear" }));
      expect(onClear).not.toHaveBeenCalled();
    });

    it("hides confirmation prompt when No is clicked", async () => {
      const entries = [makeEntry()];
      renderWS(entries);
      fireEvent.click(screen.getByRole("button", { name: "Clear all entries" }));
      fireEvent.click(screen.getByRole("button", { name: "Cancel clear" }));
      expect(screen.queryByText("Clear all?")).toBeNull();
      // Clear all button should be back
      expect(screen.getByRole("button", { name: "Clear all entries" })).toBeTruthy();
    });
  });

  describe("export", () => {
    it("calls onExport when Export is clicked", () => {
      const onExport = vi.fn();
      renderWS([makeEntry()], { onExport });
      fireEvent.click(screen.getByRole("button", { name: "Export working set" }));
      expect(onExport).toHaveBeenCalledOnce();
    });
  });

  describe("drag-and-drop", () => {
    it("calls onReorder when a card is dragged and dropped to a new index", () => {
      const onReorder = vi.fn();
      const entries = [
        makeEntry({ id: "a", title: "Alpha" }),
        makeEntry({ id: "b", title: "Beta" }),
      ];
      renderWS(entries, { onReorder });

      const cards = screen.getAllByRole("listitem");
      // Simulate dragging card 0 to card 1
      fireEvent.dragStart(cards[0]);
      fireEvent.dragOver(cards[1]);
      fireEvent.drop(cards[1]);

      expect(onReorder).toHaveBeenCalledWith(0, 1);
    });

    it("does not call onReorder when dragged to the same index", () => {
      const onReorder = vi.fn();
      const entries = [makeEntry({ id: "a", title: "Alpha" })];
      renderWS(entries, { onReorder });

      const card = screen.getByRole("listitem");
      fireEvent.dragStart(card);
      fireEvent.dragOver(card);
      fireEvent.drop(card);

      expect(onReorder).not.toHaveBeenCalled();
    });

    it("cards have draggable attribute", () => {
      const entries = [makeEntry({ title: "Draggable" })];
      renderWS(entries);
      const card = screen.getByRole("listitem");
      expect(card.getAttribute("draggable")).toBe("true");
    });
  });
});
