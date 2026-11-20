// Install once per document. Keep snapshots even when React removes a post.
const selector = arguments[0];
if (window.__vkCollector) return;
const saved = new Map();
function save(el) {
  if (!el || el.nodeType !== 1) return;
  let nodes = [];
  if (el.matches(selector)) nodes.push(el);
  if (el.closest(selector)) nodes.push(el.closest(selector));
  nodes.push(...el.querySelectorAll(selector));
  for (const node of nodes) {
    if (node.parentElement?.closest(selector)) continue; // Reposts are not neighbours.
    const raw = node.getAttribute('data-post-id') || node.id.replace(/^post/, '');
    if (!/^-?\d+_\d+$/.test(raw)) continue;
    const html = node.outerHTML;
    if (saved.get(raw)?.html !== html) saved.set(raw, {key: raw, html, dirty: true});
  }
}
const observer = new MutationObserver(records => {
  for (const record of records) {
    save(record.target.nodeType === 1 ? record.target : record.target.parentElement);
    for (const node of record.addedNodes) save(node);
    for (const node of record.removedNodes) save(node);
  }
});
observer.observe(document.documentElement, {subtree: true, childList: true,
  attributes: true, characterData: true});
save(document.documentElement);
window.__vkCollector = {
  drain() {
    save(document.documentElement);
    return [...saved.values()].filter(x => x.dirty).map(x => {
      x.dirty = false;
      return {key: x.key, html: x.html};
    });
  }
};
