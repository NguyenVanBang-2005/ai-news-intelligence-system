// Display formats for dates, counts and scores.

export const DISPLAY_TIME_ZONE = "Asia/Ho_Chi_Minh";
export const UNKNOWN_DATE = "Date unknown";

const HAS_TIME_ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: DISPLAY_TIME_ZONE,
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZoneName: "shortOffset",
});

const countFormat = new Intl.NumberFormat("en-US");

/** Parses an API time; one without "Z" or "+hh:mm" is taken as UTC. Null if invalid. */
export function parseApiDate(value) {
  if (typeof value !== "string" || value.trim() === "") return null;
  let text = value.trim();
  if (DATE_ONLY.test(text)) text += "T00:00:00Z";
  else if (!HAS_TIME_ZONE.test(text)) text += "Z";
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** For example "26 Oct 2026, 16:00 GMT+7"; "Date unknown" for null or invalid input. */
export function formatDateTime(value) {
  const date = parseApiDate(value);
  return date ? dateTimeFormat.format(date) : UNKNOWN_DATE;
}

/** For example "1,284". */
export function formatCount(value) {
  return Number.isFinite(value) ? countFormat.format(value) : "–";
}

/** A trend score in standard deviations, for example "+2.1σ" or "-0.4σ". */
export function formatScore(value) {
  if (!Number.isFinite(value)) return "–";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${Math.abs(value).toFixed(1)}σ`;
}

/** A 0-1 similarity as a whole percentage, for example "82%". */
export function formatPercent(value) {
  if (!Number.isFinite(value)) return "–";
  return `${Math.round(Math.min(1, Math.max(0, value)) * 100)}%`;
}
