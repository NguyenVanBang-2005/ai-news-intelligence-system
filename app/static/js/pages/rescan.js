// "Rescan sources": runs POST /api/v1/ingestion/run and shows its numbers in four cards.
// The server keeps no history of runs, so the last result is kept in sessionStorage.

import { adminRequest, hasToken, tokenErrorMessage } from "../admin-token.js";
import { errorMessage, loading } from "../components.js";
import { el } from "../dom.js";
import { formatCount, formatDateTime, formatPercent, formatRelativeTime } from "../format.js";
import { watchToken } from "./admin-access.js";

// The run is synchronous on the server and may take minutes.
export const RESCAN_TIMEOUT_MS = 180000;
const SLOW_HINT_DELAY_MS = 5000;
const MAX_ERRORS_SHOWN = 10;
const STORAGE_KEY = "ainis.lastRescan";
const RUN_PATH = "/api/v1/ingestion/run";

const SLOW_HINT = "Rescanning can take a few minutes. Keep this tab open.";
const TIMEOUT_MESSAGE = "The rescan is taking longer than expected. It may still be running on the server; reload the list in a minute.";
const NO_RESULT_HINT = "Run a rescan to see results.";

const STAT_CARDS = [
  { key: "sources_processed", label: "Sources processed" },
  { key: "articles_seen", label: "Articles seen" },
  { key: "articles_created", label: "New articles saved" },
  { key: "duplicates_skipped", label: "Duplicates skipped" },
];

/**
 * The hero button, the stat cards and the report box.
 * `onFinished` runs after every rescan that got an answer (to reload the source list).
 */
export function createRescan({ onFinished }) {
  const view = {
    button: el("button", { className: "btn btn-hero", type: "button", onclick: () => runRescan(view) }, [
      el("span", { className: "spinner", "aria-hidden": "true" }),
      el("span", { className: "btn-label", text: "Rescan sources" }),
    ]),
    note: el("p", { className: "hero-note", text: "" }),
    cards: el("div", { className: "stat-grid" }),
    report: el("section", { className: "rescan-report", "aria-live": "polite" }),
    busy: false,
    onFinished,
  };
  watchToken(view.button, () => updateButton(view));
  const saved = loadLastRun();
  view.cards.replaceChildren(...statCards(saved?.result));
  if (saved) view.report.replaceChildren(reportCard(saved));
  return view;
}

function updateButton(view) {
  view.button.disabled = view.busy || !hasToken();
  view.note.textContent = hasToken() ? "" : "Enter the admin token to manage sources.";
}

async function runRescan(view) {
  if (view.busy || !hasToken()) return; // one run at a time; never without a token
  setBusy(view, true);
  const stopHint = showRunning(view.report);
  try {
    const result = await adminRequest(RUN_PATH, { method: "POST", timeoutMs: RESCAN_TIMEOUT_MS });
    const run = saveLastRun(result);
    view.cards.replaceChildren(...statCards(result));
    view.report.replaceChildren(reportCard(run));
    view.onFinished();
  } catch (error) {
    view.report.replaceChildren(failureCard(error, view.onFinished));
  } finally {
    stopHint();
    setBusy(view, false);
  }
}

function setBusy(view, busy) {
  view.busy = busy;
  view.button.classList.toggle("is-busy", busy);
  view.button.setAttribute("aria-busy", String(busy));
  view.button.querySelector(".btn-label").textContent = busy ? "Rescanning…" : "Rescan sources";
  updateButton(view);
}

// "Rescanning sources…", plus SLOW_HINT after SLOW_HINT_DELAY_MS.
function showRunning(report) {
  const box = el("div", { className: "card rescan-card" }, loading("Rescanning sources…"));
  report.replaceChildren(box);
  const timer = setTimeout(() => {
    box.append(el("p", { className: "state state-hint rescan-slow", text: SLOW_HINT }));
  }, SLOW_HINT_DELAY_MS);
  return () => clearTimeout(timer);
}

function statCards(result) {
  return STAT_CARDS.map((stat, index) => el("div", { className: "card stat-card" }, [
    el("div", { className: "stat-top" }, [
      el("p", { className: "stat-label", text: stat.label }),
      el("span", { className: "stat-index", "aria-hidden": "true", text: String(index + 1).padStart(2, "0") }),
    ]),
    el("p", { className: "stat-value", text: result ? formatCount(result[stat.key]) : "–" }),
    el("div", { className: "stat-bottom" }, [
      el("code", { className: "stat-field", text: stat.key }),
      el("span", { className: "stat-meta", text: result ? statMeta(stat.key, result) : NO_RESULT_HINT }),
    ]),
  ]));
}

// Only the duplicate card has an extra figure: the duplicate rate of this run.
function statMeta(key, result) {
  if (key !== "duplicates_skipped" || !(result.articles_seen > 0)) return "";
  return `${formatPercent(result.duplicates_skipped / result.articles_seen)} of articles seen`;
}

function reportCard(run) {
  const { result, ranAt } = run;
  const errors = Array.isArray(result.errors) ? result.errors : [];
  const when = el("time", { datetime: ranAt, title: formatDateTime(ranAt), text: formatRelativeTime(ranAt) ?? "" });
  const summary = `${formatCount(result.sources_processed)} sources processed, ` +
    `${formatCount(result.articles_created)} new articles saved, ${formatCount(errors.length)} errors.`;
  return el("div", { className: "card rescan-card" }, [
    el("p", { className: "rescan-summary" }, ["Last rescan ", when, ": ", summary]),
    errors.length ? errorList(errors) : null,
  ]);
}

function errorList(errors) {
  const shown = errors.slice(0, MAX_ERRORS_SHOWN);
  const more = errors.length - shown.length;
  return el("div", { className: "rescan-errors" }, [
    el("h3", { className: "rescan-errors-title", text: "Errors" }),
    el("ul", {}, [
      ...shown.map((text) => el("li", { text: String(text) })),
      more > 0 ? el("li", { className: "rescan-more", text: `…and ${more} more` }) : null,
    ]),
  ]);
}

function failureCard(error, reloadList) {
  if (error?.kind === "network" && error.timedOut) {
    return el("div", { className: "banner banner-info rescan-timeout", role: "status" }, [
      el("p", { text: TIMEOUT_MESSAGE }),
      el("button", { className: "btn btn-secondary", type: "button", text: "Reload list", onclick: reloadList }),
    ]);
  }
  if (!error?.kind) console.error(error); // a bug, not an API answer
  const text = tokenErrorMessage(error) ?? errorMessage(error);
  return el("p", { className: "banner banner-error", role: "alert", text });
}

function loadLastRun() {
  try {
    const run = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) ?? "null");
    return run && typeof run === "object" && run.result && run.ranAt ? run : null;
  } catch {
    return null; // storage blocked or a broken value
  }
}

function saveLastRun(result) {
  const run = { result, ranAt: new Date().toISOString() };
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(run));
  } catch {
    // storage blocked: the result is still shown, just not kept after a reload
  }
  return run;
}
