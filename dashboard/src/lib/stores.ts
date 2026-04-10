/**
 * Svelte stores for shared dashboard state.
 *
 * Provides reactive stores for project filter selection, refresh triggers,
 * user identity, configurable auto-refresh interval, and tab selection.
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

/** Auto-refresh interval in milliseconds. Default 60s. */
export const refreshIntervalMs = writable<number>(60_000);

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
