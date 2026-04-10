/**
 * entry-types.ts — shared entry type constants aligned with the Distillery data model.
 *
 * Source of truth: src/distillery/models.py EntryType enum.
 * Excludes "inbox" which is the unclassified state — entries are classified
 * *from* inbox, not *to* inbox.
 */

/** All valid entry types for classification and reclassification. */
export const ENTRY_TYPES = [
  "session",
  "bookmark",
  "minutes",
  "meeting",
  "reference",
  "idea",
  "person",
  "project",
  "digest",
  "github",
  "feed",
] as const;

export type EntryType = (typeof ENTRY_TYPES)[number];
