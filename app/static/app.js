// Entry point of the AINIS web UI: wires the pages to the hash router.

import { comingSoon } from "./js/components.js";
import { closeDrawer } from "./js/drawer.js";
import { renderSearchPage } from "./js/pages/search.js";
import { startRouter } from "./js/router.js";

const routes = {
  search: { title: "Search", render: renderSearchPage },
  topics: { title: "Topics", render: (root) => root.append(comingSoon("Topics")) },
  sources: { title: "Sources", render: (root) => root.append(comingSoon("Sources")) },
};

// A drawer belongs to the page it was opened on.
window.addEventListener("hashchange", closeDrawer);
startRouter({ root: document.getElementById("app"), routes, defaultRoute: "search" });
