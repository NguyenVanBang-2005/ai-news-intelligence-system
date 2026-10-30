// The Topics page: topics found by BERTopic (GET /api/v1/ai/topics), the outlier group,
// articles per day of the trending topics, and the articles of the selected topic.
// Every number on the page comes from the API.

import { request } from "../api.js";
import { emptyState, errorMessage, loading } from "../components.js";
import { el } from "../dom.js";
import { formatCount } from "../format.js";
import { fetchTrending } from "../trending.js";
import { articlesPath, topicArticlesPanel } from "./topic-articles.js";
import { labelKeywords, outlierCard, topicCard } from "./topic-cards.js";
import { timeseriesSection } from "./topic-chart.js";

// Same as OUTLIER_LABEL in app/services/topic_model.py; not part of GET /ai/topics.
export const OUTLIER_LABEL = "Other / Outlier";
const NO_TOPICS = "No topics yet. An admin can run AI processing.";

export function renderTopicsPage(root) {
  const body = el("div", { className: "topics-body", "aria-live": "polite" }, loading("Loading topics…"));
  root.append(hero(), el("div", { className: "container container-wide topics-page" }, body));
  loadPage(body);
}

function hero() {
  return el("section", { className: "hero hero-topics" }, [
    el("h1", { className: "hero-title", text: "Topics" }),
    el("p", { className: "hero-subtitle", text: "Groups of similar articles found by the topic model. Pick a topic to see its articles." }),
  ]);
}

async function loadPage(body) {
  try {
    const [topics, all, outliers, trending] = await Promise.all([
      request("/api/v1/ai/topics"),
      request(articlesPath(null, 1)),
      request(articlesPath(OUTLIER_LABEL, 1)),
      fetchTrending().catch(() => []), // the page still works without trending badges
    ]);
    if (!body.isConnected) return; // the user has left the page
    body.replaceChildren(...pageContent({
      topics: Array.isArray(topics) ? topics : [],
      total: all?.total ?? 0,
      outlierCount: outliers?.total ?? 0,
      trendingLabels: new Set(trending.map((item) => item.topic)),
    }));
  } catch (error) {
    if (body.isConnected) body.replaceChildren(errorState(error, body));
  }
}

function errorState(error, body) {
  return el("div", { className: "banner banner-error list-error", role: "alert" }, [
    el("p", { text: `Topics could not be loaded. ${errorMessage(error)}` }),
    el("button", {
      className: "btn btn-secondary", type: "button", text: "Retry",
      onclick: () => { body.replaceChildren(loading("Loading topics…")); loadPage(body); },
    }),
  ]);
}

function pageContent({ topics, total, outlierCount, trendingLabels }) {
  if (topics.length === 0) return [emptyState(NO_TOPICS)];
  const panel = topicArticlesPanel();
  const grid = el("div", { className: "topic-grid" });
  const pick = (button, label) => selectTopic(grid, button, label, panel);
  grid.append(...topics.map((topic) => topicCard(topic, {
    total, trending: trendingLabels.has(topic.label), onPick: (button) => pick(button, topic.label),
  })));
  const outlier = outlierCard({
    label: OUTLIER_LABEL, count: outlierCount, total, onPick: (button) => pick(button, OUTLIER_LABEL),
  });
  return [summary(topics.length, total), grid, outlier, timeseriesSection(), panel.node];
}

function summary(topicCount, total) {
  return el("p", { className: "topics-summary" }, [
    el("strong", { text: formatCount(topicCount) }), ` topic${topicCount === 1 ? "" : "s"} in `,
    el("strong", { text: formatCount(total) }), ` article${total === 1 ? "" : "s"}`,
  ]);
}

// Marks the picked card (the outlier card sits outside the grid) and loads its articles.
function selectTopic(grid, button, label, panel) {
  const cards = [...grid.querySelectorAll(".topic-card"), grid.parentElement?.querySelector(".topic-card-outlier")];
  for (const card of cards) card?.setAttribute("aria-pressed", String(card === button));
  const title = label === OUTLIER_LABEL ? OUTLIER_LABEL : labelKeywords(label).join(", ");
  panel.show(label, title);
}
