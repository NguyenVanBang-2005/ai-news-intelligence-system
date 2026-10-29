// A modal side panel: focus moves in and is kept inside, Esc or a backdrop click closes it,
// focus returns to the element that opened it, and the page behind does not scroll.

import { el } from "./dom.js";

const FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';
const BODY_LOCK_CLASS = "drawer-open";

let current = null; // the open drawer, if any

/** The open drawer's { panel, header, body, footer, setLabel(id) }, or null. */
export function openDrawerParts() {
  return current?.parts ?? null;
}

/** Opens the drawer (or reuses the open one) and returns its parts to fill. */
export function openDrawer({ label, opener }) {
  if (current) {
    current.opener = opener ?? current.opener;
    return current.parts;
  }
  const parts = buildDrawer(label);
  current = { parts, opener, onKey: (event) => handleKey(event, parts.panel) };
  document.body.append(parts.backdrop, parts.panel);
  document.body.classList.add(BODY_LOCK_CLASS);
  document.addEventListener("keydown", current.onKey);
  parts.closeButton.focus();
  return parts;
}

export function closeDrawer() {
  if (!current) return;
  const { parts, opener, onKey } = current;
  current = null;
  document.removeEventListener("keydown", onKey);
  parts.backdrop.remove();
  parts.panel.remove();
  document.body.classList.remove(BODY_LOCK_CLASS);
  if (opener?.isConnected) opener.focus();
}

function buildDrawer(label) {
  const labelId = "drawer-label";
  const closeButton = el("button", {
    className: "drawer-close", type: "button", "aria-label": "Close", text: "×", onclick: closeDrawer,
  });
  const header = el("div", { className: "drawer-header" }, [
    el("p", { className: "drawer-label", id: labelId, text: label }),
    el("div", { className: "drawer-header-extra" }),
    closeButton,
  ]);
  const body = el("div", { className: "drawer-body" });
  const footer = el("div", { className: "drawer-footer" });
  const panel = el("aside", {
    className: "drawer", role: "dialog", "aria-modal": "true", "aria-labelledby": labelId,
  }, [header, body, footer]);
  const backdrop = el("div", { className: "drawer-backdrop", onclick: closeDrawer });
  const setLabel = (id) => panel.setAttribute("aria-labelledby", id || labelId);
  return { panel, backdrop, header, body, footer, closeButton, setLabel };
}

function handleKey(event, panel) {
  if (event.key === "Escape") {
    event.preventDefault();
    closeDrawer();
  } else if (event.key === "Tab") {
    keepFocusInside(event, panel);
  }
}

// Tab from the last element goes to the first one, Shift+Tab from the first to the last.
function keepFocusInside(event, panel) {
  const items = [...panel.querySelectorAll(FOCUSABLE)].filter((node) => node.offsetParent !== null);
  if (items.length === 0) return;
  const first = items[0];
  const last = items[items.length - 1];
  const inside = panel.contains(document.activeElement);
  if (event.shiftKey && (document.activeElement === first || !inside)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !inside)) {
    event.preventDefault();
    first.focus();
  }
}
