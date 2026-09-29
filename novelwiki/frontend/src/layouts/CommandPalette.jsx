/* ============================================================
   Command palette (⌘K / Ctrl+K) — find a story in your library, the shared
   library, or (inside a book) a Codex entry within your chapter boundary.
   Results are tied to query + novel + ceiling; stale ones never show.
   ============================================================ */
import React, { useEffect, useId, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { codexApi } from "../modules/codex/api.js";
import { experienceApi } from "../modules/experience/api.js";
import { useNovelsQuery } from "../modules/catalog/queries.js";
import { Icon } from "../components/Icon.jsx";
import { Cover } from "../components/ui.jsx";
import { TYPE_ICON } from "../lib/constants.js";
import { useDebounce, useFocusTrap } from "../lib/hooks.js";

function ResultIcon({ item }) {
  if (item.group === "Codex") {
    return <span className={`pi-orb t-${item.type || "concept"}`} aria-hidden="true"><Icon name={TYPE_ICON[item.type] || "spark"} size={15} /></span>;
  }
  return <span className="pi-cover" aria-hidden="true"><Cover src={item.cover} title={item.label} /></span>;
}

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
      ...library.map(n => ({ key: `library-${n.id}`, group: "Your library", label: n.title, meta: n.author, path: `/n/${n.id}`, cover: n.cover_url })),
      ...(current?.entities || []).map(e => ({ key: `entity-${e.id}`, group: "Codex", label: e.canonical_name || e.name, meta: e.type, type: e.type, path: `/n/${novelId}/codex/e/${e.id}` })),
      ...(current?.remote || []).filter(n => !ids.has(n.id)).map(n => ({ key: `shared-${n.id}`, group: "Shared library", label: n.title, meta: n.author, path: `/n/${n.id}`, cover: n.cover_url })),
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
      <div className="palette-input">
        <Icon name="search" size={20} />
        <input role="combobox" aria-expanded="true" aria-autocomplete="list" aria-controls={listId} aria-activedescendant={items.length ? `${listId}-${activeIndex}` : undefined} aria-label="Find a story or Codex entry" value={q} onChange={e => setQ(e.target.value)} placeholder={novelId != null ? "Find a story or Codex entry…" : "Find a story…"} />
        <kbd className="palette-esc" aria-hidden="true">esc</kbd>
        <button className="icon-btn plain" aria-label="Close search" onClick={onClose}><Icon name="x" size={17} /></button>
      </div>
      <div className="palette-list" id={listId} role="listbox" aria-label="Search results">
        {items.map((item, index) => <React.Fragment key={item.key}>
          {items[index - 1]?.group !== item.group && <div className="palette-group" role="presentation">{item.group}</div>}
          <button role="option" id={`${listId}-${index}`} aria-selected={index === activeIndex}
                  className={`palette-item${index === activeIndex ? " focused" : ""}`} data-result-index={index}
                  style={{ "--i": index }}
                  onFocus={() => setFocus(index)} onMouseMove={() => { if (index !== activeIndex) setFocus(index); }} onClick={() => select(item)}>
            <ResultIcon item={item} />
            <span className="pi-text"><span className="truncate pi-label">{item.label}</span>{item.meta && <span className="pi-meta">{item.meta}</span>}</span>
            <Icon name="arrowRight" size={15} className="pi-go" />
          </button>
        </React.Fragment>)}
      </div>
      <div className="palette-status" role="status">{q.trim() && !current ? "Searching…" : current?.failed ? "Some results couldn't load. Your library is still available." : !items.length ? "No matches. Try a title or author." : <><span className="palette-keys"><span><kbd>↑</kbd> <kbd>↓</kbd> to browse</span><span><kbd>↵</kbd> to open</span><span><kbd>esc</kbd> to close</span></span><span className="palette-touch">Tap a result to open it.</span></>}</div>
    </div>
  </div>;
}
