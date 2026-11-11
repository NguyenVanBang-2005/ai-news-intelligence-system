// "Add an RSS/Atom source": POST /api/v1/sources with type "rss".

import { el, setButtonBusy } from "../js/dom.js";
import { showToast } from "../js/toast.js";
import { LANGUAGES } from "../js/pages/source-status.js";
import { adminErrorText, adminRequest, messageBanner } from "./admin-api.js";

const NAME_MAX = 120;
const URL_MAX = 1000;

/** The form card; `onAdded(source)` runs after the server created the source. */
export function sourceAddForm({ onAdded }) {
  const view = buildForm();
  view.form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit(view, onAdded);
  });
  return el("section", { className: "card source-form-card", "aria-labelledby": "add-source-title" }, [
    el("div", { className: "panel-head" }, [
      el("span", { className: "panel-icon", "aria-hidden": "true", text: "RSS" }),
      el("div", {}, [
        el("h2", { className: "panel-title", id: "add-source-title", text: "Add an RSS/Atom source" }),
        el("p", { className: "panel-subtitle", text: "The feed is read the next time ingestion runs." }),
      ]),
    ]),
    view.form,
  ]);
}

function buildForm() {
  const name = el("input", { id: "source-name", name: "name", type: "text", autocomplete: "off",
    maxlength: NAME_MAX, placeholder: "Example: OpenAI News", className: "field-input" });
  const url = el("input", { id: "source-url", name: "feed_url", type: "url", inputmode: "url",
    autocomplete: "off", maxlength: URL_MAX, placeholder: "https://example.com/feed.xml", className: "field-input" });
  const language = el("select", { id: "source-language", name: "language", className: "field-input" },
    LANGUAGES.map((item) => el("option", { value: item.code, text: item.name })));
  const button = el("button", { className: "btn btn-primary btn-block", type: "submit", text: "+ Add source" });
  const message = el("div", { className: "form-message", "aria-live": "polite" });
  const form = el("form", { className: "source-form", novalidate: true }, [
    field("Name", name), field("Feed URL", url), field("Language", language), button, message,
  ]);
  return { form, name, url, language, button, message };
}

function field(label, input) {
  return el("div", { className: "field" }, [
    el("label", { className: "field-label", for: input.id, text: label }), input,
  ]);
}

// The server checks the values; its `detail` is shown word for word on 409/422.
async function submit(view, onAdded) {
  if (view.button.disabled) return; // one request at a time
  setButtonBusy(view.button, true);
  try {
    const source = await adminRequest("/api/v1/sources", {
      method: "POST",
      body: { name: view.name.value.trim(), type: "rss", feed_url: view.url.value.trim(), language: view.language.value },
    });
    view.name.value = "";
    view.url.value = "";
    view.message.replaceChildren();
    showToast(`Source added: ${source.name}`, "success");
    onAdded(source);
  } catch (error) {
    view.message.replaceChildren(messageBanner(`The source was not added. ${adminErrorText(error)}`, "error"));
  } finally {
    setButtonBusy(view.button, false);
  }
}
