// Trending topics from GET /api/v1/topics/trending, kept in memory for a short time.

import { request } from "./api.js";

// The parameters of the first request; the sidebar reads its "24h" / "7 days" labels from here.
export const TRENDING_PARAMS = Object.freeze({
  window_hours: 24,
  baseline_days: 7,
  min_articles: 2,
  limit: 10,
});

// Used only when the window above has no trending topic (for example, every article is
// older than a day). The widest window the API accepts: le=168 in app/api/routes/topics.py.
export const FALLBACK_WINDOW_HOURS = 168;

export const NO_TRENDING_TEXT =
  "No topics yet. An administrator can run the demo seed script to load articles.";

const CACHE_MS = 60000;

let cached = null; // { at: time in ms, promise }

export function trendingPath(params = TRENDING_PARAMS) {
  return `/api/v1/topics/trending?${new URLSearchParams(params)}`;
}

/**
 * { topics, windowHours }: the trending list ([{topic, article_count, expected_count,
 * trend_score}]) and the window it was computed for. That is TRENDING_PARAMS.window_hours,
 * or FALLBACK_WINDOW_HOURS when the first window had no topic. Callers within CACHE_MS share
 * one result. A failed request is not cached.
 */
export function fetchTrending() {
  if (cached && Date.now() - cached.at < CACHE_MS) return cached.promise;
  const promise = loadTrending();
  cached = { at: Date.now(), promise };
  promise.catch(() => {
    if (cached?.promise === promise) cached = null; // let the next page visit try again
  });
  return promise;
}

async function loadTrending() {
  const topics = await requestTopics(TRENDING_PARAMS);
  if (topics.length > 0) return { topics, windowHours: TRENDING_PARAMS.window_hours };
  const wider = { ...TRENDING_PARAMS, window_hours: FALLBACK_WINDOW_HOURS };
  return { topics: await requestTopics(wider), windowHours: FALLBACK_WINDOW_HOURS };
}

async function requestTopics(params) {
  const topics = await request(trendingPath(params));
  return Array.isArray(topics) ? topics : [];
}

/** "24h" for windows under two days, otherwise "7 days". */
export function windowLabel(hours) {
  return hours < 48 ? `${hours}h` : `${Math.round(hours / 24)} days`;
}

/** "24 hours" or "7 days", for sentences. */
export function windowPhrase(hours) {
  return hours < 48 ? `${hours} hours` : `${Math.round(hours / 24)} days`;
}

/** The note shown when the wider window is in use; null for the normal window. */
export function fallbackNotice(windowHours) {
  if (windowHours === TRENDING_PARAMS.window_hours) return null;
  return `No trending topics in the last ${windowPhrase(TRENDING_PARAMS.window_hours)}. ` +
    `Showing the last ${windowPhrase(windowHours)}.`;
}
