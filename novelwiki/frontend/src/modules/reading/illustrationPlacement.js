// Keep prose and narration indices intact: illustrations occupy gaps between blocks.
export function paragraphIllustrations(paragraphs, scenes) {
  const slots = new Map();
  const texts = paragraphs.map(paragraph => paragraph.text.replace(/\s+/g, " ").trim());
  const content = texts.join(" ");
  const add = (slot, scene) => slots.set(slot, [...(slots.get(slot) || []), scene]);
  for (const scene of scenes) {
    const placement = scene.placement || { position: "end" };
    if (placement.position === "start") { add(0, scene); continue; }
    if (placement.position === "end") { add(texts.length, scene); continue; }
    const anchor = (placement.anchor || "").replace(/\s+/g, " ").trim();
    const offset = anchor ? content.indexOf(anchor) : -1;
    // A changed or ambiguous anchor must never move art to the wrong scene.
    if (offset < 0 || content.indexOf(anchor, offset + 1) >= 0) continue;
    const end = offset + anchor.length;
    let cursor = 0;
    const index = texts.findIndex(text => {
      cursor += text.length;
      if (cursor >= end) return true;
      cursor += 1;
      return false;
    });
    if (index >= 0) add(index + 1, scene);
  }
  return slots;
}

export function prepareIllustratedHtml(html, scenes) {
  const template = document.createElement("template");
  template.innerHTML = html;
  const root = template.content;
  const targets = [];
  let startTail = null;
  for (const [index, scene] of scenes.entries()) {
    const placement = scene.placement || { position: "end" };
    let target = null;
    if (placement.position === "after") {
      const anchor = (placement.anchor || "").replace(/\s+/g, " ").trim();
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const owners = [];
      let content = "", node, previousBlock = null;
      const append = (char, owner) => {
        const normalized = /\s/.test(char) ? " " : char;
        if (normalized === " " && content.endsWith(" ")) return;
        content += normalized; owners.push(owner);
      };
      while ((node = walker.nextNode())) {
        const block = node.parentElement?.closest("p, h1, h2, h3, h4, h5, h6, blockquote, li, pre, div");
        if (previousBlock && block !== previousBlock) append(" ", node);
        for (let char = 0; char < node.textContent.length; char += 1) append(node.textContent[char], node);
        previousBlock = block;
      }
      const start = anchor ? content.indexOf(anchor) : -1;
      if (start < 0 || content.indexOf(anchor, start + 1) >= 0) continue;
      const last = { node: owners[start + anchor.length - 1] };
      target = last?.node.parentElement?.closest("p, h1, h2, h3, h4, h5, h6, blockquote, li, pre, div");
      if (!target || !root.contains(target)) continue;
      // Keep generated figures outside list/table structures and narration spans.
      target = target.closest("table, ul, ol") || target;
    }
    const marker = document.createElement("div");
    marker.setAttribute("data-illustration-slot", String(index));
    targets.push({ index, scene });
    if (placement.position === "start") {
      if (startTail) startTail.after(marker);
      else root.insertBefore(marker, root.firstChild);
      startTail = marker;
    }
    else if (target) {
      // Preserve planner order when several illustrations follow one block.
      let after = target;
      while (after.nextSibling?.nodeType === 1 && after.nextSibling.hasAttribute("data-illustration-slot")) after = after.nextSibling;
      after.after(marker);
    } else root.append(marker);
  }
  return { html: template.innerHTML, targets };
}
