import React, { useEffect, useId, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { codexApi } from "../modules/codex/api.js";
import { experienceApi } from "../modules/experience/api.js";
import { useNovelsQuery } from "../modules/catalog/queries.js";
import { Icon } from "../components/Icon.jsx";
import { useDebounce, useFocusTrap } from "../lib/hooks.js";

export function CommandPalette({ onClose, novelId, ceiling }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [focus, setFocus] = useState(0);
  const debQ = useDebounce(q.trim(), 200);
  const { data: novels } = useNovelsQuery();
  const [result, setResult] = useState(null);
  const dialogRef = useFocusTrap(true);
  const listId = useId();
  const key = JSON.stringify([q.trim(), novelId, ceiling]);
  const current = result?.key === key ? result : null;

  useEffect(() => {
    if (!debQ) { setResult(null); return; }
    let canceled = false;
    const requestKey = JSON.stringify([debQ, novelId, ceiling]);
    const entitySearch = novelId != null && ceiling != null
      ? codexApi.listEntities(novelId, ceiling, { q: debQ }) : Promise.resolve([]);
    Promise.allSettled([experienceApi.discover({ q: debQ, limit: 6 }), entitySearch]).then(([shared, codex]) => {
      if (canceled) return;
      const remote = shared.status === "fulfilled" ? shared.value : [];
      setResult({ key: requestKey, remote: Array.isArray(remote) ? remote : remote.items || [], entities: codex.status === "fulfilled" ? codex.value.slice(0, 6) : [], failed: shared.status === "rejected" || codex.status === "rejected" });
    });
    return () => { canceled = true; };
  }, [debQ, novelId, ceiling]);

  const items = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const library = (novels || []).filter(n => !needle || n.title.toLowerCase().includes(needle) || (n.author || "").toLowerCase().includes(needle)).slice(0, 6);
    const ids = new Set(library.map(n => n.id));
    return [
      ...library.map(n => ({ key: `library-${n.id}`, group: "Your library", label: n.title, meta: n.author, path: `/n/${n.id}` })),
      ...(current?.entities || []).map(e => ({ key: `entity-${e.id}`, group: "Codex", label: e.canonical_name || e.name, meta: e.type, path: `/n/${novelId}/codex/e/${e.id}` })),
      ...(current?.remote || []).filter(n => !ids.has(n.id)).map(n => ({ key: `shared-${n.id}`, group: "Shared library", label: n.title, meta: n.author, path: `/n/${n.id}` })),
    ];
  }, [novels, q, current, novelId]);
  useEffect(() => { setFocus(0); }, [q, novelId, ceiling]);
  const select = item => { navigate(item.path); onClose(); };
  const activeIndex = Math.max(0, Math.min(focus, items.length - 1));
  const onKey = e => {
    if (e.key === "Escape") { e.stopPropagation(); onClose(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = Math.max(0, Math.min(items.length - 1, activeIndex + (e.key === "ArrowDown" ? 1 : -1)));
      setFocus(next);
      const option = dialogRef.current?.querySelector(`[data-result-index="${next}"]`);
      option?.scrollIntoView({ block: "nearest" });
      if (e.target.closest('[role="option"]')) option?.focus({ preventScroll: true });
    } else if (e.key === "Enter" && e.target.tagName === "INPUT" && items[activeIndex]) { e.preventDefault(); select(items[activeIndex]); }
  };
  return <div className="palette-scrim" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="palette" ref={dialogRef} role="dialog" aria-modal="true" aria-label="Search" tabIndex={-1} onKeyDown={onKey}>
      <div className="palette-input"><Icon name="search" size={19} /><input role="combobox" aria-expanded="true" aria-autocomplete="list" aria-controls={listId} aria-activedescendant={items.length ? `${listId}-${activeIndex}` : undefined} aria-label="Find a story or Codex entry" value={q} onChange={e => setQ(e.target.value)} placeholder="Find a story or Codex entry…" /><button className="icon-btn plain" aria-label="Close search" onClick={onClose}><Icon name="x" size={17} /></button></div>
      <div className="palette-list" id={listId} role="listbox" aria-label="Search results">
        {items.map((item, index) => <React.Fragment key={item.key}>{items[index - 1]?.group !== item.group && <div className="palette-group" role="presentation">{item.group}</div>}<button role="option" id={`${listId}-${index}`} aria-selected={index === activeIndex} className={`palette-item${index === activeIndex ? " focused" : ""}`} data-result-index={index} onFocus={() => setFocus(index)} onClick={() => select(item)}><Icon name={item.group === "Codex" ? "compass" : "book"} size={17} /><span className="truncate">{item.label}</span>{item.meta && <span className="pi-meta">{item.meta}</span>}</button></React.Fragment>)}
      </div>
      <div className="palette-status" role="status">{q.trim() && !current ? "Searching…" : current?.failed ? "Some results couldn't load. Your library is still available." : !items.length ? "No matches. Try a title or author." : "Use ↑ ↓ to browse, Enter to open, and Esc to close."}</div>
    </div>
  </div>;
}
