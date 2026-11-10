// Admin source list: GET /api/v1/sources with the sync status, an "Ingest" button per
// source, an "Enable"/"Disable" button (PATCH {is_active}) and the delete button
// (DELETE, always after a confirmation dialog).

import { badge, emptyState, loading } from "../js/components.js";
import { confirmDialog } from "../js/confirm-dialog.js";
import { el } from "../js/dom.js";
import { formatDateTime } from "../js/format.js";
import { languageName, sourceStatus } from "../js/pages/source-status.js";
import { adminErrorText, adminRequest, messageBanner } from "./admin-api.js";

const SOURCES_PATH = "/api/v1/sources";
const CASCADE_WARNING = "Deleting this source also permanently deletes all of its articles.";

/** Returns { node, reload }. `onIngest(source)` runs one source's ingestion (a promise). */
export function sourcesAdminPanel({ onIngest }) {
  const view = {
    onIngest,
    count: el("p", { className: "panel-subtitle" }),
    message: el("div", { className: "list-message", "aria-live": "polite" }),
    body: el("div", { className: "source-list-body" }),
  };
  view.reload = () => loadSources(view);
  const node = el("section", { className: "card source-list-card", "aria-labelledby": "admin-sources-title" }, [
    el("div", { className: "panel-head panel-head-split" }, [
      el("div", {}, [el("h2", { className: "panel-title", id: "admin-sources-title", text: "Sources" }), view.count]),
      el("button", { className: "btn btn-secondary btn-small", type: "button", text: "Refresh", onclick: view.reload }),
    ]),
    view.message, view.body,
  ]);
  view.reload();
  return { node, reload: view.reload };
}

async function loadSources(view) {
  view.body.replaceChildren(loading("Loading sources…"));
  try {
    const sources = await adminRequest(SOURCES_PATH);
    renderList(view, Array.isArray(sources) ? sources : []);
  } catch (error) {
    view.count.textContent = "";
    view.body.replaceChildren(messageBanner(`The sources could not be loaded. ${adminErrorText(error)}`, "error"));
  }
}

function renderList(view, sources) {
  view.sources = sources;
  showCount(view);
  if (sources.length === 0) {
    view.body.replaceChildren(emptyState("No sources yet. Add one with the form."));
    return;
  }
  const head = el("thead", {}, el("tr", {}, ["Source", "Type", "Language", "Status", "Last sync", "Actions"]
    .map((text) => el("th", { scope: "col", text }))));
  const rows = sources.map((source) => sourceRow(view, source));
  view.body.replaceChildren(el("table", { className: "source-table" }, [head, el("tbody", {}, rows)]));
}

function showCount(view) {
  const { sources } = view;
  const active = sources.filter((source) => source.is_active).length;
  view.count.textContent = `${sources.length} source${sources.length === 1 ? "" : "s"} · ${active} active`;
}

function sourceRow(view, source) {
  const status = sourceStatus(source);
  const address = source.feed_url ?? source.query ?? "";
  return el("tr", {}, [
    el("td", { className: "cell-source", dataset: { label: "Source" } }, [
      el("span", { className: "source-name", text: source.name }),
      address ? el("span", { className: "source-address", text: address }) : null, // plain text, never a link
    ]),
    el("td", { dataset: { label: "Type" }, text: source.type }),
    el("td", { dataset: { label: "Language" }, text: languageName(source.language) }),
    el("td", { className: "cell-status", dataset: { label: "Status" } }, [
      badge(status.label, status.tone),
      source.last_error ? el("span", { className: "status-detail status-detail-danger", text: source.last_error }) : null,
    ]),
    el("td", { dataset: { label: "Last sync" }, text: source.last_synced_at ? formatDateTime(source.last_synced_at) : "Never" }),
    el("td", { className: "cell-actions" }, [
      ingestButton(view, source), toggleButton(view, source), deleteButton(view, source),
    ]),
  ]);
}

function ingestButton(view, source) {
  const button = el("button", {
    className: "btn btn-secondary btn-small", type: "button", text: "Ingest", "aria-label": `Ingest ${source.name}`,
  });
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await view.onIngest(source);
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function toggleButton(view, source) {
  const action = source.is_active ? "Disable" : "Enable";
  const button = el("button", {
    className: "btn btn-secondary btn-small btn-toggle", type: "button", text: action,
    "aria-label": `${action} ${source.name}`,
    title: source.is_active ? "Active: included in rescans" : "Inactive: skipped by rescans",
  });
  button.addEventListener("click", () => setActive(view, source, button));
  return button;
}

/** PATCH the source to the opposite state; on success its row is rebuilt in place. */
async function setActive(view, source, button) {
  if (button.disabled) return; // already on the way
  const turnOn = !source.is_active;
  const row = button.closest("tr");
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = turnOn ? "Enabling…" : "Disabling…";
  try {
    const updated = await adminRequest(`${SOURCES_PATH}/${encodeURIComponent(source.id)}`, {
      method: "PATCH", body: { is_active: turnOn },
    });
    view.sources = view.sources.map((item) => (item.id === updated.id ? updated : item));
    showCount(view);
    if (row?.isConnected) {
      const fresh = sourceRow(view, updated);
      row.replaceWith(fresh);
      fresh.querySelector(".btn-toggle")?.focus(); // keep keyboard focus on the same control
    }
    const word = updated.is_active ? "enabled" : "disabled";
    view.message.replaceChildren(messageBanner(`Source ${word}: ${updated.name}`, "info"));
  } catch (error) {
    view.message.replaceChildren(messageBanner(`The source was not changed. ${adminErrorText(error)}`, "error"));
    if (button.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = source.is_active ? "Disable" : "Enable";
    }
  }
}

function deleteButton(view, source) {
  return el("button", {
    className: "btn-icon btn-delete", type: "button", text: "Delete", "aria-label": `Delete ${source.name}`,
    onclick: (event) => askToDelete(view, source, event.currentTarget),
  });
}

async function askToDelete(view, source, button) {
  if (button.disabled) return; // this source is already being deleted
  const confirmed = await confirmDialog({
    title: `Delete "${source.name}"?`,
    lines: [`Source: ${source.name}`, CASCADE_WARNING, "This cannot be undone."],
    confirmText: "Delete source", danger: true, opener: button,
  });
  button.disabled = true;
  if (confirmed) await deleteSource(view, source);
  if (button.isConnected) button.disabled = false;
}

async function deleteSource(view, source) {
  try {
    await adminRequest(`${SOURCES_PATH}/${encodeURIComponent(source.id)}`, { method: "DELETE" });
    view.message.replaceChildren(messageBanner(`Source deleted: ${source.name}`, "info"));
  } catch (error) {
    view.message.replaceChildren(messageBanner(`The source was not deleted. ${adminErrorText(error)}`, "error"));
  }
  view.reload();
}
