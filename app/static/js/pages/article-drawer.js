// Article details in the drawer, read from GET /api/v1/articles/{id}.

import { request } from "../api.js";
import { badge, loading } from "../components.js";
import { appendChildren, el, externalLink, safeHref } from "../dom.js";
import { openDrawer } from "../drawer.js";
import { formatDateTime, formatPercent } from "../format.js";

const PREVIEW_CHARS = 4000;
const TITLE_ID = "article-drawer-title";

const STATUS_BADGES = {
  analyzed: ["Analyzed", "success"],
  ai_analyzed: ["Analyzed", "success"],
  pending: ["Pending", "warning"],
  missing_content: ["Title only", "neutral"],
};

// Only the newest open request may fill the drawer; older answers are ignored.
let latestRequest = 0;
let loadingId = null;

/** Opens the drawer for article `id`; `opener` gets the focus back on close. */
export function openArticle(id, opener) {
  if (loadingId === id) return; // the same article is already loading
  const parts = openDrawer({ label: "Article details", opener });
  loadArticle(id, parts);
}

async function loadArticle(id, parts) {
  const requestNumber = ++latestRequest;
  loadingId = id;
  showState(parts, loading("Loading article…"));
  try {
    const article = await request(`/api/v1/articles/${encodeURIComponent(id)}`);
    if (requestNumber !== latestRequest || !parts.panel.isConnected) return;
    renderArticle(parts, article);
  } catch (error) {
    if (requestNumber !== latestRequest || !parts.panel.isConnected) return;
    showState(parts, errorState(error, () => loadArticle(id, parts)));
  } finally {
    if (requestNumber === latestRequest) loadingId = null;
  }
}

function showState(parts, node) {
  parts.setLabel(null);
  parts.header.querySelector(".drawer-header-extra").replaceChildren();
  parts.body.replaceChildren(node);
  parts.footer.replaceChildren();
}

function errorState(error, retry) {
  if (error?.kind === "not_found") {
    return el("p", { className: "banner banner-info", role: "status", text: "This article is no longer available." });
  }
  const message = error?.kind === "network"
    ? "The article could not be loaded. Check your connection and try again."
    : "The article could not be loaded because of a server error.";
  return el("div", { className: "banner banner-error drawer-error", role: "alert" }, [
    el("p", { text: message }),
    el("button", { className: "btn btn-secondary", type: "button", text: "Retry", onclick: retry }),
  ]);
}

function renderArticle(parts, article) {
  const [statusText, tone] = STATUS_BADGES[article.status] ?? [article.status, "neutral"];
  parts.header.querySelector(".drawer-header-extra").replaceChildren(badge(statusText, tone));
  parts.body.replaceChildren();
  appendChildren(parts.body, [ // skips the nulls of missing fields
    article.topic ? badge(article.topic, "primary") : null,
    el("h2", { className: "drawer-title", id: TITLE_ID, text: article.title }),
    article.summary ? el("p", { className: "drawer-lead", text: article.summary }) : null,
    factsGrid(article),
    classificationCard(article),
    contentSection(article.content),
    historySection(article),
  ]);
  parts.setLabel(TITLE_ID);
  parts.footer.replaceChildren(originalLink(article.url));
}

function factsGrid(article) {
  const fact = (label, value) => el("div", { className: "fact" }, [
    el("dt", { text: label }), el("dd", { text: value }),
  ]);
  return el("dl", { className: "facts" }, [
    fact("Author", article.author || "Unknown"),
    fact("Source", article.source_name),
    fact("Published", formatDateTime(article.published_at)),
    fact("Collected", formatDateTime(article.created_at)),
  ]);
}

function classificationCard(article) {
  const rows = [el("div", { className: "classification-row" }, [
    el("span", { text: "Topic" }), el("strong", { text: article.topic || "Not classified yet" }),
  ])];
  if (Number.isFinite(article.confidence)) {
    const bar = el("div", { className: "meter" }, el("span", { className: "meter-fill" }));
    bar.style.setProperty("--bar", formatPercent(article.confidence));
    rows.push(el("div", { className: "classification-row" }, [
      el("span", { text: "Classification confidence" }),
      el("strong", { text: formatPercent(article.confidence) }),
    ]), bar);
  }
  return el("section", { className: "card drawer-card" }, [
    el("h3", { className: "drawer-section-title", text: "Classification" }), ...rows,
  ]);
}

function contentSection(content) {
  const title = el("h3", { className: "drawer-section-title", text: "Collected content" });
  const text = (content ?? "").trim();
  if (!text) {
    return el("section", {}, [title, el("p", { className: "state", text: "No text was collected for this article." })]);
  }
  const isLong = text.length > PREVIEW_CHARS;
  const body = el("div", { className: "drawer-content" }, paragraphs(text.slice(0, PREVIEW_CHARS), isLong));
  const section = el("section", {}, [title, body]);
  if (isLong) {
    const more = el("button", {
      className: "btn btn-secondary", type: "button", text: "Show full text",
      onclick: () => { body.replaceChildren(...paragraphs(text, false)); more.remove(); },
    });
    section.append(more);
  }
  return section;
}

// One <p> per block of text separated by a blank line.
function paragraphs(text, cut) {
  const blocks = text.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);
  if (cut && blocks.length) blocks[blocks.length - 1] += "…";
  return blocks.map((block) => el("p", { text: block }));
}

function historySection(article) {
  const step = (label, when) => el("li", { className: "timeline-step" }, [
    el("strong", { text: label }), el("time", { datetime: when, text: formatDateTime(when) }),
  ]);
  return el("section", {}, [
    el("h3", { className: "drawer-section-title", text: "Source & data history" }),
    el("ol", { className: "timeline" }, [
      article.published_at ? step("Published", article.published_at) : null,
      step("Collected", article.created_at),
    ]),
  ]);
}

function originalLink(url) {
  if (safeHref(url) === null) return el("p", { className: "state", text: "Original link unavailable" });
  return externalLink(url, "Open original article", { className: "btn btn-primary" });
}
