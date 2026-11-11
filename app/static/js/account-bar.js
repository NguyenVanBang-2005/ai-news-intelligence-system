// The right side of the top bar: "Log in" / "Register" when signed out; the username,
// role, an "Admin" link (admins only), "Change password" and "Log out" when signed in.
// The state comes from GET /api/v1/auth/me when the page loads (401 = signed out).

import { badge } from "./components.js";
import { authErrorText, fetchCurrentUser, logOut } from "./auth.js";
import { openAuthDialog } from "./auth-dialog.js";
import { el, setButtonBusy } from "./dom.js";
import { changePasswordControls } from "./password-dialog.js";

const ADMIN_PATH = "/admin/";

/** Fills `root` with the account controls and keeps them up to date. */
export async function startAccountBar(root) {
  root.replaceChildren(el("span", { className: "account-note", text: "…" }));
  try {
    showUser(root, await fetchCurrentUser());
  } catch {
    showUser(root, null); // the page still works signed out
  }
}

function showUser(root, user) {
  root.replaceChildren(...(user ? signedIn(root, user) : signedOut(root)));
}

function signedOut(root) {
  const onSignedIn = (user) => showUser(root, user);
  const logInButton = el("button", { className: "btn btn-secondary btn-small", type: "button", text: "Log in" });
  const registerButton = el("button", { className: "btn btn-primary btn-small", type: "button", text: "Register" });
  logInButton.addEventListener("click", () => openAuthDialog({ mode: "login", opener: logInButton, onSignedIn }));
  registerButton.addEventListener("click", () => openAuthDialog({ mode: "register", opener: registerButton, onSignedIn }));
  return [logInButton, registerButton];
}

function signedIn(root, user) {
  const logOutButton = el("button", { className: "btn btn-secondary btn-small", type: "button", text: "Log out" });
  const message = el("span", { className: "account-error", role: "alert" });
  logOutButton.addEventListener("click", () => endSession(root, logOutButton, message));
  return [
    el("span", { className: "account-name", text: user.username }),
    badge(user.role, user.role === "admin" ? "primary" : "neutral"),
    user.role === "admin" ? el("a", { className: "nav-link", href: ADMIN_PATH, text: "Admin" }) : null,
    ...changePasswordControls(),
    logOutButton,
    message,
  ].filter(Boolean);
}

async function endSession(root, button, message) {
  setButtonBusy(button, true);
  try {
    await logOut();
    showUser(root, null);
  } catch (error) {
    message.textContent = authErrorText(error);
    setButtonBusy(button, false);
  }
}
