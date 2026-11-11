// The "Change password" modal (role="dialog"), built like auth-dialog.js: focus stays
// inside, Esc or a backdrop click closes it, focus returns to the opener.
// Passwords are only sent to POST /api/v1/auth/change-password, never kept or logged.

import { authErrorText, changePassword } from "./auth.js";
import { el, setButtonBusy } from "./dom.js";
import { keepFocusInside } from "./focus-trap.js";
import { showToast } from "./toast.js";

const BODY_LOCK_CLASS = "dialog-open";
const TITLE_ID = "password-dialog-title";
const MIN_CHARS = 10;
const MAX_CHARS = 128;
const SUBMIT_TEXT = "Change password";
const BUSY_TEXT = "Changing…";
const HINT = `New password: ${MIN_CHARS}-${MAX_CHARS} characters, not your username and not the current one. `
  + "Your other signed-in browsers will be logged out.";

/**
 * The "Change password" controls for the account bar (a list, spread into the bar).
 * Success is announced with a toast that hides itself.
 */
export function changePasswordControls() {
  const button = el("button", { className: "btn btn-secondary btn-small", type: "button", text: "Change password" });
  button.addEventListener("click", () => openPasswordDialog({
    opener: button,
    onChanged: () => showToast("Password changed. Other sessions were logged out.", "success"),
  }));
  return [button];
}

/** Opens the dialog. `onChanged()` runs after the server accepted the new password. */
export function openPasswordDialog({ opener, onChanged }) {
  const view = buildView();
  const close = () => {
    document.removeEventListener("keydown", view.onKey);
    view.backdrop.remove();
    view.box.remove();
    document.body.classList.remove(BODY_LOCK_CLASS);
    if (opener?.isConnected) opener.focus();
  };
  view.onKey = (event) => handleKey(event, view.box, close);
  view.cancel.addEventListener("click", close);
  view.backdrop.addEventListener("click", close);
  view.form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit(view, close, onChanged);
  });
  document.body.append(view.backdrop, view.box);
  document.body.classList.add(BODY_LOCK_CLASS);
  document.addEventListener("keydown", view.onKey);
  view.current.focus();
}

function buildView() {
  const current = passwordInput("password-current", "Current password", "current-password");
  const next = passwordInput("password-new", "New password", "new-password");
  const confirm = passwordInput("password-confirm", "Confirm new password", "new-password");
  const view = {
    current: current.input,
    next: next.input,
    confirm: confirm.input,
    submitButton: el("button", { className: "btn btn-primary", type: "submit", text: SUBMIT_TEXT }),
    cancel: el("button", { className: "btn btn-secondary", type: "button", text: "Cancel" }),
    message: el("div", { className: "form-message", "aria-live": "polite" }),
    backdrop: el("div", { className: "dialog-backdrop" }),
  };
  view.form = el("form", { className: "auth-form", novalidate: true }, [
    current.field, next.field, confirm.field,
    el("p", { className: "form-note", text: HINT }),
    view.message,
    el("div", { className: "dialog-actions" }, [view.cancel, view.submitButton]),
  ]);
  view.box = el("div", { className: "dialog auth-dialog", role: "dialog", "aria-modal": "true", "aria-labelledby": TITLE_ID }, [
    el("h2", { className: "dialog-title", id: TITLE_ID, text: "Change password" }), view.form,
  ]);
  return view;
}

function passwordInput(id, label, autocomplete) {
  const input = el("input", {
    id, name: id, type: "password", className: "field-input", autocomplete, maxlength: MAX_CHARS, spellcheck: "false",
  });
  const field = el("div", { className: "field" }, [el("label", { className: "field-label", for: id, text: label }), input]);
  return { input, field };
}

/** The reason the form cannot be sent yet, or null. Checked again by the server. */
export function passwordFormProblem(current, next, confirm) {
  if (!current || !next || !confirm) return "Fill in all three fields.";
  if (next.length < MIN_CHARS || next.length > MAX_CHARS) {
    return `The new password must be ${MIN_CHARS}-${MAX_CHARS} characters.`;
  }
  if (next !== confirm) return "The new passwords do not match.";
  if (next === current) return "The new password must be different from the current one.";
  return null;
}

async function submit(view, close, onChanged) {
  if (view.submitButton.disabled) return; // a request is already on the way
  const problem = passwordFormProblem(view.current.value, view.next.value, view.confirm.value);
  if (problem) return showError(view, problem);
  setBusy(view, true);
  try {
    await changePassword(view.current.value, view.next.value);
    close();
    onChanged();
  } catch (error) {
    view.current.value = "";
    showError(view, changeErrorText(error));
    view.current.focus();
  } finally {
    setBusy(view, false);
  }
}

/** 400 wrong current password, 422 rule broken, 429 too many tries: the server's own words. */
function changeErrorText(error) {
  if (error?.status === 401) return "Your session has ended. Log in again to change your password.";
  return authErrorText(error);
}

function setBusy(view, busy) {
  setButtonBusy(view.submitButton, busy);
  view.cancel.disabled = busy;
  view.submitButton.textContent = busy ? BUSY_TEXT : SUBMIT_TEXT;
}

function showError(view, text) {
  view.message.replaceChildren(el("p", { className: "banner banner-error", role: "alert", text }));
}

function handleKey(event, box, close) {
  if (event.key === "Escape") {
    event.preventDefault();
    close();
  } else if (event.key === "Tab") {
    keepFocusInside(event, box);
  }
}
