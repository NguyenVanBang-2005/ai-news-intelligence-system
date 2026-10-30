// Trending topics from GET /api/v1/topics/trending, kept in memory for a short time.

import { request } from "./api.js";

// The parameters actually sent; the sidebar reads its "24h" / "7 days" labels from here.
export const TRENDING_PARAMS = Object.freeze({
  window_hours: 24,
  baseline_days: 7,
  min_articles: 2,
  limit: 10,
});

const CACHE_MS = 60000;

let cached = null; // { at: time in ms, promise }

export function trendingPath(params = TRENDING_PARAMS) {
  return `/api/v1/topics/trending?${new URLSearchParams(params)}`;
}

/**
 * The trending list ([{topic, article_count, expected_count, trend_score}]), strongest first.
 * Callers within CACHE_MS share one request. A failed request is not cached.
 */
export function fetchTrending() {
  if (cached && Date.now() - cached.at < CACHE_MS) return cached.promise;
  const promise = request(trendingPath()).then((topics) => (Array.isArray(topics) ? topics : []));
  cached = { at: Date.now(), promise };
  promise.catch(() => {
    if (cached?.promise === promise) cached = null; // let the next page visit try again
  });
  return promise;
}
