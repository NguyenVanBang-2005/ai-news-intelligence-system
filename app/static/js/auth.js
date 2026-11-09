// Sign-in calls to /api/v1/auth. The session is an HttpOnly cookie set by the server:
// this code never sees or stores it, and passwords are only sent, never kept or logged.

import { ApiError, detailText, request } from "./api.js";

const AUTH_PATH = "/api/v1/auth";

/** The signed-in user ({ id, username, role }), or null when not signed in (401). */
export async function fetchCurrentUser() {
  try {
    return await request(`${AUTH_PATH}/me`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

/** Logs in and returns the user; the server sets the session cookie. */
export function logIn(username, password) {
  return request(`${AUTH_PATH}/login`, { method: "POST", body: { username, password } });
}

/** Creates an account (role "user") and returns it; it does not log in. */
export function register(username, password) {
  return request(`${AUTH_PATH}/register`, { method: "POST", body: { username, password } });
}

/** Ends the session on the server and clears the cookie. */
export async function logOut() {
  await request(`${AUTH_PATH}/logout`, { method: "POST" });
}

/** The message to show for a failed login or registration: the server's detail if any. */
export function authErrorText(error) {
  const detail = detailText(error);
  if (error?.status === 429) {
    const wait = Number.isFinite(error.retryAfter) && error.retryAfter > 0
      ? ` Please wait ${error.retryAfter} second${error.retryAfter === 1 ? "" : "s"} and try again.`
      : " Please wait and try again.";
    return `${detail ?? "Too many attempts."}${wait}`;
  }
  if (detail) return detail;
  if (error?.kind === "network") return "The server could not be reached. Please try again.";
  return "Something went wrong on the server. Please try again later.";
}
