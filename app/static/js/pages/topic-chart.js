// "Articles per day" for the trending topics: GET /api/v1/topics/timeseries, one small bar
// chart per topic, drawn as SVG with attributes only (no style attribute, no library).

import { request } from "../api.js";
import { loading } from "../components.js";
import { el } from "../dom.js";
import { formatCount, formatShortDay } from "../format.js";
import { TRENDING_PARAMS } from "../trending.js";
import { labelKeywords } from "./topic-cards.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const CHART_DAYS = 7;
const CHART_TOPICS = 5;
const CHART = { width: 280, height: 64, gap: 4, minBar: 1 };

export function timeseriesPath() {
  const { window_hours, baseline_days, min_articles } = TRENDING_PARAMS;
  const params = { days: CHART_DAYS, limit: CHART_TOPICS, window_hours, baseline_days, min_articles };
  return `/api/v1/topics/timeseries?${new URLSearchParams(params)}`;
}

/** The chart card; it loads its own data and shows a short message if there is none. */
export function timeseriesSection() {
  const body = el("div", { className: "chart-body", "aria-live": "polite" }, loading("Loading chart…"));
  loadSeries(body);
  return el("section", { className: "card topic-chart", "aria-labelledby": "topic-chart-title" }, [
    el("div", { className: "panel-head chart-head" }, [
      el("h2", { className: "panel-title", id: "topic-chart-title", text: "Articles per day" }),
      el("p", { className: "panel-subtitle", text: `Trending topics, last ${CHART_DAYS} days (UTC)` }),
    ]),
    body,
  ]);
}

async function loadSeries(body) {
  try {
    const series = await request(timeseriesPath());
    const usable = Array.isArray(series) ? series.filter((item) => Array.isArray(item.points)) : [];
    if (usable.length === 0) body.replaceChildren(message(emptyText()));
    else body.replaceChildren(...[dateAxis(usable), seriesList(usable)].filter(Boolean));
  } catch {
    body.replaceChildren(message("The chart is unavailable right now."));
  }
}

function emptyText() {
  return `No topic is trending in the last ${TRENDING_PARAMS.window_hours} hours, so there is nothing to chart.`;
}

function message(text) {
  return el("p", { className: "state", text });
}

/**
 * One date row for all charts (they share the same days): first and last day of the API
 * points, placed over the bar column. Null when the API sent no usable days.
 */
export function axisDays(series) {
  const points = series.find((item) => item.points.length > 0)?.points ?? [];
  const first = formatShortDay(points[0]?.date);
  const last = formatShortDay(points[points.length - 1]?.date);
  return first && last ? { first, last } : null;
}

function dateAxis(series) {
  const days = axisDays(series);
  if (!days) return null;
  return el("div", { className: "chart-axis", "aria-hidden": "true" }, [
    el("span", { className: "chart-axis-spacer" }),
    el("span", { className: "chart-axis-days" }, [
      el("span", { className: "chart-axis-first", text: days.first }),
      el("span", { className: "chart-axis-last", text: days.last }),
    ]),
    el("span", { className: "chart-axis-spacer" }),
  ]);
}

function seriesList(series) {
  const peak = Math.max(1, ...series.flatMap((item) => item.points.map((point) => point.count)));
  return el("ul", { className: "chart-list" }, series.map((item) => el("li", { className: "chart-row" }, [
    el("span", { className: "chart-name", text: labelKeywords(item.topic).slice(0, 3).join(" · ") }),
    barChart(item, peak),
    el("span", { className: "chart-total", text: `${formatCount(sum(item.points))} in ${item.points.length} days` }),
  ])));
}

function sum(points) {
  return points.reduce((total, point) => total + (Number.isFinite(point.count) ? point.count : 0), 0);
}

/** One SVG bar per day; bar heights share `peak` so topics can be compared. */
function barChart(item, peak) {
  const { width, height, gap } = CHART;
  const barWidth = (width - gap * (item.points.length - 1)) / Math.max(1, item.points.length);
  const svg = svgNode("svg", {
    // "none": the bars fill the whole column, so the date row above lines up with them.
    class: "chart-svg", viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", role: "img",
    "aria-label": `${item.topic}: ${item.points.map((p) => `${p.date} ${p.count}`).join(", ")}`,
  });
  item.points.forEach((point, index) => svg.append(bar(point, index * (barWidth + gap), barWidth, peak)));
  return svg;
}

function bar(point, x, barWidth, peak) {
  const count = Number.isFinite(point.count) ? point.count : 0;
  const barHeight = count > 0 ? Math.max(CHART.minBar, (count / peak) * CHART.height) : CHART.minBar;
  const rect = svgNode("rect", {
    class: count > 0 ? "chart-bar" : "chart-bar chart-bar-empty",
    x: x.toFixed(1), y: (CHART.height - barHeight).toFixed(1),
    width: barWidth.toFixed(1), height: barHeight.toFixed(1), rx: 2,
  });
  const tooltip = svgNode("title");
  tooltip.textContent = `${point.date}: ${formatCount(count)} article${count === 1 ? "" : "s"}`;
  rect.append(tooltip);
  return rect;
}

// SVG elements need the SVG namespace; attributes are set one by one, never "style".
function svgNode(tag, attributes = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name.toLowerCase() === "style") throw new TypeError("svgNode() does not set style");
    node.setAttribute(name, String(value));
  }
  return node;
}
