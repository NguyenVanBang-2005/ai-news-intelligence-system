// Articles of the selected topic: GET /api/v1/articles?topic=<label>, newest published first.
// A row opens the article drawer of the Search page.

import { request } from "../api.js";
import { emptyState, errorMessage, loading } from "../components.js";
import { el } from "../dom.js";
import { formatCount, formatDateTime } from "../format.js";
import { openArticle } from "./article-drawer.js";

export const PAGE_SIZE = 20;
const HEADING_ID = "topic-articles-title";

/** The articles path for an exact topic label; `topic` null means all articles. */
export function articlesPath(topic, limit, offset = 0) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (topic !== null) params.set("topic", topic);
  return `/api/v1/articles?${params}`;
}

/** The panel, hidden until show(topic, title) is called. */
export function topicArticlesPanel() {
  const view = {
    topic: null, offset: 0, latestLoad: 0,
    heading: el("h2", { className: "panel-title", id: HEADING_ID, tabindex: "-1" }),
    count: el("p", { className: "panel-subtitle" }),
    list: el("ol", { className: "topic-article-list" }),
    status: el("div", { "aria-live": "polite" }),
    more: el("button", { className: "btn btn-secondary", type: "button", text: "Load more", hidden: true }),
  };
  view.more.addEventListener("click", () => loadPage(view));
  view.node = el("section", {
    className: "card topic-articles", "aria-labelledby": HEADING_ID, hidden: true,
  }, [el("div", { className: "panel-head" }, [view.heading, view.count]), view.list, view.status, view.more]);
  return { node: view.node, show: (topic, title) => showTopic(view, topic, title) };
}

function showTopic(view, topic, title) {
  view.topic = topic;
  view.offset = 0;
  view.heading.textContent = `Articles: ${title}`;
  view.count.textContent = "";
  view.list.replaceChildren();
  view.node.hidden = false;
  view.heading.focus();
  loadPage(view);
}

// Only the answer to the newest request is shown; an older, slower answer is dropped.
async function loadPage(view) {
  const loadNumber = ++view.latestLoad;
  view.more.hidden = true;
  view.status.replaceChildren(loading("Loading articles…"));
  try {
    const page = await request(articlesPath(view.topic, PAGE_SIZE, view.offset));
    if (loadNumber !== view.latestLoad) return;
    showPage(view, page?.items ?? [], page?.total ?? 0);
  } catch (error) {
    if (loadNumber !== view.latestLoad) return;
    view.status.replaceChildren(el("div", { className: "banner banner-error list-error", role: "alert" }, [
      el("p", { text: `The articles could not be loaded. ${errorMessage(error)}` }),
      el("button", { className: "btn btn-secondary", type: "button", text: "Retry", onclick: () => loadPage(view) }),
    ]));
  }
}

function showPage(view, items, total) {
  view.list.append(...items.map(articleRow));
  view.offset += items.length;
  view.count.textContent = `${formatCount(total)} article${total === 1 ? "" : "s"}, newest first`;
  view.status.replaceChildren(total === 0 ? emptyState("No articles in this topic.") : "");
  view.more.hidden = items.length === 0 || view.offset >= total;
}

function articleRow(article) {
  const open = (event) => openArticle(article.id, event.currentTarget);
  return el("li", { className: "topic-article" }, [
    el("button", { className: "result-title-button topic-article-title", type: "button", text: article.title, onclick: open }),
    el("p", { className: "topic-article-meta" }, [
      el("span", { className: "topic-article-source", text: article.source_name ?? "" }),
      el("time", { datetime: article.published_at ?? null, text: formatDateTime(article.published_at) }),
    ]),
  ]);
}
