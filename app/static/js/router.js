// Hash router: "#/search", "#/topics", "#/sources". Pages live in the URL hash, not on the server.

const SITE_NAME = "AINIS";

/**
 * Shows the page of the current hash in `root` and follows hash changes.
 * `routes`: { name: { title, render(root) } }. Unknown hashes show `defaultRoute`.
 */
export function startRouter({ root, routes, defaultRoute }) {
  const show = () => showRoute({ root, routes, defaultRoute });
  window.addEventListener("hashchange", show);
  show();
}

function showRoute({ root, routes, defaultRoute }) {
  const name = routeName(window.location.hash, routes, defaultRoute);
  const route = routes[name];
  document.title = `${route.title} · ${SITE_NAME}`;
  markActiveNav(name);
  root.replaceChildren();
  route.render(root);
}

/** The route named by a hash like "#/topics", or the default one. */
export function routeName(hash, routes, defaultRoute) {
  const match = /^#\/([a-z-]+)\/?$/.exec(hash);
  const name = match ? match[1] : defaultRoute;
  return Object.hasOwn(routes, name) ? name : defaultRoute;
}

function markActiveNav(name) {
  for (const link of document.querySelectorAll("[data-route]")) {
    const active = link.dataset.route === name;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}
