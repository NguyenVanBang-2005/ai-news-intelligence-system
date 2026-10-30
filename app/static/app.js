// Entry point of the AINIS web UI: wires the pages to the hash router.

import { closeDrawer } from "./js/drawer.js";
import { renderSearchPage } from "./js/pages/search.js";
import { renderSourcesPage } from "./js/pages/sources.js";
import { renderTopicsPage } from "./js/pages/topics.js";
import { startRouter } from "./js/router.js";

const routes = {
  search: { title: "Search", render: renderSearchPage },
  topics: { title: "Topics", render: renderTopicsPage },
  sources: { title: "Sources", render: renderSourcesPage },
};

// A drawer belongs to the page it was opened on.
window.addEventListener("hashchange", closeDrawer);
startRouter({ root: document.getElementById("app"), routes, defaultRoute: "search" });
