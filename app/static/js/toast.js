// Short notices in the bottom corner ("Password changed.", "Source enabled: ..."). One at a
// time: a new toast replaces the one on screen. It slides in by CSS and, after TOAST_MS,
// gets the "toast-leaving" class (slide out) and is removed. Text only, via textContent.

import { el } from "./dom.js";

export const TOAST_MS = 4000;
const LEAVE_MS = 200; // --duration-base in style.css

let region = null;

/** Shows `message`; tone "success" (role="status") or "error" (role="alert"). */
export function showToast(message, tone = "success") {
  const toast = el("p", {
    className: `toast toast-${tone}`,
    role: tone === "error" ? "alert" : "status",
    text: message,
  });
  toastRegion().replaceChildren(toast);
  setTimeout(() => {
    toast.classList.add("toast-leaving");
    setTimeout(() => toast.remove(), LEAVE_MS);
  }, TOAST_MS);
}

function toastRegion() {
  if (!region?.isConnected) {
    region = el("div", { className: "toast-region", "aria-live": "polite" });
    document.body.append(region);
  }
  return region;
}
