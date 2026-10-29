// The Search page: POST /api/v1/ai/search and a list of matching stored articles.

import { request, SEARCH_TIMEOUT_MS } from "../api.js";
import { badge, card, emptyState, errorBanner, infoBanner, loading } from "../components.js";
import { el, externalLink } from "../dom.js";
import { formatDateTime, formatPercent } from "../format.js";

const SEARCH_PATH = "/api/v1/ai/search";
const MIN_QUERY_LENGTH = 2;
const MAX_QUERY_LENGTH = 500;
const SLOW_HINT_DELAY_MS = 5000;
const SLOW_HINT = "The first search can take up to a minute while the model loads.";

const SUMMARY_LABELS = {
  ai: ["AI summary", "primary"],
  cached: ["Cached summary", "success"],
  extractive: ["Extractive summary", "warning"],
};

export function renderSearchPage(root) {
  const view = {
    input: el("input", {
      className: "search-input", type: "search", name: "input", autocomplete: "off",
      maxlength: MAX_QUERY_LENGTH, placeholder: "Search AI news…",
      "aria-label": "Search the collected news",
    }),
    button: el("button", { className: "btn btn-primary", type: "submit", text: "Search" }),
    results: el("section", { className: "results", "aria-live": "polite" }),
    busy: false,
  };
  const form = el("form", {
    className: "search-box", role: "search", novalidate: true,
    onsubmit: (event) => { event.preventDefault(); runSearch(view); },
  }, [view.input, view.button]);

  root.append(hero(form), el("div", { className: "container" }, view.results));
  view.input.focus();
}

function hero(form) {
  return el("section", { className: "hero" }, [
    el("h1", { className: "hero-title", text: "Find AI news in the articles we have collected" }),
    el("p", { className: "hero-subtitle", text: "Search by topic or question. Results come only from stored articles." }),
    form,
    el("p", { className: "hero-hint", text: "Links are not accepted here: type words, not an article URL." }),
  ]);
}

async function runSearch(view) {
  if (view.busy) return; // one request at a time
  const query = view.input.value.trim();
  if (query.length < MIN_QUERY_LENGTH) {
    showInResults(view, infoBanner(`Please type at least ${MIN_QUERY_LENGTH} characters.`));
    return;
  }
  setBusy(view, true);
  const stopSlowHint = showLoadingWithSlowHint(view);
  try {
    const data = await request(SEARCH_PATH, {
      method: "POST", body: { input: query }, timeoutMs: SEARCH_TIMEOUT_MS,
    });
    view.results.replaceChildren(resultsPanel(query, data.sources ?? []));
  } catch (error) {
    if (!error?.kind) console.error(error); // a bug, not an API answer
    showInResults(view, errorBanner(error));
  } finally {
    stopSlowHint();
    setBusy(view, false);
  }
}

// Shows "Searching…", plus SLOW_HINT if the answer takes longer than SLOW_HINT_DELAY_MS.
// Results or an error replace the whole loading card, hint included.
function showLoadingWithSlowHint(view) {
  const box = el("div", { className: "loading-box" }, loading("Searching…"));
  showInResults(view, box);
  const timer = setTimeout(() => {
    box.append(el("p", { className: "state state-hint", text: SLOW_HINT }));
  }, SLOW_HINT_DELAY_MS);
  return () => clearTimeout(timer);
}

function setBusy(view, busy) {
  view.busy = busy;
  view.button.disabled = busy;
  view.button.textContent = busy ? "Searching…" : "Search";
  view.results.setAttribute("aria-busy", String(busy));
}

function showInResults(view, node) {
  view.results.replaceChildren(card(node));
}

function resultsPanel(query, sources) {
  if (sources.length === 0) {
    return card(emptyState(`No articles found for "${query}".`, "Try other words or a broader topic."));
  }
  const count = `${sources.length} matching article${sources.length === 1 ? "" : "s"}`;
  return el("div", { className: "results-panel" }, [
    card(el("div", { className: "results-header" }, [
      el("h2", { className: "results-title", text: "Related articles" }),
      el("p", { className: "results-count", text: count }),
    ])),
    el("ol", { className: "result-list" }, sources.map(resultCard)),
  ]);
}

function resultCard(source, index) {
  const [summaryLabel, summaryTone] = SUMMARY_LABELS[source.summary_method] ?? ["Summary", "neutral"];
  return el("li", { className: "card result-card" }, [
    el("div", { className: "result-top" }, [
      el("span", { className: "result-index", text: String(index + 1).padStart(2, "0") }),
      source.topic ? badge(source.topic, "primary") : null,
      el("time", { datetime: source.published_at, text: formatDateTime(source.published_at) }),
    ]),
    el("h3", { className: "result-title" }, externalLink(source.url, source.title)),
    el("p", { className: "result-summary", text: source.summary }),
    el("div", { className: "result-meta" }, [
      el("span", { className: "result-source", text: source.source_name }),
      badge(summaryLabel, summaryTone),
      el("span", { title: "Similarity to your search", text: `Match ${formatPercent(source.similarity)}` }),
    ]),
  ]);
}
