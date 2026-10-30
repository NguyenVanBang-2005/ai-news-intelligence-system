// The "Admin access" block of the Sources page: type, use or clear the admin token.
// There is no endpoint to check a token, so it only counts as verified after an
// admin request has succeeded.

import {
  clearToken, onTokenChange, saveToken, tokenStatus,
  TOKEN_REJECTED_MESSAGE, TOKEN_UNCONFIGURED_MESSAGE,
} from "../admin-token.js";
import { el } from "../dom.js";

const STATUS_TEXT = {
  none: "No token: read-only",
  unverified: "Token set (not verified yet)",
  verified: "Token verified",
  rejected: TOKEN_REJECTED_MESSAGE,
  unconfigured: TOKEN_UNCONFIGURED_MESSAGE,
};
const STATUS_TONE = { none: "neutral", unverified: "warning", verified: "success", rejected: "danger", unconfigured: "danger" };
// With a working token the input row is folded away behind a "Change token" button.
const FOLDED_STATUSES = new Set(["unverified", "verified"]);
const WARNING = "Use this page only on a trusted local setup. The token is kept for this browser tab only.";

/**
 * Calls `update(status)` now and on every token change, until `node` leaves the page.
 * Pages are rebuilt on every route change, so old listeners must not pile up.
 */
export function watchToken(node, update) {
  update(tokenStatus());
  const stop = onTokenChange((status) => {
    if (node.isConnected) update(status);
    else stop();
  });
}

export function adminAccessPanel() {
  const view = buildView();
  watchToken(view.panel, (status) => showStatus(view, status));
  return view.panel;
}

function buildView() {
  const input = el("input", {
    className: "admin-input", id: "admin-token-input", type: "password", name: "admin-token",
    autocomplete: "off", spellcheck: "false", "aria-describedby": "admin-token-warning",
  });
  const hint = el("p", { className: "admin-hint", role: "status" });
  const form = el("form", {
    className: "admin-form", novalidate: true, onsubmit: (event) => submitToken(event, input, hint),
  }, [
    el("label", { className: "visually-hidden", for: "admin-token-input", text: "Admin token" }),
    input,
    el("button", { className: "btn btn-primary", type: "submit", text: "Use token" }),
  ]);
  const view = {
    input, hint, form,
    status: el("p", { className: "admin-status" }),
    change: el("button", { className: "btn btn-secondary", type: "button", text: "Change token" }),
    clear: el("button", { className: "btn btn-secondary", type: "button", text: "Clear token" }),
  };
  view.change.addEventListener("click", () => { setFolded(view, false); input.focus(); });
  view.clear.addEventListener("click", () => { input.value = ""; hint.textContent = ""; clearToken(); });
  view.panel = el("section", { className: "admin-panel", "aria-label": "Admin access" }, [
    el("div", { className: "admin-row" }, [
      el("h2", { className: "admin-title", text: "Admin access" }),
      el("div", { className: "admin-status-box", role: "status", "aria-live": "polite" }, view.status),
      form, view.change, view.clear,
    ]),
    hint,
    el("p", { className: "admin-warning", id: "admin-token-warning", text: WARNING }),
  ]);
  return view;
}

function submitToken(event, input, hint) {
  event.preventDefault();
  hint.textContent = saveToken(input.value) ? "" : "Paste the admin token first.";
}

function showStatus(view, status) {
  view.status.textContent = STATUS_TEXT[status] ?? STATUS_TEXT.none;
  view.status.className = `admin-status admin-status-${STATUS_TONE[status] ?? "neutral"}`;
  view.clear.hidden = status === "none";
  view.input.setAttribute("aria-invalid", String(status === "rejected"));
  setFolded(view, FOLDED_STATUSES.has(status));
}

// Folded: the input row is hidden (its text is kept) and "Change token" is shown instead.
function setFolded(view, folded) {
  view.form.hidden = folded;
  view.change.hidden = !folded;
}
