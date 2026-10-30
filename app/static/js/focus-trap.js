// Keeps keyboard focus inside a modal element (drawer, dialog) while it is open.

const FOCUSABLE = 'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** On Tab: from the last element go to the first one, Shift+Tab from the first to the last. */
export function keepFocusInside(event, container) {
  const items = [...container.querySelectorAll(FOCUSABLE)].filter((node) => node.offsetParent !== null);
  if (items.length === 0) return;
  const first = items[0];
  const last = items[items.length - 1];
  const inside = container.contains(document.activeElement);
  if (event.shiftKey && (document.activeElement === first || !inside)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (document.activeElement === last || !inside)) {
    event.preventDefault();
    first.focus();
  }
}
