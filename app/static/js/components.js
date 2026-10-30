// Shared pieces: loading, empty state, error banner, badge, card, "Coming soon".

import { el } from "./dom.js";

const LINK_NOT_SUPPORTED = "Article links aren't supported on this page.";
const BAD_LENGTH = "Please enter 2 to 500 characters.";

export function loading(message = "Loading…") {
  return el("p", { className: "state state-loading", role: "status", text: message });
}

export function emptyState(title, hint = "") {
  return el("div", { className: "state state-empty" }, [
    el("p", { className: "state-empty-title", text: title }),
    hint ? el("p", { className: "state", text: hint }) : null,
  ]);
}

export function infoBanner(message) {
  return el("p", { className: "banner banner-info", role: "status", text: message });
}

/** A banner with a plain-English message for an ApiError (or any other error). */
export function errorBanner(error) {
  return el("p", { className: "banner banner-error", role: "alert", text: errorMessage(error) });
}

export function errorMessage(error) {
  switch (error?.kind) {
    case "validation":
      // A list of field errors means a bad length; a plain message means a link.
      return Array.isArray(error.detail) ? BAD_LENGTH : LINK_NOT_SUPPORTED;
    case "too_large":
      return "Your query is too long.";
    case "rate_limited":
      return rateLimitedMessage(error.retryAfter);
    case "unavailable":
      return "The service is not ready yet.";
    case "unauthorized":
      return "This action needs a valid admin token.";
    case "not_found":
      return "Not found.";
    case "network":
      return error.timedOut
        ? "The server took too long to answer. Please try again."
        : "The server could not be reached. Check your connection and try again.";
    default:
      return "Something went wrong on the server. Please try again later.";
  }
}

function rateLimitedMessage(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return "Too many searches. Please wait a moment and try again.";
  }
  return `Too many searches. Please wait ${seconds} second${seconds === 1 ? "" : "s"} and try again.`;
}

/** tone: "neutral" | "primary" | "success" | "warning" | "danger". */
export function badge(text, tone = "neutral") {
  return el("span", { className: `badge badge-${tone}`, text });
}

/**
 * A thin bar for a value from 0 to `max`, drawn by <progress>, so no style is set from code.
 * Without a `label` the bar is decorative (the number is shown as text next to it).
 */
export function progressBar(value, { max = 1, label = null, className = "meter" } = {}) {
  const clamped = Number.isFinite(value) ? Math.min(max, Math.max(0, value)) : 0;
  return el("progress", {
    className, value: clamped, max, "aria-label": label, "aria-hidden": label ? null : "true",
  });
}

export function card(children, className = "") {
  return el("div", { className: `card ${className}`.trim() }, children);
}

/** Placeholder for a page that is not built yet. */
export function comingSoon(title) {
  return el("div", { className: "container" }, [
    card([
      el("h1", { text: title }),
      el("p", { text: "Coming soon. This page is not available yet." }),
    ], "coming-soon"),
  ]);
}
