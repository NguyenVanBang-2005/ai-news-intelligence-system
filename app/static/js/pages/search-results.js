// The list of search results. A title or arrow opens the article drawer (not the site).

import { badge, card, emptyState } from "../components.js";
import { el } from "../dom.js";
import { formatDateTime } from "../format.js";
import { openArticle } from "./article-drawer.js";

const SUMMARY_LABELS = {
  ai: ["AI summary", "primary"],
  cached: ["Cached summary", "success"],
  extractive: ["Extractive summary", "warning"],
};

export function resultsPanel(query, sources) {
  if (sources.length === 0) {
    return card(emptyState(`No articles found for "${query}".`, "Try other words or a broader topic."));
  }
  const count = `${sources.length} best matching result${sources.length === 1 ? "" : "s"}`;
  return el("div", { className: "results-panel" }, [
    // In a card: the top of the results overlaps the dark hero.
    card(el("div", { className: "results-header" }, [
      el("h2", { className: "results-title", text: "Related articles" }),
      el("p", { className: "results-count", text: count }),
    ])),
    el("ol", { className: "result-list" }, sources.map(resultCard)),
  ]);
}

function resultCard(source, index) {
  const [summaryLabel, summaryTone] = SUMMARY_LABELS[source.summary_method] ?? ["Summary", "neutral"];
  const open = (event) => openArticle(source.id, event.currentTarget);
  return el("li", { className: "card result-card" }, [
    el("span", { className: "result-index", text: String(index + 1).padStart(2, "0") }),
    el("div", { className: "result-body" }, [
      el("div", { className: "result-top" }, [
        source.topic ? badge(source.topic, "primary") : null,
        el("time", { datetime: source.published_at, text: formatDateTime(source.published_at) }),
      ]),
      el("h3", { className: "result-title" }, el("button", {
        className: "result-title-button", type: "button", text: source.title, onclick: open,
      })),
      el("p", { className: "result-summary", text: source.summary }),
      el("div", { className: "result-meta" }, [
        el("span", { className: "source-avatar", "aria-hidden": "true", text: initial(source.source_name) }),
        el("span", { className: "result-source", text: source.source_name }),
        badge(summaryLabel, summaryTone),
        el("button", {
          className: "result-open", type: "button", text: "→", onclick: open,
          "aria-label": `Open details: ${source.title}`,
        }),
      ]),
    ]),
  ]);
}

function initial(name) {
  const letter = String(name ?? "").trim().charAt(0);
  return letter ? letter.toUpperCase() : "?";
}
