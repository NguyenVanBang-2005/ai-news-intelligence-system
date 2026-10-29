// Calls to the AINIS API on the same origin, with errors sorted into a few kinds.

export const DEFAULT_TIMEOUT_MS = 20000;
// The first search after a server start may wait for the embedding model to load.
export const SEARCH_TIMEOUT_MS = 60000;

const KIND_BY_STATUS = {
  401: "unauthorized",
  404: "not_found",
  413: "too_large",
  422: "validation",
  429: "rate_limited",
  503: "unavailable",
};

/** An API failure. `kind` is one of the values of KIND_BY_STATUS, "network" or "server". */
export class ApiError extends Error {
  constructor(kind, { status = null, detail = null, retryAfter = null, timedOut = false } = {}) {
    super(`API error: ${kind}${status ? ` (HTTP ${status})` : ""}`);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
    this.retryAfter = retryAfter;
    this.timedOut = timedOut;
  }
}

/**
 * Sends one request and returns the parsed JSON body, or throws an ApiError.
 * `admin` is an admin token passed by the caller; it is never stored here.
 */
export async function request(path, { method = "GET", body, admin, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  assertSameOriginPath(path);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: buildHeaders(body, admin),
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      signal: controller.signal,
    });
  } catch {
    throw new ApiError("network", { timedOut: controller.signal.aborted });
  } finally {
    clearTimeout(timer);
  }
  const data = await readJson(response);
  if (!response.ok) throw errorFromResponse(response, data);
  return data;
}

// Only paths like "/api/v1/..." are allowed, so a request can never leave this origin.
function assertSameOriginPath(path) {
  if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) {
    throw new TypeError(`request() needs a same-origin path, got ${String(path)}`);
  }
}

function buildHeaders(body, admin) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (admin) headers["X-Admin-Token"] = admin;
  return headers;
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return null; // empty or non-JSON body
  }
}

function errorFromResponse(response, data) {
  const kind = KIND_BY_STATUS[response.status] ?? "server";
  return new ApiError(kind, {
    status: response.status,
    detail: data?.detail ?? null,
    retryAfter: parseRetryAfter(response.headers.get("Retry-After")),
  });
}

/** Retry-After as whole seconds (it may be a number or an HTTP date), or null. */
export function parseRetryAfter(value) {
  if (!value) return null;
  if (/^\d+$/.test(value.trim())) return Number(value.trim());
  const date = Date.parse(value);
  if (Number.isNaN(date)) return null;
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}
