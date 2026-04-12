/**
 * Svelte stores for shared dashboard state.
 *
 * Provides reactive stores for project filter selection, refresh triggers,
 * user identity, and configurable auto-refresh interval.
 */

import { writable, derived } from "svelte/store";

/** Selected project filter — null means "all projects". */
export const selectedProject = writable<string | null>(null);

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

/** Available dashboard tabs. */
export type DashboardTab = "home" | "capture";

/** Active tab in the dashboard. Defaults to "home". */
export const activeTab = writable<DashboardTab>("home");

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
