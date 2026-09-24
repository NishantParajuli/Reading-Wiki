/* New web source, with defaults and URL guidance from the adapter registry. */
import React, { useId, useState } from "react";
import { catalogApi } from "./api.js";
import { useSourceAdapter } from "./useSourceAdapter.js";
import { Dialog } from "../../components/overlay.jsx";
import { Button } from "../../components/ui.jsx";

export function AddNovelDialog({ onCreated, onClose }) {
  const source = useSourceAdapter();
  const hintId = useId();
  const [title, setTitle] = useState("");
  const [startUrl, setStartUrl] = useState("");
  const [archivePassword, setArchivePassword] = useState("");
  const [codex, setCodex] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || !startUrl.trim() || !source.language.trim() || !source.ready || busy) return;
    if (source.adapter === "raw-fucknovelpia" && !archivePassword) return;
    setBusy(true); setErr(null);
    try {
      const res = await catalogApi.createNovel({
        title: title.trim(),
        codex_enabled: codex,
        original_language: source.language.trim(),
        source: {
          adapter: source.adapter, start_url: startUrl.trim(), language: source.language.trim(),
          is_raw: source.isRaw,
          config: source.adapter === "raw-fucknovelpia" ? { archive_password: archivePassword } : null,
        },
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
          <input value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. I Was Trapped in a Bad Ending…" autoFocus required disabled={busy} />
        </label>
        <label className="field">
          <span>Website</span>
          <select value={source.adapter} onChange={e => source.chooseAdapter(e.target.value)} disabled={!source.ready || busy}>
            {!source.ready && <option value="">Choose a website</option>}
            {source.adapters.map(a => <option key={a.name} value={a.name}>{a.label}</option>)}
          </select>
        </label>
        {source.loading && <p className="muted" role="status">Loading website sources…</p>}
        {source.error && <div role="alert" className="acct-err">{source.error} <Button variant="ghost" onClick={source.retry}>Try again</Button></div>}
        <label className="field">
          <span>Novel or chapter URL</span>
          <input type="url" value={startUrl} onChange={e => setStartUrl(e.target.value)} placeholder="https://…" aria-describedby={hintId} required disabled={busy} />
        </label>
        <p id={hintId} className="muted" style={{ margin: 0, fontSize: "var(--text-xs)" }}>{source.selected?.start_url_hint || "Use a supported novel or chapter URL for this website."}</p>
        {source.adapter === "raw-fucknovelpia" && <label className="field">
          <span>ZIP password</span>
          <input type="password" autoComplete="off" value={archivePassword} onChange={e => setArchivePassword(e.target.value)} required disabled={busy} />
        </label>}
        <div className="row wrap" style={{ gap: 16 }}>
          <label className="field" style={{ flex: "0 0 110px" }}>
            <span>Language</span>
            <input value={source.language} onChange={e => source.setLanguage(e.target.value)} placeholder="en" required disabled={busy} />
          </label>
          <label className="check">
            <input type="checkbox" checked={source.isRaw} onChange={e => source.setIsRaw(e.target.checked)} disabled={busy} />
            Raw (needs translation)
          </label>
          <label className="check">
            <input type="checkbox" checked={codex} onChange={e => setCodex(e.target.checked)} disabled={busy} />
            Enable codex
          </label>
        </div>
        {err && <div className="acct-err" role="alert">{err}</div>}
        <div className="row" style={{ gap: 10, justifyContent: "flex-end" }}>
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" variant="primary" icon="check" loading={busy} disabled={!source.ready}>Add to library</Button>
        </div>
      </form>
    </Dialog>
  );
}
