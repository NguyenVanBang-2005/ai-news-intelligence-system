// A modal "are you sure?" box (role="alertdialog"), used instead of window's built-in one.
// Focus starts on Cancel and stays inside; Esc or a backdrop click cancels;
// focus returns to the element that opened it.

import { el } from "./dom.js";
import { keepFocusInside } from "./focus-trap.js";

const BODY_LOCK_CLASS = "dialog-open";
const TITLE_ID = "confirm-dialog-title";
const MESSAGE_ID = "confirm-dialog-message";

/**
 * Shows the dialog and resolves to true (confirmed) or false (cancelled).
 * `lines`: paragraphs of plain text. `danger`: the confirm button is red.
 */
export function confirmDialog({ title, lines, confirmText, cancelText = "Cancel", danger = false, opener }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (answer) => {
      if (done) return; // a second click while closing does nothing
      done = true;
      close();
      resolve(answer);
    };
    const cancelButton = el("button", {
      className: "btn btn-secondary", type: "button", text: cancelText, onclick: () => finish(false),
    });
    const confirmButton = el("button", {
      className: `btn ${danger ? "btn-danger" : "btn-primary"}`, type: "button", text: confirmText,
      onclick: () => finish(true),
    });
    const box = el("div", {
      className: "dialog", role: "alertdialog", "aria-modal": "true",
      "aria-labelledby": TITLE_ID, "aria-describedby": MESSAGE_ID,
    }, [
      el("h2", { className: "dialog-title", id: TITLE_ID, text: title }),
      el("div", { className: "dialog-message", id: MESSAGE_ID }, lines.map((line) => el("p", { text: line }))),
      el("div", { className: "dialog-actions" }, [cancelButton, confirmButton]),
    ]);
    const backdrop = el("div", { className: "dialog-backdrop", onclick: () => finish(false) });
    const onKey = (event) => handleKey(event, box, () => finish(false));
    const onLeave = () => finish(false); // the page changed behind the dialog
    const close = () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("hashchange", onLeave);
      backdrop.remove();
      box.remove();
      document.body.classList.remove(BODY_LOCK_CLASS);
      if (opener?.isConnected) opener.focus();
    };
    document.body.append(backdrop, box);
    document.body.classList.add(BODY_LOCK_CLASS);
    document.addEventListener("keydown", onKey);
    window.addEventListener("hashchange", onLeave);
    cancelButton.focus();
  });
}

function handleKey(event, box, cancel) {
  if (event.key === "Escape") {
    event.preventDefault();
    cancel();
  } else if (event.key === "Tab") {
    keepFocusInside(event, box);
  }
}
