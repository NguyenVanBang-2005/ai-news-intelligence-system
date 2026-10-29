// The "Source list" table: GET /api/v1/sources, plus the Active switch (PATCH)
// and the delete button (DELETE, always after a confirmation dialog).

import { adminRequest, hasToken, NEEDS_TOKEN_MESSAGE, tokenErrorMessage } from "../admin-token.js";
import { request } from "../api.js";
import { badge, emptyState, errorMessage, loading } from "../components.js";
import { confirmDialog } from "../confirm-dialog.js";
import { el } from "../dom.js";
import { watchToken } from "./admin-access.js";
import { languageName, sourceStatus } from "./source-status.js";

const SOURCES_PATH = "/api/v1/sources";
const CASCADE_WARNING = "Deleting this source also permanently deletes all of its articles.";

/** Returns { node, reload } for the list card. */
export function sourceListPanel() {
  const view = {
    sources: [],
    busyIds: new Set(), // sources with a PATCH or DELETE on the way
    latestLoad: 0,
    count: el("p", { className: "panel-subtitle" }),
    note: el("p", { className: "form-note" }),
    message: el("div", { className: "list-message", "aria-live": "polite" }),
    body: el("div", { className: "source-list-body" }),
  };
  const node = el("section", { className: "card source-list-card", "aria-labelledby": "source-list-title" }, [
    el("div", { className: "panel-head panel-head-split" }, [
      el("div", {}, [el("h2", { className: "panel-title", id: "source-list-title", text: "Source list" }), view.count]),
      badge("Manual sync", "primary"),
    ]),
    view.note, view.message, view.body,
  ]);
  watchToken(node, () => updateControls(view));
  const reload = () => loadSources(view);
  view.reload = reload;
  reload();
  return { node, reload };
}

async function loadSources(view) {
  const loadNumber = ++view.latestLoad;
  if (view.sources.length === 0) view.body.replaceChildren(loading("Loading sources…"));
  try {
    const sources = await request(SOURCES_PATH); // public: no token sent
    if (loadNumber !== view.latestLoad) return; // a newer load is on the way
    view.sources = Array.isArray(sources) ? sources : [];
    renderList(view);
  } catch (error) {
    if (loadNumber !== view.latestLoad) return;
    view.sources = [];
    view.count.textContent = "";
    view.body.replaceChildren(loadError(error, view.reload));
  }
}

function loadError(error, retry) {
  return el("div", { className: "banner banner-error list-error", role: "alert" }, [
    el("p", { text: `The sources could not be loaded. ${errorMessage(error)}` }),
    el("button", { className: "btn btn-secondary", type: "button", text: "Retry", onclick: retry }),
  ]);
}

function renderList(view) {
  updateCount(view);
  if (view.sources.length === 0) {
    view.body.replaceChildren(emptyState("No sources yet. Add one above."));
    return;
  }
  const head = el("thead", {}, el("tr", {}, ["Source", "Language", "Status", "Active"]
    .map((text) => el("th", { scope: "col", text }))
    .concat(el("th", { scope: "col" }, el("span", { className: "visually-hidden", text: "Delete" })))));
  const rows = view.sources.map((source) => sourceRow(view, source));
  view.body.replaceChildren(el("table", { className: "source-table" }, [head, el("tbody", {}, rows)]));
  updateControls(view);
}

function updateCount(view) {
  const active = view.sources.filter((source) => source.is_active).length;
  const total = view.sources.length;
  view.count.textContent = `${total} source${total === 1 ? "" : "s"} · ${active} active`;
}

function sourceRow(view, source) {
  const status = sourceStatus(source);
  const address = source.feed_url ?? source.query ?? "";
  return el("tr", { dataset: { sourceId: String(source.id) } }, [
    el("td", { className: "cell-source", dataset: { label: "Source" } }, [
      el("span", { className: "source-name", text: source.name }),
      address ? el("span", { className: "source-address", text: address }) : null, // plain text, never a link
    ]),
    el("td", { dataset: { label: "Language" }, text: languageName(source.language) }),
    el("td", { className: "cell-status", dataset: { label: "Status" }, title: status.title }, [
      badge(status.label, status.tone),
      status.detail ? el("span", { className: `status-detail status-detail-${status.tone}`, text: status.detail }) : null,
    ]),
    el("td", { dataset: { label: "Active" } }, activeSwitch(view, source)),
    el("td", { className: "cell-actions" }, deleteButton(view, source)),
  ]);
}

function activeSwitch(view, source) {
  const verb = source.is_active ? "Disable" : "Enable";
  return el("button", {
    className: "switch", type: "button", role: "switch",
    "aria-checked": String(source.is_active), "aria-label": `${verb} ${source.name}`,
    dataset: { sourceId: String(source.id) },
    onclick: (event) => toggleActive(view, source, event.currentTarget),
  }, el("span", { className: "switch-knob", "aria-hidden": "true" }));
}

function deleteButton(view, source) {
  return el("button", {
    className: "btn-icon btn-delete", type: "button", text: "Delete",
    "aria-label": `Delete ${source.name}`, dataset: { sourceId: String(source.id) },
    onclick: (event) => askToDelete(view, source, event.currentTarget),
  });
}

// Admin controls are off without a token and while a request for their source runs.
function updateControls(view) {
  const locked = !hasToken();
  view.note.textContent = locked ? NEEDS_TOKEN_MESSAGE : "";
  for (const button of view.body.querySelectorAll(".switch, .btn-delete")) {
    button.disabled = locked || view.busyIds.has(Number(button.dataset.sourceId));
  }
}

// No optimistic update: the switch only changes to what the server sends back.
async function toggleActive(view, source, button) {
  if (!hasToken() || view.busyIds.has(source.id)) return;
  setSourceBusy(view, source.id, true);
  try {
    const updated = await adminRequest(`${SOURCES_PATH}/${encodeURIComponent(source.id)}`, {
      method: "PATCH", body: { is_active: !source.is_active },
    });
    replaceSource(view, updated, button);
    showMessage(view, `${updated.name} is now ${updated.is_active ? "active" : "inactive"}.`, "info");
  } catch (error) {
    if (error?.status === 404) return sourceGone(view);
    showMessage(view, `The change was not saved. ${actionErrorText(error)}`, "error");
  } finally {
    setSourceBusy(view, source.id, false);
  }
}

function replaceSource(view, updated, oldButton) {
  view.sources = view.sources.map((item) => (item.id === updated.id ? updated : item));
  const oldRow = oldButton.closest("tr");
  const hadFocus = oldRow?.contains(document.activeElement);
  const newRow = sourceRow(view, updated);
  oldRow?.replaceWith(newRow);
  updateCount(view);
  if (hadFocus) newRow.querySelector(".switch").focus();
}

async function askToDelete(view, source, button) {
  if (!hasToken() || view.busyIds.has(source.id)) return;
  const confirmed = await confirmDialog({
    title: `Delete "${source.name}"?`,
    lines: [`Source: ${source.name}`, CASCADE_WARNING, "This cannot be undone."],
    confirmText: "Delete source", danger: true, opener: button,
  });
  if (confirmed) await deleteSource(view, source);
}

async function deleteSource(view, source) {
  setSourceBusy(view, source.id, true);
  try {
    await adminRequest(`${SOURCES_PATH}/${encodeURIComponent(source.id)}`, { method: "DELETE" });
    showMessage(view, `Source deleted: ${source.name}`, "info");
    view.reload();
  } catch (error) {
    if (error?.status === 404) return sourceGone(view);
    showMessage(view, `The source was not deleted. ${actionErrorText(error)}`, "error");
  } finally {
    setSourceBusy(view, source.id, false);
  }
}

function sourceGone(view) {
  showMessage(view, "This source no longer exists.", "error");
  view.reload();
}

function actionErrorText(error) {
  if (!error?.kind) console.error(error); // a bug, not an API answer
  return tokenErrorMessage(error) ?? errorMessage(error);
}

function setSourceBusy(view, id, busy) {
  if (busy) view.busyIds.add(id);
  else view.busyIds.delete(id);
  updateControls(view);
}

function showMessage(view, text, tone) {
  const role = tone === "error" ? "alert" : "status";
  view.message.replaceChildren(el("p", { className: `banner banner-${tone}`, role, text }));
}
