// "Add an RSS/Atom source" form: POST /api/v1/sources with type "rss".

import { adminRequest, hasToken, NEEDS_TOKEN_MESSAGE, tokenErrorMessage } from "../admin-token.js";
import { errorMessage } from "../components.js";
import { el } from "../dom.js";
import { watchToken } from "./admin-access.js";
import { LANGUAGES } from "./source-status.js";

const NAME_MIN = 2;
const NAME_MAX = 120;
const URL_MAX = 2000;

const MESSAGES = {
  name: `Enter a name of ${NAME_MIN} to ${NAME_MAX} characters.`,
  url: "Enter a feed URL that starts with http:// or https://.",
  conflict: "A source with this name or feed URL already exists.",
  rejected: "The server rejected these values. Check the name and URL.",
};

/** The form card; `onAdded(source)` runs after a 201. */
export function addSourceForm({ onAdded }) {
  const view = buildForm();
  view.onAdded = onAdded;
  view.form.addEventListener("submit", (event) => { event.preventDefault(); submit(view); });
  watchToken(view.form, () => updateControls(view));
  return el("section", { className: "card source-form-card", "aria-labelledby": "add-source-title" }, [
    el("div", { className: "panel-head" }, [
      el("span", { className: "panel-icon", "aria-hidden": "true", text: "RSS" }),
      el("div", {}, [
        el("h2", { className: "panel-title", id: "add-source-title", text: "Add an RSS/Atom source" }),
        el("p", { className: "panel-subtitle", text: "The feed is checked the next time sources are rescanned." }),
      ]),
    ]),
    view.form,
  ]);
}

function buildForm() {
  const name = el("input", { id: "source-name", name: "name", type: "text", autocomplete: "off",
    maxlength: NAME_MAX, placeholder: "Example: OpenAI News", className: "field-input" });
  const url = el("input", { id: "source-url", name: "feed_url", type: "text", inputmode: "url",
    autocomplete: "off", maxlength: URL_MAX, placeholder: "https://example.com/feed.xml", className: "field-input" });
  const language = el("select", { id: "source-language", name: "language", className: "field-input" },
    LANGUAGES.map((item) => el("option", { value: item.code, text: item.name })));
  const button = el("button", { className: "btn btn-primary btn-block", type: "submit", text: "+ Add source" });
  const note = el("p", { className: "form-note" });
  const message = el("div", { className: "form-message", "aria-live": "polite" });
  const form = el("form", { className: "source-form", novalidate: true }, [
    field("Name", name), field("Feed URL", url), field("Language", language), button, note, message,
  ]);
  return { form, name, url, language, button, note, message, busy: false };
}

function field(label, input) {
  return el("div", { className: "field" }, [
    el("label", { className: "field-label", for: input.id, text: label }), input,
  ]);
}

function updateControls(view) {
  const locked = !hasToken();
  for (const control of [view.name, view.url, view.language]) control.disabled = locked;
  view.button.disabled = locked || view.busy;
  view.note.textContent = locked ? NEEDS_TOKEN_MESSAGE : "";
}

/** The values to send, or { problem } when they fail the checks done before calling the API. */
export function checkSourceInput(nameText, urlText) {
  const name = String(nameText ?? "").trim();
  const feedUrl = String(urlText ?? "").trim();
  if (name.length < NAME_MIN || name.length > NAME_MAX) return { problem: MESSAGES.name };
  if (!/^https?:\/\/[^\s/]+/i.test(feedUrl) || !isValidUrl(feedUrl)) return { problem: MESSAGES.url };
  return { name, feedUrl };
}

function isValidUrl(text) {
  try {
    return Boolean(new URL(text).hostname);
  } catch {
    return false;
  }
}

async function submit(view) {
  if (view.busy || !hasToken()) return; // one request at a time; never without a token
  const checked = checkSourceInput(view.name.value, view.url.value);
  if (checked.problem) return showMessage(view, checked.problem, "error");
  setBusy(view, true);
  try {
    const source = await adminRequest("/api/v1/sources", {
      method: "POST",
      body: { name: checked.name, type: "rss", feed_url: checked.feedUrl, language: view.language.value },
    });
    view.name.value = "";
    view.url.value = "";
    showMessage(view, `Source added: ${source.name}`, "info");
    view.onAdded(source);
  } catch (error) {
    showMessage(view, failureText(error), "error");
  } finally {
    setBusy(view, false);
  }
}

function failureText(error) {
  if (error?.status === 409) return MESSAGES.conflict;
  if (error?.status === 422) return MESSAGES.rejected;
  if (!error?.kind) console.error(error); // a bug, not an API answer
  return tokenErrorMessage(error) ?? errorMessage(error);
}

function setBusy(view, busy) {
  view.busy = busy;
  view.button.textContent = busy ? "Adding…" : "+ Add source";
  updateControls(view);
}

function showMessage(view, text, tone) {
  const role = tone === "error" ? "alert" : "status";
  view.message.replaceChildren(el("p", { className: `banner banner-${tone}`, role, text }));
}
