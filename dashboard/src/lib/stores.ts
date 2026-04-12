/**
 * Svelte stores for shared dashboard state.
 *
 * Provides reactive stores for project filter selection, refresh triggers,
 * user identity, configurable auto-refresh interval, tab selection, and
 * working set (pinned entries for comparison/export).
 */

import { writable, derived } from "svelte/store";

/** Tab types available in the dashboard. */
export type TabType = "home" | "explore";

/** Selected project filter — null means "all projects". */
export const selectedProject = writable<string | null>(null);

/** Currently active tab in the dashboard. */
export const activeTab = writable<TabType>("home");

/** Incrementing counter that triggers a data refresh when incremented. */
export const refreshCounter = writable<number>(0);

/**
 * Auto-refresh interval in milliseconds. Default 300 s (5 minutes).
 *
 * The Home tab's idle traffic adds up quickly — BriefingStats alone
 * fires several `distillery_list` calls per tick, RecentCorrections
 * fans out O(N) in per-entry `distillery_relations` and
 * `distillery_get` calls, and RadarFeed / ProjectSelector / identity
 * each add one more. A 60 s tick blew past the 60 req/min HTTP rate
 * limit on staging (see
 * src/distillery/mcp/middleware.py::RateLimitMiddleware and
 * src/distillery/config.py::HttpRateLimitConfig defaults).
 *
 * 300 s gives staging ~5× more headroom while still feeling fresh.
 * Consumers that want a tighter refresh for a specific view can
 * override this store locally, and manual refresh / project change
 * / tab switch still trigger an immediate re-fetch regardless.
 */
export const refreshIntervalMs = writable<number>(300_000);

/** User identity from MCP Apps OAuth context. */
export interface UserIdentity {
  /** GitHub login name. */
  login: string;
  /** Display name or login fallback. */
  displayName: string;
  /** Avatar URL if available. */
  avatarUrl?: string;
}

/** Current authenticated user. null while loading or unauthenticated. */
export const currentUser = writable<UserIdentity | null>(null);

/** Whether any async data load is in progress. */
export const isLoading = writable<boolean>(false);

/**
 * Manually trigger a refresh by incrementing the refresh counter.
 * All components that subscribe to refreshCounter will re-fetch their data.
 */
export function triggerRefresh(): void {
  refreshCounter.update((n) => n + 1);
}

/**
 * Derived store: current refresh counter value (for subscription convenience).
 * Components that need to re-run effects on refresh subscribe to this.
 */
export const refreshTick = derived(refreshCounter, ($counter) => $counter);

// ---------------------------------------------------------------------------
// Working Set store — pinned entries for comparison / export
// ---------------------------------------------------------------------------

/**
 * A pinned knowledge entry in the working set.
 * Stores enough info to render a compact card without re-fetching.
 */
export interface PinnedEntry {
  /** Entry UUID from the knowledge store. */
  id: string;
  /** Short display title (first line of content or explicit title). */
  title: string;
  /** Entry type label (e.g. "knowledge", "note", "bookmark"). */
  type: string;
  /** Full content of the entry. */
  content: string;
  /** ISO timestamp when the entry was pinned. */
  pinnedAt: string;
}

const WORKING_SET_KEY = "distillery.workingSet";

/** Type guard: returns true if value has all required PinnedEntry string fields. */
function isPinnedEntry(value: unknown): value is PinnedEntry {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === "string" &&
    typeof v.title === "string" &&
    typeof v.type === "string" &&
    typeof v.content === "string" &&
    typeof v.pinnedAt === "string"
  );
}

/** Load persisted working set from sessionStorage, or return empty array. */
function loadFromSession(): PinnedEntry[] {
  try {
    const raw = sessionStorage.getItem(WORKING_SET_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isPinnedEntry) : [];
  } catch {
    return [];
  }
}

/** Save working set to sessionStorage. */
function saveToSession(entries: PinnedEntry[]): void {
  try {
    sessionStorage.setItem(WORKING_SET_KEY, JSON.stringify(entries));
  } catch {
    // sessionStorage may be unavailable in some environments — fail silently.
  }
}

/** The working set: pinned entries the user wants to compare or export. */
export const workingSet = writable<PinnedEntry[]>(loadFromSession());

// Keep sessionStorage in sync whenever the store changes.
workingSet.subscribe((entries) => {
  saveToSession(entries);
});

/**
 * Pin an entry to the working set.
 * If the entry is already pinned (by id), this is a no-op (duplicate prevention).
 */
export function pinEntry(entry: PinnedEntry): void {
  workingSet.update((entries) => {
    if (entries.some((e) => e.id === entry.id)) return entries;
    return [...entries, { ...entry, pinnedAt: entry.pinnedAt || new Date().toISOString() }];
  });
}

/**
 * Remove an entry from the working set by id.
 */
export function unpinEntry(id: string): void {
  workingSet.update((entries) => entries.filter((e) => e.id !== id));
}

/**
 * Return true if the entry with the given id is currently pinned.
 * This is a snapshot check — for reactive use, subscribe to workingSet.
 */
export function isEntryPinned(id: string, entries: PinnedEntry[]): boolean {
  return entries.some((e) => e.id === id);
}

/**
 * Remove all entries from the working set.
 */
export function clearWorkingSet(): void {
  workingSet.set([]);
}

/**
 * Move the entry at fromIndex to toIndex.
 * No-op if either index is out of range.
 */
export function reorderEntries(fromIndex: number, toIndex: number): void {
  workingSet.update((entries) => {
    if (
      fromIndex < 0 ||
      fromIndex >= entries.length ||
      toIndex < 0 ||
      toIndex >= entries.length ||
      fromIndex === toIndex
    ) {
      return entries;
    }
    const next = [...entries];
    const [moved] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, moved);
    return next;
  });
}
