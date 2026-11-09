// The "Log in" / "Register" modal (role="dialog"), built like confirm-dialog.js:
// focus stays inside, Esc or a backdrop click closes it, focus returns to the opener.

import { authErrorText, logIn, register } from "./auth.js";
import { el } from "./dom.js";
import { keepFocusInside } from "./focus-trap.js";

const BODY_LOCK_CLASS = "dialog-open";
const TITLE_ID = "auth-dialog-title";

const MODES = {
  login: {
    title: "Log in", submit: "Log in", busy: "Logging in…", autocomplete: "current-password",
    switchText: "No account yet? Register", other: "register",
  },
  register: {
    title: "Create an account", submit: "Register", busy: "Creating…", autocomplete: "new-password",
    switchText: "Already have an account? Log in", other: "login",
    hint: "Username: 3-32 characters (a-z, 0-9, _ . -). Password: 10-128 characters, not the username.",
  },
};

/**
 * Opens the dialog in `mode` ("login" or "register"). `onSignedIn(user)` runs after a
 * successful login. `notice` and `username` prefill the dialog (used after registering).
 */
export function openAuthDialog({ mode, opener, onSignedIn, notice = "", username = "" }) {
  const view = buildView(MODES[mode], username, notice);
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
  view.switchButton.addEventListener("click", () => {
    close();
    openAuthDialog({ mode: MODES[mode].other, opener, onSignedIn, username: view.username.value });
  });
  view.form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit({ mode, view, close, opener, onSignedIn });
  });
  document.body.append(view.backdrop, view.box);
  document.body.classList.add(BODY_LOCK_CLASS);
  document.addEventListener("keydown", view.onKey);
  (view.username.value ? view.password : view.username).focus();
}

function buildView(config, username, notice) {
  const usernameField = textInput("auth-username", "username", "Username", { autocomplete: "username", maxlength: 64 });
  const passwordField = textInput("auth-password", "password", "Password", {
    type: "password", autocomplete: config.autocomplete, maxlength: 128,
  });
  const view = {
    config,
    username: usernameField.input,
    password: passwordField.input,
    submitButton: el("button", { className: "btn btn-primary", type: "submit", text: config.submit }),
    cancel: el("button", { className: "btn btn-secondary", type: "button", text: "Cancel" }),
    switchButton: el("button", { className: "btn-link", type: "button", text: config.switchText }),
    message: el("div", { className: "form-message", "aria-live": "polite" }),
    backdrop: el("div", { className: "dialog-backdrop" }),
  };
  view.username.value = username;
  if (notice) showMessage(view, notice, "info");
  view.form = buildForm(view, [usernameField.field, passwordField.field]);
  view.box = el("div", { className: "dialog auth-dialog", role: "dialog", "aria-modal": "true", "aria-labelledby": TITLE_ID }, [
    el("h2", { className: "dialog-title", id: TITLE_ID, text: config.title }), view.form,
  ]);
  return view;
}

function buildForm(view, fields) {
  return el("form", { className: "auth-form", novalidate: true }, [
    ...fields,
    view.config.hint ? el("p", { className: "form-note", text: view.config.hint }) : null,
    view.message,
    el("div", { className: "dialog-actions" }, [view.cancel, view.submitButton]),
    el("p", { className: "auth-switch" }, view.switchButton),
  ]);
}

function textInput(id, name, label, props) {
  const input = el("input", { id, name, type: "text", className: "field-input", spellcheck: "false", ...props });
  const field = el("div", { className: "field" }, [el("label", { className: "field-label", for: id, text: label }), input]);
  return { input, field };
}

async function submit({ mode, view, close, opener, onSignedIn }) {
  if (view.submitButton.disabled) return; // a request is already on the way
  const username = view.username.value.trim();
  const password = view.password.value;
  if (!username || !password) return showMessage(view, "Enter a username and a password.", "error");
  setBusy(view, true);
  try {
    if (mode === "login") {
      const user = await logIn(username, password);
      close();
      onSignedIn(user);
    } else {
      const user = await register(username, password);
      close();
      openAuthDialog({
        mode: "login", opener, onSignedIn, username: user.username,
        notice: `Account "${user.username}" created. You can log in now.`,
      });
    }
  } catch (error) {
    view.password.value = "";
    showMessage(view, authErrorText(error), "error");
  } finally {
    setBusy(view, false);
  }
}

function setBusy(view, busy) {
  view.submitButton.disabled = busy;
  view.submitButton.textContent = busy ? view.config.busy : view.config.submit;
}

function showMessage(view, text, tone) {
  const role = tone === "error" ? "alert" : "status";
  view.message.replaceChildren(el("p", { className: `banner banner-${tone}`, role, text }));
}

function handleKey(event, box, close) {
  if (event.key === "Escape") {
    event.preventDefault();
    close();
  } else if (event.key === "Tab") {
    keepFocusInside(event, box);
  }
}
