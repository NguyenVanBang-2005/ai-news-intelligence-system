// Ingestion: POST /api/v1/ingestion/run for all active sources or one source, then its
// four counts and every error the server returned.

import { loading } from "../js/components.js";
import { el } from "../js/dom.js";
import { formatCount } from "../js/format.js";
import { adminErrorText, adminRequest, messageBanner } from "./admin-api.js";

// The run is synchronous on the server and may take minutes.
export const RESCAN_TIMEOUT_MS = 180000;
const RUN_PATH = "/api/v1/ingestion/run";

const COUNTS = [
  { key: "sources_processed", label: "Sources processed" },
  { key: "articles_seen", label: "Articles seen" },
  { key: "articles_created", label: "New articles saved" },
  { key: "duplicates_skipped", label: "Duplicates skipped" },
];

/** Returns { node, run(source | null) }. `onFinished` runs after every answered run. */
export function ingestionPanel({ onFinished }) {
  const view = {
    busy: false,
    onFinished,
    report: el("div", { className: "rescan-report", "aria-live": "polite" }),
  };
  view.allButton = el("button", {
    className: "btn btn-primary", type: "button", text: "Run ingestion for all active sources",
    onclick: () => runIngestion(view, null),
  });
  const node = el("section", { className: "card admin-card", "aria-labelledby": "ingestion-title" }, [
    el("h2", { className: "panel-title", id: "ingestion-title", text: "Ingestion" }),
    el("p", { className: "panel-subtitle", text: "Collect new articles now. Use \"Ingest\" in the source list for one source." }),
    view.allButton,
    view.report,
  ]);
  return { node, run: (source) => runIngestion(view, source) };
}

async function runIngestion(view, source) {
  if (view.busy) {
    view.report.replaceChildren(messageBanner("An ingestion run is already in progress.", "info"));
    return;
  }
  setBusy(view, true);
  const target = source ? `source "${source.name}"` : "all active sources";
  view.report.replaceChildren(loading(`Ingesting ${target}… This can take a few minutes.`));
  try {
    const path = source ? `${RUN_PATH}?source_id=${encodeURIComponent(source.id)}` : RUN_PATH;
    const result = await adminRequest(path, { method: "POST", timeoutMs: RESCAN_TIMEOUT_MS });
    view.report.replaceChildren(resultCard(target, result));
    view.onFinished();
  } catch (error) {
    view.report.replaceChildren(messageBanner(`Ingestion of ${target} failed. ${adminErrorText(error)}`, "error"));
  } finally {
    setBusy(view, false);
  }
}

function setBusy(view, busy) {
  view.busy = busy;
  view.allButton.disabled = busy;
}

function resultCard(target, result) {
  const errors = Array.isArray(result?.errors) ? result.errors : [];
  return el("div", { className: "rescan-card" }, [
    el("p", { className: "rescan-summary", text: `Finished: ${target}.` }),
    el("div", { className: "stat-grid" }, COUNTS.map((count) => el("div", { className: "card stat-card" }, [
      el("p", { className: "stat-label", text: count.label }),
      el("p", { className: "stat-value", text: formatCount(result?.[count.key]) }),
      el("code", { className: "stat-field", text: count.key }),
    ]))),
    el("div", { className: "rescan-errors" }, [
      el("h3", { className: "rescan-errors-title", text: `Errors (${errors.length})` }),
      errors.length
        ? el("ul", {}, errors.map((text) => el("li", { text: String(text) })))
        : el("p", { className: "state", text: "No errors." }),
    ]),
  ]);
}
