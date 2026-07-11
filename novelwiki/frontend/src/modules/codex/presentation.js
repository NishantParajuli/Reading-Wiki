const TYPE_PORTRAIT = {
  character: "PORTRAIT", location: "PLACE", faction: "EMBLEM",
  item: "OBJECT", concept: "CONCEPT", organization: "EMBLEM",
};

export function portraitLabel(type, name) {
  const portrait = TYPE_PORTRAIT[type] || "ENTRY";
  return name ? `${portrait} — ${name}` : portrait;
}

export function buildCiteMap(citations) {
  const map = {};
  (citations || []).forEach((citation) => {
    const kind = (citation.kind || "").toLowerCase();
    map[`${kind}:${citation.id}`] = {
      ch: citation.chapter,
      quote: citation.snippet || "",
      chunk: `${kind} ${citation.id}`,
      label: `${kind.charAt(0).toUpperCase()}${kind.slice(1)} ${citation.id}`,
      kind,
      id: citation.id,
    };
  });
  return map;
}
