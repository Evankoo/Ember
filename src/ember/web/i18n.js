// Interface text of an English workspace. The shared templates and scripts are written in
// Chinese; the server puts the English catalog in window.EMBER_TEXT, and this script replaces
// every text node or label whose whole text is a catalog entry, now and whenever the page changes.
// Chinese workspaces get no catalog, and the script does nothing.
(function () {
  "use strict";
  const data = window.EMBER_TEXT;
  if (!data) return;
  const exact = data.exact;
  const patterns = data.patterns.map(([source, target]) => [new RegExp(`^${source}$`, "s"), target]);
  const han = /[一-鿿]/;
  const ATTRIBUTES = ["placeholder", "title", "aria-label", "alt", "data-empty", "data-execution-label"];

  function translate(text) {
    const core = String(text).trim();
    if (!core || !han.test(core)) return text;
    let result = Object.prototype.hasOwnProperty.call(exact, core) ? exact[core] : undefined;
    if (result === undefined) {
      for (const [pattern, target] of patterns) {
        const match = core.match(pattern);
        if (match) {
          result = target.replace(/\{(\w+)\}/g, (whole, key) => (match.groups && key in match.groups ? translate(match.groups[key]) : whole));
          break;
        }
      }
    }
    return result === undefined ? text : String(text).replace(core, result);
  }

  function visit(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const value = translate(node.nodeValue);
      if (value !== node.nodeValue) node.nodeValue = value;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE || node.tagName === "SCRIPT" || node.tagName === "STYLE" || node.isContentEditable) return;
    for (const name of ATTRIBUTES) {
      const value = node.getAttribute(name);
      if (value && han.test(value)) {
        const next = translate(value);
        if (next !== value) node.setAttribute(name, next);
      }
    }
    if (node.tagName === "INPUT" && (node.type === "button" || node.type === "submit") && han.test(node.value)) node.value = translate(node.value);
    for (const child of node.childNodes) visit(child);
  }

  window.emberText = translate;
  visit(document.documentElement);
  new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === "characterData") visit(record.target);
      else if (record.type === "attributes") visit(record.target);
      else record.addedNodes.forEach(visit);
    }
  }).observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRIBUTES });
})();
