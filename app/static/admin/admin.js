// Entry point of the admin page (/admin/). It asks GET /api/v1/auth/me who is signed in:
// nobody -> "Log in as an administrator"; role "user" -> "Administrator role required";
// role "admin" -> the dashboard. A 401/403 later on brings back the log-in screen.

import { authErrorText, fetchCurrentUser, logOut } from "../js/auth.js";
import { badge, errorBanner, loading } from "../js/components.js";
import { el, setButtonBusy } from "../js/dom.js";
import { changePasswordControls } from "../js/password-dialog.js";
import { aiProcessPanel } from "./ai-process-admin.js";
import { onSessionLost } from "./admin-api.js";
import { ingestionPanel } from "./ingestion-admin.js";
import { sourceAddForm } from "./source-add-form.js";
import { sourcesAdminPanel } from "./sources-admin.js";

const LOGIN_NEEDED = "Log in as an administrator";
const ROLE_NEEDED = "Administrator role required";

const main = document.getElementById("admin");
const account = document.getElementById("account");

onSessionLost(() => showGate(LOGIN_NEEDED, "Your session has ended or no longer has the admin role."));
start();

async function start() {
  main.replaceChildren(loading("Checking your session…"));
  let user;
  try {
    user = await fetchCurrentUser();
  } catch (error) {
    main.replaceChildren(el("div", { className: "container" }, [
      errorBanner(error),
      el("button", { className: "btn btn-secondary", type: "button", text: "Retry", onclick: start }),
    ]));
    return;
  }
  if (!user) return showGate(LOGIN_NEEDED, "Log in on the main site with an admin account, then come back here.");
  if (user.role !== "admin") return showGate(ROLE_NEEDED, `You are signed in as "${user.username}", which is not an admin account.`);
  showDashboard(user);
}

function showGate(title, text) {
  account.replaceChildren();
  main.replaceChildren(el("div", { className: "container" }, [
    el("section", { className: "card admin-gate" }, [
      el("h1", { className: "admin-gate-title", text: title }),
      el("p", { text }),
      el("a", { className: "btn btn-primary", href: "/", text: "Go to the main site" }),
    ]),
  ]));
}

function showDashboard(user) {
  showAccount(user);
  const list = sourcesAdminPanel({ onIngest: (source) => ingestion.run(source) });
  const ingestion = ingestionPanel({ onFinished: list.reload });
  const form = sourceAddForm({ onAdded: list.reload });
  main.replaceChildren(el("div", { className: "container container-wide admin-page" }, [
    el("h1", { className: "admin-page-title", text: "Administration" }),
    el("div", { className: "sources-grid" }, [form, list.node]),
    el("div", { className: "admin-grid" }, [ingestion.node, aiProcessPanel()]),
  ]));
}

function showAccount(user) {
  const logOutButton = el("button", { className: "btn btn-secondary btn-small", type: "button", text: "Log out" });
  const message = el("span", { className: "account-error", role: "alert" });
  logOutButton.addEventListener("click", async () => {
    setButtonBusy(logOutButton, true);
    try {
      await logOut();
      showGate(LOGIN_NEEDED, "You have logged out.");
    } catch (error) {
      message.textContent = authErrorText(error);
      setButtonBusy(logOutButton, false);
    }
  });
  account.replaceChildren(
    el("span", { className: "account-name", text: user.username }),
    badge(user.role, "primary"),
    ...changePasswordControls(),
    logOutButton,
    message,
  );
}
