/**
 * Svelte stores for shared dashboard state.
 *
 * Provides reactive stores for project filter selection, refresh triggers,
 * user identity, and configurable auto-refresh interval.
 */

import { writable, derived } from "svelte/store";

/** Dashboard top-level tab identifiers. */
export type DashboardTab = "home" | "explore" | "capture" | "manage";

/** User roles that determine tab and feature access. */
export type UserRole = "developer" | "curator" | "admin";

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

/** Current user role. null while loading or unauthenticated. */
export const userRole = writable<UserRole | null>(null);

/** Active top-level dashboard tab. */
export const activeTab = writable<DashboardTab>("home");

/** Whether any async data load is in progress. */
export const isLoading = writable<boolean>(false);

/** Inbox entry count — used for Manage tab badge. null while loading. */
export const inboxBadgeCount = writable<number | null>(null);

/** Pending review entry count — used for Manage tab badge. null while loading. */
export const reviewBadgeCount = writable<number | null>(null);

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
