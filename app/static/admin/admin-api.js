// API calls of the admin page. They go through request() in js/api.js (session cookie +
// "X-Requested-With: ainis"); a 401/403 means the session ended or lost its admin role.

import { detailText, request } from "../js/api.js";
import { errorMessage } from "../js/components.js";
import { el } from "../js/dom.js";

let sessionLostHandler = () => {};

/** Registers what to do when the server answers 401/403 (show the log-in screen). */
export function onSessionLost(handler) {
  sessionLostHandler = handler;
}

/** request() for admin endpoints; 401/403 also call the session-lost handler. */
export async function adminRequest(path, options = {}) {
  try {
    return await request(path, options);
  } catch (error) {
    if (error?.status === 401 || error?.status === 403) sessionLostHandler(error);
    throw error;
  }
}

/** The server's `detail` word for word when it sent one, else a general message. */
export function adminErrorText(error) {
  if (!error?.kind) console.error(error); // a bug, not an API answer
  return detailText(error) ?? errorMessage(error);
}

/** A banner for a message; tone "error" is announced at once (role="alert"). */
export function messageBanner(text, tone) {
  return el("p", { className: `banner banner-${tone}`, role: tone === "error" ? "alert" : "status", text });
}
