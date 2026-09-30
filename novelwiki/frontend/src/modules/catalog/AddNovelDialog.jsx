/* New web source, with defaults and URL guidance from the adapter registry.
   A glass sheet: the title set large, the source as one composed group
   (website · language · URL with its hint), and the two opt-ins as
   switches with a line of explanation each. */
import React, { useId, useState } from "react";
import { catalogApi } from "./api.js";
import { useSourceAdapter } from "./useSourceAdapter.js";
import { Dialog } from "../../components/overlay.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button } from "../../components/ui.jsx";

export function AddNovelDialog({ onCreated, onClose }) {
  const source = useSourceAdapter();
  const hintId = useId();
  const rawHelpId = useId();
  const codexHelpId = useId();
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
    <Dialog title="Add a novel" icon="sparkles" wide onClose={onClose} busy={busy}>
      <form className="nf nf-dialog" onSubmit={submit}>
        <p className="nf-intro">Paste a link from a supported website. Chapters are fetched in the background — you can start reading as soon as the first ones arrive.</p>

        <label className="field nf-title-field">
          <span>Title</span>
          <input value={title} onChange={e => setTitle(e.target.value)} placeholder="e.g. Lord of the Mysteries" required disabled={busy} />
        </label>

        <fieldset className="nf-group">
          <legend className="nf-legend"><Icon name="link" size={13} /> Source</legend>
          <div className="nf-row">
            <label className="field nf-grow">
              <span>Website</span>
              <select value={source.adapter} onChange={e => source.chooseAdapter(e.target.value)} disabled={!source.ready || busy}>
                {!source.ready && <option value="">Choose a website</option>}
                {source.adapters.map(a => <option key={a.name} value={a.name}>{a.label}</option>)}
              </select>
            </label>
            <label className="field nf-lang">
              <span>Language</span>
              <input value={source.language} onChange={e => source.setLanguage(e.target.value)} placeholder="en" required disabled={busy} />
            </label>
          </div>
          {source.loading && <p className="nf-status" role="status"><span className="spinner" aria-hidden="true" /> Loading website sources…</p>}
          {source.error && <div role="alert" className="nf-alert"><Icon name="alert" size={15} /><span className="grow">{source.error}</span> <Button variant="ghost" size="sm" onClick={source.retry}>Try again</Button></div>}
          <label className="field">
            <span>Novel or chapter URL</span>
            <input type="url" value={startUrl} onChange={e => setStartUrl(e.target.value)} placeholder="https://…" aria-describedby={hintId} required disabled={busy} className="nf-url" />
          </label>
          <p id={hintId} className="nf-help">{source.selected?.start_url_hint || "Use a supported novel or chapter URL for this website."}</p>
          {source.adapter === "global-novelpia" && <p className="source-account-copy nf-note">
            <a href="/account/sources" target="_blank" rel="noreferrer">Add or update Novelpia cookies in Settings</a> (opens in a new tab).
          </p>}
          {source.adapter === "raw-fucknovelpia" && <label className="field">
            <span>ZIP password</span>
            <input type="password" autoComplete="off" value={archivePassword} onChange={e => setArchivePassword(e.target.value)} required disabled={busy} />
          </label>}
        </fieldset>

        <div className="nf-switches">
          <div className="nf-switch-row">
            <label className="check nf-switch">
              <input type="checkbox" checked={source.isRaw} onChange={e => source.setIsRaw(e.target.checked)} disabled={busy} aria-describedby={rawHelpId} />
              Raw (needs translation)
            </label>
            <p id={rawHelpId} className="nf-switch-help">Chapters arrive untranslated and are translated as you read.</p>
          </div>
          <div className="nf-switch-row">
            <label className="check nf-switch">
              <input type="checkbox" checked={codex} onChange={e => setCodex(e.target.checked)} disabled={busy} aria-describedby={codexHelpId} />
              Enable codex
            </label>
            <p id={codexHelpId} className="nf-switch-help">A spoiler-safe wiki of people, places and events that grows with your progress.</p>
          </div>
        </div>

        {err && <div className="nf-alert" role="alert"><Icon name="alert" size={15} /><span>{err}</span></div>}
        <div className="nf-actions is-end nf-foot">
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" variant="primary" icon="check" loading={busy} disabled={!source.ready}>Add to library</Button>
        </div>
      </form>
    </Dialog>
  );
}
