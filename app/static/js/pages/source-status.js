// What the Sources page shows for a source: language name and sync status.
// Everything here is computed in the browser from the fields of GET /api/v1/sources.

import { formatDateTime, formatRelativeTime } from "../format.js";

// Languages offered when adding a source. Add a line here to offer another one.
export const LANGUAGES = Object.freeze([
  { code: "en", name: "English" },
  { code: "vi", name: "Vietnamese" },
]);

/** "English" for "en"; an unknown code is shown as it is. */
export function languageName(code) {
  return LANGUAGES.find((language) => language.code === code)?.name ?? String(code ?? "");
}

/**
 * { label, tone, detail, title } for the status badge of a source.
 * tone is a badge tone; detail is the small line under the badge (or null);
 * title is the full time of the last sync (or null).
 */
export function sourceStatus(source, now = Date.now()) {
  const title = source.last_synced_at ? `Last sync: ${formatDateTime(source.last_synced_at)}` : null;
  if (!source.is_active) {
    return { label: "Inactive", tone: "neutral", detail: "Skipped by rescans", title };
  }
  switch (source.last_status) {
    case "ok":
      return { label: "Stable", tone: "success", detail: syncedText(source.last_synced_at, now), title };
    case "warning":
      return { label: "Warning", tone: "warning", detail: "No new items found in the last sync", title };
    case "error":
      return { label: "Error", tone: "danger", detail: errorReason(source.last_error), title };
    default:
      return { label: "Not synced yet", tone: "neutral", detail: null, title };
  }
}

function syncedText(syncedAt, now) {
  const relative = formatRelativeTime(syncedAt, now);
  return relative ? `Synced ${relative}` : null;
}

/** "UnsupportedFeedError: Link returns HTML" -> "Link returns HTML" (the error type is dropped). */
export function errorReason(lastError) {
  const text = String(lastError ?? "").trim();
  if (!text) return "The last sync failed.";
  const cut = text.indexOf(": ");
  return cut === -1 ? text : text.slice(cut + 2);
}
