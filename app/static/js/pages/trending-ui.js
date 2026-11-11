// Trending chips under the search box and the "Trending topics" sidebar.

import { loading, progressBar } from "../components.js";
import { el } from "../dom.js";
import { formatCount, formatScore } from "../format.js";
import { fallbackNotice, NO_TRENDING_TEXT, TRENDING_PARAMS, windowLabel, windowPhrase } from "../trending.js";

const MAX_CHIPS = 4;
const UNAVAILABLE = "Trending is unavailable right now.";

/** The "Trending:" chip row; it stays hidden unless there are topics. */
export function trendingChips(trendingPromise, onPick) {
  const row = el("div", { className: "trending-chips", hidden: true });
  trendingPromise.then(({ topics, windowHours }) => {
    const top = strongestFirst(topics).slice(0, MAX_CHIPS);
    if (top.length === 0) return;
    // Says which window the chips come from when it is not the usual one.
    const label = windowHours === TRENDING_PARAMS.window_hours
      ? "Trending:" : `Trending (last ${windowPhrase(windowHours)}):`;
    row.append(el("span", { className: "trending-chips-label", text: label }),
      ...top.map((item) => el("button", {
        className: "chip", type: "button", text: item.topic, onclick: () => onPick(item.topic),
      })));
    row.hidden = false;
  }).catch(() => {}); // the row just stays hidden
  return row;
}

/** The sidebar card: loading, then the list, an empty message or an error message. */
export function trendingSidebar(trendingPromise, onPick) {
  const list = el("div", { className: "trend-content" }, loading("Loading trending topics…"));
  const windowTag = el("span", { className: "trend-window", text: windowLabel(TRENDING_PARAMS.window_hours) });
  const captionLine = el("p", { className: "trend-caption", text: caption(TRENDING_PARAMS.window_hours) });
  trendingPromise.then(({ topics, windowHours }) => {
    windowTag.textContent = windowLabel(windowHours);
    captionLine.textContent = caption(windowHours);
    if (topics.length === 0) {
      list.replaceChildren(message(NO_TRENDING_TEXT));
      return;
    }
    const notice = fallbackNotice(windowHours);
    list.replaceChildren(...[
      notice ? el("p", { className: "state state-hint", text: notice }) : null,
      trendList(strongestFirst(topics), onPick),
    ].filter(Boolean));
  }).catch(() => list.replaceChildren(message(UNAVAILABLE)));
  return el("aside", { className: "card search-sidebar", "aria-label": "Trending topics" }, [
    el("div", { className: "trend-header" }, [
      el("h2", { className: "trend-title", text: "Trending topics" }),
      windowTag,
    ]),
    list,
    captionLine,
  ]);
}

function caption(windowHours) {
  const days = TRENDING_PARAMS.baseline_days;
  return `Score compares the last ${windowPhrase(windowHours)} with the usual level over the previous ${days} days. Approximate.`;
}

function message(text) {
  return el("p", { className: "state trend-message", text });
}

function strongestFirst(topics) {
  return [...topics].sort((a, b) => b.trend_score - a.trend_score);
}

function trendList(topics, onPick) {
  const top = Math.max(...topics.map((item) => item.trend_score), 0);
  return el("ol", { className: "trend-list" }, topics.map((item, index) => {
    const share = top > 0 ? Math.max(0, item.trend_score) / top : 0;
    const bar = progressBar(share, { className: "trend-bar" }); // decorative: the score is shown
    const count = `${formatCount(item.article_count)} article${item.article_count === 1 ? "" : "s"}`;
    return el("li", {}, el("button", {
      className: "trend-item", type: "button", onclick: () => onPick(item.topic),
      "aria-label": `Search for ${item.topic}`,
    }, [
      el("span", { className: "trend-rank", text: String(index + 1) }),
      el("span", { className: "trend-main" }, [
        el("span", { className: "trend-name", text: item.topic }), bar,
        el("span", { className: "trend-count", text: count }),
      ]),
      el("span", { className: "trend-score", text: formatScore(item.trend_score) }),
    ]));
  }));
}
