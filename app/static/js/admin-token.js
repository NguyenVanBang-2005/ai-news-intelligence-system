// The admin token for this browser tab, and admin requests that send it.
// The token lives in sessionStorage only (or in memory if sessionStorage is blocked).
// It is never logged, put in a URL, a cookie, a DOM attribute or an error message.

import { request } from "./api.js";

const STORAGE_KEY = "ainis.adminToken";

export const TOKEN_REJECTED_MESSAGE = "The admin token was rejected. Enter it again.";
export const TOKEN_UNCONFIGURED_MESSAGE = "The server has no admin token configured.";
export const NEEDS_TOKEN_MESSAGE = "Enter the admin token to manage sources.";

let memoryToken = null; // used only when sessionStorage cannot be used
// "none" | "unverified" | "verified" | "rejected" | "unconfigured"
let status = readToken() ? "unverified" : "none";
const listeners = new Set();

function readToken() {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) || memoryToken;
  } catch {
    return memoryToken; // storage blocked (privacy settings, sandbox)
  }
}

function writeToken(token) {
  memoryToken = null;
  try {
    if (token) window.sessionStorage.setItem(STORAGE_KEY, token);
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    memoryToken = token || null;
  }
}

export function hasToken() {
  return Boolean(readToken());
}

/** "none", "unverified", "verified", "rejected" or "unconfigured". */
export function tokenStatus() {
  return status;
}

/** Calls `listener(status)` on every change; returns a function that stops it. */
export function onTokenChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function setStatus(next, { always = false } = {}) {
  if (next === status && !always) return;
  status = next;
  for (const listener of [...listeners]) listener(status);
}

/** Saves a token typed by the user; it is not checked until an admin request is made. */
export function saveToken(value) {
  const token = String(value ?? "").trim();
  if (!token) return false;
  writeToken(token);
  setStatus("unverified", { always: true }); // a new token is never verified yet
  return true;
}

export function clearToken() {
  writeToken(null);
  setStatus("none");
}

/**
 * Sends an admin request with the token in its header. A success marks the token as
 * verified; 401 and 503 update the status. Errors are re-thrown for the caller.
 */
export async function adminRequest(path, options = {}) {
  const token = readToken();
  if (!token) throw new Error("adminRequest() needs a token; check hasToken() first");
  try {
    const data = await request(path, { ...options, admin: token });
    setStatus("verified");
    return data;
  } catch (error) {
    if (error?.status === 401) setStatus("rejected");
    else if (error?.status === 503) setStatus("unconfigured");
    throw error;
  }
}

/** The message for a failed admin request, or null if it is not a token problem. */
export function tokenErrorMessage(error) {
  if (error?.status === 401) return TOKEN_REJECTED_MESSAGE;
  if (error?.status === 503) return TOKEN_UNCONFIGURED_MESSAGE;
  return null;
}
