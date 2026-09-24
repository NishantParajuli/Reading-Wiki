import React, { useId, useState } from "react";
import { acquisitionApi } from "../acquisition/api.js";
import { Button } from "../../components/ui.jsx";
import { useSourceAdapter } from "./useSourceAdapter.js";

export function AddSourceForm({ novelId, onAdded, onCancel }) {
  const source = useSourceAdapter();
  const hintId = useId();
  const [startUrl, setStartUrl] = useState("");
  const [archivePassword, setArchivePassword] = useState("");
  const [continuesFrom, setContinuesFrom] = useState("");
  const [localStart, setLocalStart] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    if (!source.ready || !startUrl.trim() || !source.language.trim() || busy) return;
    if (source.adapter === "raw-fucknovelpia" && !archivePassword) return;
    setError(null);
    let offset = 0;
    if (continuesFrom.trim()) {
      const global = Number(continuesFrom);
      const local = localStart.trim() ? Number(localStart) : 1;
      offset = global - local;
      if (![global, local, offset].every(Number.isFinite)) {
        setError("Enter valid chapter numbers, such as 125 or 125.5.");
        return;
      }
    }
    setBusy(true);
    try {
      await acquisitionApi.addSource(novelId, {
        adapter: source.adapter, start_url: startUrl.trim(), language: source.language.trim(),
        is_raw: source.isRaw, chapter_offset: offset,
        config: source.adapter === "raw-fucknovelpia" ? { archive_password: archivePassword } : null,
      });
      onAdded();
    } catch (e) {
      setError(e.message || "Couldn't add the source.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="col" style={{ gap: 12, marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }} onSubmit={submit}>
      <div className="row wrap" style={{ gap: 12 }}>
        <label className="field" style={{ flex: "1 1 180px" }}>
          <span>Website</span>
          <select value={source.adapter} onChange={e => source.chooseAdapter(e.target.value)} disabled={!source.ready || busy}>
            {!source.ready && <option value="">Choose a website</option>}
            {source.adapters.map(a => <option key={a.name} value={a.name}>{a.label}</option>)}
          </select>
        </label>
        <label className="field" style={{ flex: "0 0 100px" }}>
          <span>Language</span>
          <input value={source.language} onChange={e => source.setLanguage(e.target.value)} required disabled={busy} />
        </label>
      </div>
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
      <div className="row wrap" style={{ gap: 14 }}>
        <label className="field" style={{ flex: "1 1 170px" }}>
          <span>Continues from global chapter</span>
          <input value={continuesFrom} onChange={e => setContinuesFrom(e.target.value)} placeholder="e.g. 125" inputMode="decimal" disabled={busy} />
        </label>
        {continuesFrom.trim() && (
          <label className="field" style={{ flex: "1 1 170px" }}>
            <span>Source-local starting chapter</span>
            <input value={localStart} onChange={e => setLocalStart(e.target.value)} placeholder="defaults to 1" inputMode="decimal" disabled={busy} />
          </label>
        )}
        <label className="check">
          <input type="checkbox" checked={source.isRaw} onChange={e => source.setIsRaw(e.target.checked)} disabled={busy} />
          Raw (needs translation)
        </label>
      </div>
      {error && <p className="acct-err" role="alert">{error}</p>}
      <div className="row" style={{ gap: 10 }}>
        <Button type="submit" variant="primary" loading={busy} disabled={!source.ready}>Add source</Button>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
      </div>
    </form>
  );
}
