// The Search page: hero with search box and trending chips, then results and a
// "Trending topics" sidebar once a search has been made.

import { request, SEARCH_TIMEOUT_MS } from "../api.js";
import { card, errorBanner, infoBanner, loading } from "../components.js";
import { el } from "../dom.js";
import { fetchTrending } from "../trending.js";
import { resultsPanel } from "./search-results.js";
import { trendingChips, trendingSidebar } from "./trending-ui.js";

const SEARCH_PATH = "/api/v1/ai/search";
const MIN_QUERY_LENGTH = 2;
const MAX_QUERY_LENGTH = 500;
const SLOW_HINT_DELAY_MS = 5000;
const SLOW_HINT = "The first search can take up to a minute while the model loads.";

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
  const trending = fetchTrending(); // one shared request for chips and sidebar
  const searchFor = (topic) => { view.input.value = topic; runSearch(view); };
  view.layout = el("div", { className: "search-layout" }, [
    view.results, trendingSidebar(trending, searchFor),
  ]);

  root.append(hero(form, trendingChips(trending, searchFor)),
    el("div", { className: "container" }, view.layout));
  view.input.focus();
}

function hero(form, chips) {
  return el("section", { className: "hero" }, [
    el("h1", { className: "hero-title", text: "Find AI news in the articles we have collected" }),
    el("p", { className: "hero-subtitle", text: "Search by topic or question. Results come only from stored articles." }),
    form,
    chips,
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
    view.layout.classList.add("has-searched"); // shows the sidebar from now on
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
