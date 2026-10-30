// "Latest classified articles": GET /api/v1/articles?status=ai_analyzed, newest published
// first, with one filter pill per topic from GET /api/v1/ai/topics. A row opens the
// article drawer of the Search page.

import { request } from "../api.js";
import { badge, emptyState, errorMessage, loading } from "../components.js";
import { el } from "../dom.js";
import { formatPercent } from "../format.js";
import { openArticle } from "./article-drawer.js";

const ARTICLE_LIMIT = 10;
const MAX_TOPIC_PILLS = 8;
const NO_TOPICS_HINT = "Topics appear after the AI processing job has run.";

/** The articles path for a topic label, or for all topics when `topic` is null. */
export function classifiedPath(topic) {
  const base = `/api/v1/articles?status=ai_analyzed&limit=${ARTICLE_LIMIT}`;
  return topic === null ? base : `${base}&topic=${encodeURIComponent(topic)}`;
}

export function classifiedSection() {
  const view = {
    topic: null,
    latestLoad: 0,
    pills: el("div", { className: "pill-row", role: "group", "aria-label": "Filter by topic" }),
    hint: el("p", { className: "state state-hint", hidden: true, text: NO_TOPICS_HINT }),
    body: el("div", { className: "classified-body", "aria-live": "polite" }),
  };
  renderPills(view, []);
  loadTopics(view);
  loadArticles(view);
  return el("section", { className: "card classified-card", "aria-labelledby": "classified-title" }, [
    el("div", { className: "classified-head" }, [
      el("div", {}, [
        el("h2", { className: "panel-title", id: "classified-title", text: "Latest classified articles" }),
        el("p", { className: "panel-subtitle", text: "Articles with an AI topic, newest published first." }),
      ]),
      view.pills,
    ]),
    view.hint,
    view.body,
  ]);
}

async function loadTopics(view) {
  try {
    const topics = await request("/api/v1/ai/topics");
    const labels = topLabels(Array.isArray(topics) ? topics : []);
    renderPills(view, labels);
    view.hint.hidden = labels.length > 0;
  } catch {
    view.hint.textContent = "Topics could not be loaded. Only the full list is shown.";
    view.hint.hidden = false;
  }
}

// The labels of the largest topics, without blanks or repeats.
function topLabels(topics) {
  const sorted = [...topics].sort((a, b) => (b.size ?? 0) - (a.size ?? 0));
  const labels = sorted.map((topic) => String(topic.label ?? "").trim()).filter(Boolean);
  return [...new Set(labels)].slice(0, MAX_TOPIC_PILLS);
}

function renderPills(view, labels) {
  const choices = [{ label: "All", topic: null }, ...labels.map((label) => ({ label, topic: label }))];
  view.pillTopics = choices.map((choice) => choice.topic);
  view.pills.replaceChildren(...choices.map((choice) => el("button", {
    className: "pill", type: "button", text: choice.label,
    "aria-pressed": String(choice.topic === view.topic),
    onclick: () => pickTopic(view, choice.topic),
  })));
}

function pickTopic(view, topic) {
  view.topic = topic;
  view.pills.querySelectorAll(".pill").forEach((pill, index) => {
    pill.setAttribute("aria-pressed", String(view.pillTopics[index] === topic));
  });
  loadArticles(view);
}

// Only the answer to the newest request is shown; slower older answers are dropped.
async function loadArticles(view) {
  const loadNumber = ++view.latestLoad;
  const topic = view.topic;
  view.body.replaceChildren(loading("Loading articles…"));
  try {
    const page = await request(classifiedPath(topic));
    if (loadNumber !== view.latestLoad) return;
    view.body.replaceChildren(articleList(page?.items ?? [], topic));
  } catch (error) {
    if (loadNumber !== view.latestLoad) return;
    view.body.replaceChildren(el("div", { className: "banner banner-error list-error", role: "alert" }, [
      el("p", { text: `The articles could not be loaded. ${errorMessage(error)}` }),
      el("button", { className: "btn btn-secondary", type: "button", text: "Retry", onclick: () => loadArticles(view) }),
    ]));
  }
}

function articleList(items, topic) {
  if (items.length === 0) {
    return topic === null
      ? emptyState("No classified articles yet.", NO_TOPICS_HINT)
      : emptyState("No classified articles for this topic.");
  }
  return el("ol", { className: "classified-list" }, items.map(articleRow));
}

function articleRow(article, index) {
  const open = (event) => openArticle(article.id, event.currentTarget);
  return el("li", { className: "classified-row" }, [
    el("span", { className: "result-index", text: String(index + 1).padStart(2, "0") }),
    el("div", { className: "classified-main" }, [
      el("div", { className: "result-top" }, [
        article.topic ? badge(article.topic, "primary") : null,
        el("span", { className: "classified-source", text: article.source_name ?? "" }),
      ]),
      el("h3", { className: "result-title" }, el("button", {
        className: "result-title-button", type: "button", text: article.title, onclick: open,
      })),
      article.summary ? el("p", { className: "result-summary", text: article.summary }) : null,
    ]),
    confidenceMeter(article.confidence),
    el("button", {
      className: "result-open", type: "button", text: "→", onclick: open,
      "aria-label": `Open details: ${article.title}`,
    }),
  ]);
}

function confidenceMeter(confidence) {
  if (!Number.isFinite(confidence)) return el("span", { className: "classified-confidence" });
  const bar = el("span", { className: "meter meter-success" }, el("span", { className: "meter-fill" }));
  bar.style.setProperty("--bar", formatPercent(confidence));
  return el("div", { className: "classified-confidence" }, [
    el("span", { className: "confidence-label", text: `Confidence ${formatPercent(confidence)}` }), bar,
  ]);
}
