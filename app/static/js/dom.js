// Safe DOM building: text only goes in through textContent / text nodes, never as HTML.

// Attributes that could run code or load styles; they are refused by el().
const FORBIDDEN_ATTRIBUTES = new Set(["style", "srcdoc", "formaction"]);

/**
 * Creates an element. `props`: text, className, dataset, on<Event> (functions only),
 * href (internal links only: "#..." or "/..."), and any other plain attribute.
 */
export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) setProp(node, key, value);
  appendChildren(node, children);
  return node;
}

function setProp(node, key, value) {
  if (value === null || value === undefined || value === false) return;
  if (key === "text") {
    node.textContent = String(value);
  } else if (key === "className") {
    node.className = value;
  } else if (key === "dataset") {
    Object.assign(node.dataset, value);
  } else if (key.startsWith("on")) {
    if (typeof value !== "function") throw new TypeError(`${key} must be a function`);
    node.addEventListener(key.slice(2).toLowerCase(), value);
  } else if (key === "href") {
    node.setAttribute("href", internalHref(value));
  } else if (FORBIDDEN_ATTRIBUTES.has(key.toLowerCase())) {
    throw new TypeError(`el() does not set the "${key}" attribute`);
  } else {
    node.setAttribute(key, value === true ? "" : String(value));
  }
}

function internalHref(value) {
  const href = String(value);
  if (href.startsWith("#") || (href.startsWith("/") && !href.startsWith("//"))) return href;
  throw new TypeError(`el() only takes internal links; use externalLink() for ${href}`);
}

/** Appends strings (as text nodes), nodes and nested arrays; null/undefined/false are skipped. */
export function appendChildren(node, children) {
  for (const child of [children].flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

/** The URL if it is an absolute http:// or https:// URL, otherwise null. */
export function safeHref(url) {
  if (typeof url !== "string") return null;
  try {
    const parsed = new URL(url.trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null; // not an absolute URL
  }
}

/** A link opened in a new tab without access to this page; plain text if the URL is unsafe. */
export function externalLink(url, children, props = {}) {
  const href = safeHref(url);
  if (href === null) return el("span", props, children);
  const link = el("a", { ...props, target: "_blank", rel: "noopener noreferrer" }, children);
  link.setAttribute("href", href);
  return link;
}

const SVG_NS = "http://www.w3.org/2000/svg"; // XML namespace name, not a download

/**
 * A decorative icon that points at a <symbol id="icon-..."> written in the page's HTML
 * (see the hidden sprite in index.html and admin/index.html). Hidden from screen readers.
 */
export function svgIcon(symbolId, className = "icon") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#${symbolId}`);
  svg.append(use);
  return svg;
}

/** Disables a button while a request runs; aria-busy shows the CSS spinner. */
export function setButtonBusy(button, busy) {
  button.disabled = busy;
  if (busy) button.setAttribute("aria-busy", "true");
  else button.removeAttribute("aria-busy");
}
