/* Add-novel dialog (form logic preserved from the old AddNovelForm). */
import React, { useEffect, useState } from "react";
import { acquisitionApi } from "../acquisition/api.js";
import { catalogApi } from "./api.js";
import { Dialog } from "../../components/overlay.jsx";
import { Button } from "../../components/ui.jsx";

export function AddNovelDialog({ onCreated, onClose }) {
  const [adapters, setAdapters] = useState([]);
  const [title, setTitle] = useState("");
  const [adapter, setAdapter] = useState("");
  const [startUrl, setStartUrl] = useState("");
  const [language, setLanguage] = useState("en");
  const [isRaw, setIsRaw] = useState(false);
  const [codex, setCodex] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    acquisitionApi.adapters().then(list => {
      setAdapters(list);
      if (list[0]) setAdapter(a => a || list[0].name);
    }).catch(() => setAdapters([]));
  }, []);

  // Default the language to the chosen adapter's default.
  useEffect(() => {
    const a = adapters.find(x => x.name === adapter);
    if (a && a.default_language) setLanguage(a.default_language);
  }, [adapter, adapters]);

  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || !startUrl.trim() || busy) return;
    setBusy(true); setErr(null);
    try {
      const res = await catalogApi.createNovel({
        title: title.trim(),
        codex_enabled: codex,
        original_language: language,
        source: { adapter, start_url: startUrl.trim(), language, is_raw: isRaw },
      });
      onCreated(res.id);
    } catch (e2) {
      setErr(e2.message || "Could not create the novel.");
      setBusy(false);
    }
  }

  return (
    <Dialog title="Add a novel" icon="sparkles" onClose={onClose} busy={busy}>
      <form className="col" style={{ gap: 14 }} onSubmit={submit}>
        <label className="field">
          <span>Title</span>
          <input value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. I Was Trapped in a Bad Ending…" autoFocus />
        </label>
        <label className="field">
          <span>Scraping technique</span>
          <select value={adapter} onChange={e => setAdapter(e.target.value)}>
            {adapters.map(a => <option key={a.name} value={a.name}>{a.label}</option>)}
          </select>
        </label>
        <label className="field">
          <span>First chapter URL</span>
          <input value={startUrl} onChange={e => setStartUrl(e.target.value)} placeholder="https://…/series/<slug>/1" />
        </label>
        <div className="row wrap" style={{ gap: 16 }}>
          <label className="field" style={{ flex: "0 0 110px" }}>
            <span>Language</span>
            <input value={language} onChange={e => setLanguage(e.target.value)} placeholder="en" />
          </label>
          <label className="check">
            <input type="checkbox" checked={isRaw} onChange={e => setIsRaw(e.target.checked)} />
            Raw (needs translation)
          </label>
          <label className="check">
            <input type="checkbox" checked={codex} onChange={e => setCodex(e.target.checked)} />
            Enable codex
          </label>
        </div>
        {err && <div className="acct-err">{err}</div>}
        <div className="row" style={{ gap: 10, justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" variant="primary" icon="check" loading={busy}>Add to library</Button>
        </div>
      </form>
    </Dialog>
  );
}
