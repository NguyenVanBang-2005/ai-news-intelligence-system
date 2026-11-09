// The public Sources page: a read-only list of sources (GET /api/v1/sources) and the
// latest classified articles. Adding, deleting and rescanning sources is on /admin/.

import { request } from "../api.js";
import { badge, emptyState, errorMessage, loading } from "../components.js";
import { el } from "../dom.js";
import { classifiedSection } from "./classified-list.js";
import { languageName, sourceStatus } from "./source-status.js";

const SOURCES_PATH = "/api/v1/sources";
const TYPE_NAMES = { rss: "RSS/Atom feed", news_api: "News search" };

export function renderSourcesPage(root) {
  const body = el("div", { className: "source-list-body" });
  root.append(
    hero(),
    el("div", { className: "container container-wide sources-page" }, [
      el("section", { className: "card source-list-card", "aria-labelledby": "source-list-title" }, [
        el("div", { className: "panel-head" }, [
          el("h2", { className: "panel-title", id: "source-list-title", text: "Source list" }),
        ]),
        body,
      ]),
      classifiedSection(),
    ]),
  );
  loadSources(body);
}

function hero() {
  return el("section", { className: "hero hero-sources" }, [
    el("div", { className: "hero-sources-inner" }, [
      el("div", { className: "hero-sources-text" }, [
        el("p", { className: "hero-eyebrow", text: "Sources" }),
        el("h1", { className: "hero-title", text: "News sources" }),
        el("p", { className: "hero-subtitle", text: "Where articles are collected from, and how the latest collection went." }),
      ]),
    ]),
  ]);
}

async function loadSources(body) {
  body.replaceChildren(loading("Loading sources…"));
  try {
    const sources = await request(SOURCES_PATH);
    body.replaceChildren(sourceTable(Array.isArray(sources) ? sources : []));
  } catch (error) {
    body.replaceChildren(el("div", { className: "banner banner-error list-error", role: "alert" }, [
      el("p", { text: `The sources could not be loaded. ${errorMessage(error)}` }),
      el("button", { className: "btn btn-secondary", type: "button", text: "Retry", onclick: () => loadSources(body) }),
    ]));
  }
}

function sourceTable(sources) {
  if (sources.length === 0) return emptyState("No sources yet.");
  const head = el("thead", {}, el("tr", {}, ["Source", "Type", "Language", "Status"]
    .map((text) => el("th", { scope: "col", text }))));
  return el("table", { className: "source-table" }, [head, el("tbody", {}, sources.map(sourceRow))]);
}

function sourceRow(source) {
  const status = sourceStatus(source);
  return el("tr", {}, [
    el("td", { className: "cell-source", dataset: { label: "Source" } },
      el("span", { className: "source-name", text: source.name })),
    el("td", { dataset: { label: "Type" }, text: TYPE_NAMES[source.type] ?? String(source.type ?? "") }),
    el("td", { dataset: { label: "Language" }, text: languageName(source.language) }),
    el("td", { className: "cell-status", dataset: { label: "Status" }, title: status.title }, [
      badge(status.label, status.tone),
      status.detail ? el("span", { className: `status-detail status-detail-${status.tone}`, text: status.detail }) : null,
    ]),
  ]);
}
