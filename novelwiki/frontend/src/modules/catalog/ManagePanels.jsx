/* ============================================================
   Manage panels — source editing, the book's background jobs, health,
   the translation glossary, the contribution + tag-suggestion inboxes and
   the details (metadata) form. Loading, empty and failed states are shown
   honestly, each failure with a way to try again.
   ============================================================ */
import React, { useCallback, useEffect, useRef, useState } from "react";

import { acquisitionApi } from "../acquisition/api.js";
import { NovelpiaRecoveryLinks } from "../acquisition/index.js";
import { catalogApi } from "./api.js";
import { experienceApi } from "../experience/api.js";
import { readingApi } from "../reading/api.js";
import { translationApi } from "../translation/api.js";
import { workApi } from "../work/api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, Cover, ProgressBar, Skeleton, StatTile } from "../../components/ui.jsx";
import { JobRow } from "../work/index.js";
import { DiffView } from "../../lib/diff.jsx";
import { useToast } from "../../components/toast.jsx";
import { ttsVoiceLabel } from "../reading/index.js";
import { ManageCard } from "./ManageKit.jsx";

function PanelError({ children, onRetry }) {
  return (
    <div className="mc-error" role="alert">
      <Icon name="alert" size={15} />
      <span>{children}</span>
      {onRetry && <Button variant="ghost" size="sm" icon="refresh" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export function EditSourceForm({ novelId, source, onSaved, onCancel }) {
  const [offset, setOffset] = useState(String(source.chapter_offset || 0));
  const [archivePassword, setArchivePassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const archiveSource = source.adapter === "raw-fucknovelpia";
  const changed = offset !== String(source.chapter_offset || 0) || (archiveSource && !!archivePassword);

  async function save() {
    if (busy || !changed) return;
    setErr(null);
    const parsedOffset = Number(offset);
    if (!offset.trim() || !Number.isFinite(parsedOffset)) {
      setErr("Enter a valid chapter offset, such as -1 or 0.5.");
      return;
    }
    const fields = {};
    if (parsedOffset !== Number(source.chapter_offset || 0)) fields.chapter_offset = parsedOffset;
    if (archiveSource && archivePassword) fields.config = { archive_password: archivePassword };
    if (!Object.keys(fields).length) { onSaved({ status: "noop", renumbered: 0 }); return; }
    setBusy(true);
    try {
      const r = await acquisitionApi.updateSource(novelId, source.id, fields);
      setArchivePassword("");
      onSaved(r);
    } catch (e) {
      setErr(e.message || "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="nf-inset">
      <label className="field">
        <span>Chapter offset (added to this source's own numbers)</span>
        <input value={offset} onChange={e => setOffset(e.target.value)} placeholder="e.g. -1" inputMode="decimal" disabled={busy} />
      </label>
      <p className="nf-help">
        Use -1 if this raw source is one chapter ahead of the translation. Existing chapters are renumbered immediately.
      </p>
      {archiveSource && <label className="field">
        <span>New ZIP password</span>
        <input type="password" autoComplete="off" value={archivePassword} onChange={e => setArchivePassword(e.target.value)}
               placeholder="Leave blank to keep the current password" disabled={busy} />
      </label>}
      {err && <p className="acct-err nf-err" role="alert">{err}</p>}
      <div className="nf-actions">
        <Button variant="primary" size="sm" loading={busy} disabled={!changed} onClick={save}>Save</Button>
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>Cancel</Button>
      </div>
    </div>
  );
}

/* ── Per-novel job center ── */
export function NovelJobs({ novelId }) {
  const [jobs, setJobs] = useState(null);
  const [failed, setFailed] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const timerRef = useRef(null);
  const { toast } = useToast();

  const load = useCallback(async () => {
    try {
      const r = await workApi.jobs({ novel_id: novelId, limit: 25 });
      setJobs(r.jobs || []);
      setFailed(false);
      return r.jobs || [];
    } catch (e) { setFailed(true); setJobs(j => j || []); return []; }
  }, [novelId]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const list = await load();
      if (!alive) return;
      const active = list.some(j => ["queued", "running", "waiting_provider"].includes(j.status));
      timerRef.current = setTimeout(tick, active ? 3000 : 15000);
    };
    tick();
    return () => { alive = false; if (timerRef.current) clearTimeout(timerRef.current); };
  }, [load]);

  const cancel = async (job) => {
    setBusyId(job.id);
    try { await workApi.cancelJob(job.id); await load(); }
    catch (e) { toast(e.message || "Cancel failed.", { tone: "danger" }); }
    finally { setBusyId(null); }
  };

  // Say what is actually happening: running, queued and waiting are different.
  const tally = { running: 0, queued: 0, waiting_provider: 0 };
  (jobs || []).forEach(j => { if (j.status in tally) tally[j.status] += 1; });
  const activeLabel = [
    tally.running && `${tally.running} running`,
    tally.queued && `${tally.queued} queued`,
    tally.waiting_provider && `${tally.waiting_provider} waiting`,
  ].filter(Boolean).join(" · ");
  return (
    <ManageCard icon="layers" title="Background jobs" className="mc-jobs"
      meta={activeLabel ? <span className="mc-live"><span className="mc-live-dot" aria-hidden="true" />{activeLabel}</span> : null}>
      {jobs == null ? (
        <div className="mc-skel">{[0, 1, 2].map(i => <Skeleton key={i} height={44} />)}</div>
      ) : failed && jobs.length === 0 ? (
        <PanelError onRetry={load}>This book's jobs couldn't load.</PanelError>
      ) : jobs.length === 0 ? (
        <div className="mc-empty"><Icon name="circleCheck" size={16} /> Nothing running for this book. Scrapes, translations and builds appear here.</div>
      ) : (
        <div className="mc-joblist">
          {jobs.map(job => (
            <JobRow key={job.id}
                    job={{ ...job, source: "job", cancelable: ["queued", "running", "waiting_provider"].includes(job.status) }}
                    busy={busyId === job.id}
                    onCancel={() => cancel(job)} />
          ))}
        </div>
      )}
    </ManageCard>
  );
}

/* ── Health panel ── */
export function HealthPanel({ novelId, ttsVoices }) {
  const [hp, setHp] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancel = false;
    setHp(null);
    experienceApi.novelHealth(novelId).then(r => { if (!cancel) setHp(r); }).catch(() => { if (!cancel) setHp(false); });
    return () => { cancel = true; };
  }, [novelId, attempt]);

  if (hp == null || hp === false) {
    return (
      <ManageCard icon="shield" title="Health" className="mc-health">
        {hp === false
          ? <PanelError onRetry={() => setAttempt(a => a + 1)}>Health checks couldn't load.</PanelError>
          : <div className="health-grid" aria-busy="true">{[0, 1, 2, 3].map(i => <Skeleton key={i} height={86} style={{ borderRadius: 16 }} />)}</div>}
      </ManageCard>
    );
  }

  const catalog = new Map((ttsVoices || []).map(v => [v.id, v]));
  const prose = hp.audio ? (hp.audio.prose_chapters || 0) : 0;
  const voiceRows = [];
  if (hp.audio) {
    const byVoice = new Map();
    (ttsVoices || []).filter(v => v.ready !== false).forEach(v => {
      byVoice.set(v.id, { voice_id: v.id, have: 0, missing: prose, catalog: v });
    });
    (hp.audio.voices || []).forEach(v => {
      byVoice.set(v.voice_id, { ...byVoice.get(v.voice_id), ...v });
    });
    byVoice.forEach(v => voiceRows.push(v));
    voiceRows.sort((a, b) => ttsVoiceLabel(a.voice_id, catalog).localeCompare(ttsVoiceLabel(b.voice_id, catalog)));
  }
  const notes = [];
  if (hp.codex.missing) notes.push({ tone: "warn", text: "Codex is enabled but empty — build it from the pipeline." });
  if (!hp.codex.missing && hp.codex.stale) notes.push({ tone: "warn", text: `Codex covers up to ch. ${hp.codex.coverage_chapter} of ${hp.book_max_chapter} — rebuild to catch up.` });
  if (hp.source_last_scraped) notes.push({ tone: "info", text: `Source last scraped ${new Date(hp.source_last_scraped).toLocaleString()}.` });
  const warnings = (hp.codex.missing || hp.codex.stale ? 1 : 0) + (hp.untranslated_raw_chapters > 0 ? 1 : 0) + ((hp.recent_errors || []).length ? 1 : 0);

  return (
    <ManageCard icon="shield" title="Health" className="mc-health"
      meta={<Chip tone={warnings ? "warn" : "ok"}>{warnings ? `${warnings} to look at` : "All clear"}</Chip>}>
      <div className="health-grid">
        <StatTile value={hp.codex.entities} label="Codex entities" tone={hp.codex.missing || hp.codex.stale ? "warn" : "ok"} />
        <StatTile value={hp.untranslated_raw_chapters} label="Untranslated raw" tone={hp.untranslated_raw_chapters > 0 ? "warn" : "ok"} />
        {hp.audio && hp.audio.missing != null
          ? <StatTile value={hp.audio.missing} label="Missing audio (any voice)" tone={hp.audio.missing > 0 ? "warn" : "ok"} />
          : <StatTile value="—" label="Audio" />}
        <StatTile value={hp.total_chapters} label="Chapters" />
      </div>
      {voiceRows.length > 0 && (
        <div className="health-voices">
          {voiceRows.map(v => {
            const have = v.have || 0;
            const pct = prose ? Math.round((have / prose) * 100) : 0;
            const meta = [v.catalog && v.catalog.language, v.catalog && v.catalog.gender, v.catalog && v.catalog.accent].filter(Boolean).join(" · ");
            return (
              <div key={v.voice_id} className="health-voice-row">
                <div className="health-voice-head">
                  <span className="health-voice-orb" aria-hidden="true">{ttsVoiceLabel(v.voice_id, catalog).charAt(0).toUpperCase()}</span>
                  <span className="health-voice-name">{ttsVoiceLabel(v.voice_id, catalog)}</span>
                  <span className="mono muted">{have}/{prose}</span>
                </div>
                <ProgressBar size="xs" tone="ok" value={pct} label={`${ttsVoiceLabel(v.voice_id, catalog)} narration coverage`} />
                {meta && <div className="health-voice-meta">{meta}</div>}
              </div>
            );
          })}
        </div>
      )}
      {(notes.length > 0 || (hp.recent_errors || []).length > 0) && (
        <ul className="health-notes">
          {notes.map((n, i) => <li key={i} className={"is-" + n.tone}><span className="health-note-dot" aria-hidden="true" />{n.text}</li>)}
          {(hp.recent_errors || []).slice(0, 3).map((e, i) => (
            <li key={"e" + i} className="is-danger health-err" title={e.error}>
              <span className="health-note-dot" aria-hidden="true" />
              <span className="health-err-text">{e.kind} error: {(e.error || "").slice(0, 80)}</span>
              <NovelpiaRecoveryLinks kind={e.kind} error={e.error} />
            </li>
          ))}
        </ul>
      )}
    </ManageCard>
  );
}

/* ── Glossary ── */
export function GlossaryCard({ novelId }) {
  const [glossary, setGlossary] = useState(null);
  const [failed, setFailed] = useState(false);
  const [st, setSt] = useState("");
  const [tr, setTr] = useState("");
  const [type, setType] = useState("name");
  const [busy, setBusy] = useState(false);
  const [rowBusy, setRowBusy] = useState(null);
  const { toast } = useToast();

  const reload = useCallback(() => {
    translationApi.glossary(novelId)
      .then(list => { setGlossary(list || []); setFailed(false); })
      .catch(() => { setFailed(true); setGlossary(g => g || []); });
  }, [novelId]);
  useEffect(() => { reload(); }, [reload]);

  async function add(e) {
    e.preventDefault();
    if (!st.trim() || !tr.trim() || busy) return;
    setBusy(true);
    try {
      await translationApi.upsertGlossary(novelId, { source_term: st.trim(), translation: tr.trim(), term_type: type, locked: true });
      setSt(""); setTr(""); reload();
    } catch (e2) {
      toast(e2.message || "Couldn't add the term.", { tone: "danger" });
    } finally { setBusy(false); }
  }
  const rowAction = async (g, run, failure) => {
    setRowBusy(g.id);
    try { await run(); reload(); }
    catch (e) { toast(e.message || failure, { tone: "danger" }); }
    finally { setRowBusy(null); }
  };
  const toggleLock = (g) => rowAction(g, () => translationApi.upsertGlossary(novelId, { source_term: g.source_term, translation: g.translation, term_type: g.term_type, notes: g.notes, locked: !g.locked }), "Couldn't change the lock.");
  const del = (g) => rowAction(g, () => translationApi.delGlossary(novelId, g.id), "Couldn't delete the term.");

  const list = glossary || [];
  return (
    <ManageCard icon="globe" title="Translation glossary" className="mc-glossary"
      sub="Pinned renderings keep names and terms consistent across every translated chapter. Locked terms are never auto-changed."
      meta={glossary != null && <span className="mc-count mono">{list.length}</span>}>
      <form className="gl-form" onSubmit={add}>
        <label className="gl-field">
          <span className="sr-only">Source term</span>
          <input className="input" value={st} onChange={e => setSt(e.target.value)} placeholder="Source term (林轩)" />
        </label>
        <span className="gl-arrow" aria-hidden="true"><Icon name="arrowRight" size={15} /></span>
        <label className="gl-field">
          <span className="sr-only">English rendering</span>
          <input className="input" value={tr} onChange={e => setTr(e.target.value)} placeholder="English (Lin Xuan)" />
        </label>
        <label className="gl-type">
          <span className="sr-only">Term type</span>
          <select className="input" value={type} onChange={e => setType(e.target.value)}>
            {["name", "place", "skill", "item", "term"].map(o => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <Button type="submit" variant="primary" icon="plus" loading={busy}>Add</Button>
      </form>
      {glossary == null ? (
        <div className="mc-skel">{[0, 1].map(i => <Skeleton key={i} height={40} />)}</div>
      ) : failed && list.length === 0 ? (
        <PanelError onRetry={reload}>The glossary couldn't load.</PanelError>
      ) : list.length === 0 ? (
        <div className="mc-empty"><Icon name="quote" size={16} /> No terms yet. Add names or places whose spelling should never drift.</div>
      ) : (
        <ul className="gl-list">
          {list.map(g => (
            <li key={g.id} className={"gl-row" + (g.locked ? " is-locked" : "")}>
              <span className="gl-pair">
                <span className="gl-src">{g.source_term}</span>
                <Icon name="arrowRight" size={13} className="gl-row-arrow" />
                <span className="gl-tr">{g.translation}</span>
                {g.term_type && <Chip className="gl-kind">{g.term_type}</Chip>}
              </span>
              <span className="gl-tools">
                <button type="button" className={"icon-btn plain" + (g.locked ? " active" : "")} disabled={rowBusy === g.id}
                        title={g.locked ? "Locked — won't auto-change" : "Click to lock"}
                        aria-label={g.locked ? "Unlock term" : "Lock term"} aria-pressed={!!g.locked}
                        onClick={() => toggleLock(g)}>
                  <Icon name={g.locked ? "lock" : "unlock"} size={15} />
                </button>
                <button type="button" className="icon-btn plain" disabled={rowBusy === g.id} title="Delete" aria-label="Delete term" onClick={() => del(g)}>
                  <Icon name="x" size={15} />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </ManageCard>
  );
}

/* ── Contribution inbox ── */
export function ContributionsInbox({ novelId, items, reload, reloadNovel }) {
  const [busyId, setBusyId] = useState(null);
  const [drafts, setDrafts] = useState({});
  const { toast } = useToast();

  if (!items || items.length === 0) return null;

  const act = async (c, accept) => {
    const resolved = (drafts[c.id] || "").trim();
    if (accept && c.is_conflict && !resolved) {
      toast("Resolve this conflict before accepting it.", { tone: "info" });
      return;
    }
    setBusyId(c.id);
    try {
      if (accept) await readingApi.acceptContribution(novelId, c.id, c.is_conflict ? resolved : undefined);
      else await readingApi.rejectContribution(novelId, c.id);
      reload(); reloadNovel && reloadNovel();
      toast(accept ? "Contribution merged." : "Contribution rejected.", { tone: "ok" });
    } catch (e) { toast(e.message || "Action failed.", { tone: "danger" }); }
    finally { setBusyId(null); }
  };

  return (
    <ManageCard icon="merge" title="Contribution requests" className="mc-inbox"
      sub="Readers offered these edits to the shared translation. Accepting merges them for everyone."
      meta={<span className="mc-count is-accent mono">{items.length}</span>}>
      <div className="inbox-list">
        {items.map(c => {
          const draft = drafts[c.id] || "";
          return (
            <article key={c.id} className="contrib-row">
              <div className="contrib-head">
                <Chip className="mono">Ch. {c.chapter}</Chip>
                <span className="contrib-who">{c.from_display_name}</span>
                <span className="contrib-handle">@{c.from_username}</span>
                {c.is_conflict && <Chip tone="danger" title="Base changed since this was offered">conflict</Chip>}
              </div>
              <DiffView oldText={c.base_content || ""} newText={c.content || ""} oldLabel="Current base" newLabel="Proposed edit" />
              {c.is_conflict && (
                <div className="contrib-merge">
                  <div className="row wrap" style={{ gap: 8 }}>
                    <Button variant="ghost" size="sm" onClick={() => setDrafts(d => ({ ...d, [c.id]: c.content || "" }))}>Use proposed</Button>
                    <Button variant="ghost" size="sm" onClick={() => setDrafts(d => ({ ...d, [c.id]: c.base_content || "" }))}>Use latest base</Button>
                  </div>
                  <textarea className="tt-textarea contrib-merge-text" rows={6} value={draft}
                            aria-label="Resolved translation"
                            onChange={e => setDrafts(d => ({ ...d, [c.id]: e.target.value }))}
                            placeholder="Paste or edit the resolved translation to merge…" />
                </div>
              )}
              <div className="contrib-actions">
                <Button variant="primary" size="sm" icon="check"
                        disabled={busyId === c.id || (c.is_conflict && !draft.trim())}
                        onClick={() => act(c, true)}
                        title={c.is_conflict ? "Merge the resolved text into the shared base" : "Merge into the shared base"}>
                  {c.is_conflict ? "Accept merge" : "Accept"}
                </Button>
                <Button variant="ghost" size="sm" icon="x" disabled={busyId === c.id} onClick={() => act(c, false)}>Reject</Button>
              </div>
            </article>
          );
        })}
      </div>
    </ManageCard>
  );
}

/* ── Tag suggestion inbox ── */
export function TagSuggestionsInbox({ novelId, items, reload, reloadNovel }) {
  const [busyId, setBusyId] = useState(null);
  const { toast } = useToast();

  if (!items || items.length === 0) return null;

  const act = async (s, accept) => {
    setBusyId(s.id);
    try {
      if (accept) await catalogApi.acceptTagSuggestion(novelId, s.id);
      else await catalogApi.rejectTagSuggestion(novelId, s.id);
      reload(); reloadNovel && reloadNovel();
    } catch (e) { toast(e.message || "Action failed.", { tone: "danger" }); }
    finally { setBusyId(null); }
  };

  return (
    <ManageCard icon="sparkles" title="Tag suggestions" className="mc-inbox"
      sub="Readers proposed these tag sets. Applying one replaces the book's tags."
      meta={<span className="mc-count is-accent mono">{items.length}</span>}>
      <div className="inbox-list">
        {items.map(s => (
          <article key={s.id} className="contrib-row">
            <div className="contrib-head">
              <span className="contrib-who">{s.from_display_name}</span>
              <span className="contrib-handle">@{s.from_username}</span>
            </div>
            <div className="st-tags">
              {s.tags.length === 0
                ? <span className="muted" style={{ fontSize: "var(--text-sm)" }}>(clear all tags)</span>
                : s.tags.map(t => <Chip key={t}>{t}</Chip>)}
            </div>
            {s.note && <blockquote className="contrib-note">{s.note}</blockquote>}
            <div className="contrib-actions">
              <Button variant="primary" size="sm" icon="check" disabled={busyId === s.id} onClick={() => act(s, true)}>Apply</Button>
              <Button variant="ghost" size="sm" icon="x" disabled={busyId === s.id} onClick={() => act(s, false)}>Reject</Button>
            </div>
          </article>
        ))}
      </div>
    </ManageCard>
  );
}

/* ── Metadata edit ── */
export function MetadataCard({ novel, reloadNovel }) {
  const [title, setTitle] = useState(novel.title || "");
  const [author, setAuthor] = useState(novel.author || "");
  const [description, setDescription] = useState(novel.description || "");
  const [cover, setCover] = useState(novel.cover_url || "");
  const [busy, setBusy] = useState(false);
  const [uploadingCover, setUploadingCover] = useState(false);
  const coverFileRef = useRef(null);
  const { toast } = useToast();

  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || busy || uploadingCover) return;
    setBusy(true);
    try {
      await catalogApi.updateNovel(novel.id, {
        title: title.trim(), author: author.trim() || null,
        description: description.trim() || null, cover_url: cover.trim() || null,
      });
      toast("Novel saved.", { tone: "ok" });
      reloadNovel();
    } catch (e2) {
      toast(e2.message || "Couldn't save.", { tone: "danger" });
    } finally { setBusy(false); }
  }

  async function onPickCover(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setUploadingCover(true);
    try {
      const r = await catalogApi.uploadNovelCover(novel.id, file);
      setCover(r.cover_url || "");
      toast("Cover uploaded. Save to keep it.", { tone: "ok" });
    } catch (err) {
      toast(err.message || "Cover upload failed.", { tone: "danger" });
    } finally {
      setUploadingCover(false);
      if (coverFileRef.current) coverFileRef.current.value = "";
    }
  }

  const dirty = title !== (novel.title || "") || author !== (novel.author || "")
    || description !== (novel.description || "") || cover !== (novel.cover_url || "");
  return (
    <ManageCard as="form" icon="edit" title="Details" className="mc-details" onSubmit={submit}
      sub="How the book is titled and presented everywhere."
      meta={dirty && <span className="mc-dirty">Unsaved changes</span>}>
      <div className="md-grid">
        <div className="md-cover">
          <Cover src={cover.trim() || null} title={title || novel.title} author={author} className="md-cover-img" />
          <Button variant="ghost" size="sm" icon="upload" disabled={uploadingCover} loading={uploadingCover}
                  onClick={() => coverFileRef.current && coverFileRef.current.click()}>
            Upload cover
          </Button>
          <input ref={coverFileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif"
                 style={{ display: "none" }} onChange={onPickCover} />
        </div>
        <div className="md-fields">
          <label className="field">
            <span>Title</span>
            <input value={title} onChange={e => setTitle(e.target.value)} className="md-title-input" />
          </label>
          <label className="field">
            <span>Author</span>
            <input value={author} onChange={e => setAuthor(e.target.value)} />
          </label>
          <label className="field">
            <span>Cover image</span>
            <input value={cover} onChange={e => setCover(e.target.value)} placeholder="https://…" />
            <span className="field-help">Paste an image URL, or upload PNG/JPG/WebP/GIF under 10 MB.</span>
          </label>
        </div>
      </div>
      <label className="field">
        <span>Description</span>
        <textarea value={description} onChange={e => setDescription(e.target.value)} rows={5} />
      </label>
      <div className="nf-actions">
        <Button type="submit" variant="primary" icon="check" loading={busy} disabled={uploadingCover}>Save details</Button>
      </div>
    </ManageCard>
  );
}
