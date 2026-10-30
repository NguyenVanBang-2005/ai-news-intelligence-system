// Topic cards: keyword chips from the BERTopic label, article count, share of all articles,
// and a "Trending" badge. The outlier group gets its own, quieter card.

import { badge } from "../components.js";
import { el } from "../dom.js";
import { formatCount } from "../format.js";

const LABEL_SEPARATOR = " · ";
const OUTLIER_NOTE = "Articles that did not fit any topic";

/** The keywords of a label like "google ai · google · amazon"; a plain label is one keyword. */
export function labelKeywords(label) {
  const words = String(label ?? "").split(LABEL_SEPARATOR).map((word) => word.trim()).filter(Boolean);
  return words.length ? words : ["Untitled topic"];
}

/** "13.5%" of all articles; "–" when there is no total. */
export function shareText(count, total) {
  if (!Number.isFinite(count) || !Number.isFinite(total) || total <= 0) return "–";
  return `${((count / total) * 100).toFixed(1)}%`;
}

function articlesText(count) {
  return `${formatCount(count)} article${count === 1 ? "" : "s"}`;
}

/** A card button for one topic of GET /ai/topics; `onPick(button)` runs on click. */
export function topicCard(topic, { total, trending, onPick }) {
  const keywords = labelKeywords(topic.label);
  const button = el("button", {
    className: "topic-card", type: "button", "aria-pressed": "false",
    "aria-label": `${keywords.join(", ")}: ${articlesText(topic.size)}, ${shareText(topic.size, total)} of all articles${trending ? ", trending" : ""}`,
  }, [
    el("span", { className: "topic-chips" }, keywords.map((word) => el("span", { className: "topic-chip", text: word }))),
    el("span", { className: "topic-stats" }, [
      el("span", { className: "topic-count", text: articlesText(topic.size) }),
      el("span", { className: "topic-share", text: `${shareText(topic.size, total)} of all` }),
      trending ? badge("Trending", "warning") : null,
    ]),
  ]);
  button.addEventListener("click", () => onPick(button));
  return button;
}

/** The card of the outlier group; its count comes from GET /articles?topic=Other / Outlier. */
export function outlierCard({ label, count, total, onPick }) {
  const button = el("button", {
    className: "topic-card topic-card-outlier", type: "button", "aria-pressed": "false",
    "aria-label": `${label}: ${articlesText(count)}, ${shareText(count, total)} of all articles`,
  }, [
    el("span", { className: "topic-outlier-title", text: label }),
    el("span", { className: "topic-outlier-note", text: OUTLIER_NOTE }),
    el("span", { className: "topic-stats" }, [
      el("span", { className: "topic-count", text: articlesText(count) }),
      el("span", { className: "topic-share", text: `${shareText(count, total)} of all` }),
    ]),
  ]);
  button.addEventListener("click", () => onPick(button));
  return button;
}
