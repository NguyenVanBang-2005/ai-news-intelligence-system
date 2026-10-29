// The Sources page: admin token, rescan with its numbers, add form, source list,
// and the latest classified articles.

import { el } from "../dom.js";
import { adminAccessPanel } from "./admin-access.js";
import { classifiedSection } from "./classified-list.js";
import { createRescan } from "./rescan.js";
import { addSourceForm } from "./source-form.js";
import { sourceListPanel } from "./source-list.js";

export function renderSourcesPage(root) {
  const list = sourceListPanel();
  const rescan = createRescan({ onFinished: list.reload });
  const form = addSourceForm({ onAdded: list.reload });
  root.append(
    adminAccessPanel(),
    hero(rescan),
    el("div", { className: "container container-wide sources-page" }, [
      rescan.cards,
      rescan.report,
      el("div", { className: "sources-grid" }, [form, list.node]),
      classifiedSection(),
    ]),
  );
}

function hero(rescan) {
  return el("section", { className: "hero hero-sources" }, [
    el("div", { className: "hero-sources-inner" }, [
      el("div", { className: "hero-sources-text" }, [
        el("p", { className: "hero-eyebrow", text: "Source management" }),
        el("h1", { className: "hero-title", text: "Source & Classification Management" }),
        el("p", { className: "hero-subtitle", text: "Watch collection quality, fix failing sources and review the latest classified articles." }),
      ]),
      el("div", { className: "hero-actions" }, [rescan.button, rescan.note]),
    ]),
  ]);
}
