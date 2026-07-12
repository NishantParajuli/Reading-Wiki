import React, { useCallback, useEffect, useRef, useState } from "react";

import { acquisitionApi } from "../acquisition/api.js";
import { catalogApi } from "./api.js";
import { experienceApi } from "../experience/api.js";
import { readingApi } from "../reading/api.js";
import { translationApi } from "../translation/api.js";
import { workApi } from "../work/api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, StatTile, ProgressBar } from "../../components/ui.jsx";
import { JobRow } from "../work/index.js";
import { DiffView } from "../../lib/diff.jsx";
import { useToast } from "../../components/toast.jsx";
import { ttsVoiceLabel } from "../reading/index.js";

export function AddSourceForm({ novelId, adapters, onAdded, onCancel }) {
  const [adapter, setAdapter] = useState(adapters[0] ? adapters[0].name : "fenrirealm");
  const [startUrl, setStartUrl] = useState("");
  const [language, setLanguage] = useState("en");
  const [isRaw, setIsRaw] = useState(false);
  const [continuesFrom, setContinuesFrom] = useState("");
  const [localStart, setLocalStart] = useState("");
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  async function submit(e) {
    e.preventDefault();
    if (!startUrl.trim() || busy) return;
    setBusy(true);
    // Custom offset: global_number = local_number + offset ⇒ offset = global_start - local_start
    let offset = 0;
    if (continuesFrom.trim()) {
      const glob = parseFloat(continuesFrom);
      const loc = localStart.trim() ? parseFloat(localStart) : 1.0;
      offset = glob - loc;
    }
    try {
      await acquisitionApi.addSource(novelId, {
        adapter, start_url: startUrl.trim(), language, is_raw: isRaw,
        chapter_offset: offset, config: null,
      });
      onAdded();
    } catch (e2) {
      toast(e2.message || "Couldn't add the source.", { tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="col" style={{ gap: 12, marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 12 }} onSubmit={submit}>
      <div className="row wrap" style={{ gap: 12 }}>
        <label className="field" style={{ flex: "1 1 180px" }}>
          <span>Technique</span>
          <select value={adapter} onChange={e => setAdapter(e.target.value)}>
            {adapters.map(a => <option key={a.name} value={a.name}>{a.label}</option>)}
          </select>
        </label>
        <label className="field" style={{ flex: "0 0 100px" }}>
          <span>Language</span>
          <input value={language} onChange={e => setLanguage(e.target.value)} />
        </label>
      </div>
      <label className="field">
        <span>First chapter URL</span>
        <input value={startUrl} onChange={e => setStartUrl(e.target.value)} placeholder="https://…/1" />
      </label>
      <div className="row wrap" style={{ gap: 14 }}>
        <label className="field" style={{ flex: "1 1 170px" }}>
          <span>Continues from global chapter</span>
          <input value={continuesFrom} onChange={e => setContinuesFrom(e.target.value)} placeholder="e.g. 125" inputMode="decimal" />
        </label>
        {continuesFrom.trim() && (
          <label className="field" style={{ flex: "1 1 170px" }}>
            <span>Source-local starting chapter</span>
            <input value={localStart} onChange={e => setLocalStart(e.target.value)} placeholder="defaults to 1" inputMode="decimal" />
          </label>
        )}
        <label className="check">
          <input type="checkbox" checked={isRaw} onChange={e => setIsRaw(e.target.checked)} />
          Raw (needs translation)
        </label>
      </div>
      <div className="row" style={{ gap: 10 }}>
        <Button type="submit" variant="primary" loading={busy}>Add source</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

export function EditSourceForm({ novelId, source, onSaved, onCancel }) {
  const [offset, setOffset] = useState(String(source.chapter_offset || 0));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function save() {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      const r = await acquisitionApi.updateSource(novelId, source.id, { chapter_offset: parseFloat(offset) || 0 });
      onSaved(r);
    } catch (e) {
      setErr(e.message || "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ padding: 12, marginTop: 8, background: "var(--bg-2)", borderRadius: "var(--radius-sm)" }}>
      <label className="field">
        <span>Chapter offset (added to this source's own numbers)</span>
        <input value={offset} onChange={e => setOffset(e.target.value)} placeholder="e.g. -1" inputMode="decimal" />
      </label>
      <p className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 6 }}>
        Use -1 if this raw source is one chapter ahead of the translation. Existing chapters are renumbered immediately.
      </p>
      {err && <p className="acct-err" style={{ marginTop: 4 }}>{err}</p>}
      <div className="row" style={{ gap: 10, marginTop: 8 }}>
        <Button variant="primary" loading={busy} onClick={save}>Save</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  );
}

/* ── Per-novel job center ── */
export function NovelJobs({ novelId }) {
  const [jobs, setJobs] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const timerRef = useRef(null);
  const { toast } = useToast();

  const load = useCallback(async () => {
    try {
      const r = await workApi.jobs({ novel_id: novelId, limit: 25 });
      setJobs(r.jobs || []);
      return r.jobs || [];
    } catch (e) { setJobs([]); return []; }
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

  if (jobs == null || jobs.length === 0) return null;

  const cancel = async (job) => {
    setBusyId(job.id);
    try { await workApi.cancelJob(job.id); await load(); }
    catch (e) { toast(e.message || "Cancel failed.", { tone: "danger" }); }
    finally { setBusyId(null); }
  };

  return (
    <div className="card manage-card manage-span">
      <h3><Icon name="layers" size={16} /> Background jobs</h3>
      <div>
        {jobs.map(job => (
          <JobRow key={job.id}
                  job={{ ...job, source: "job", cancelable: ["queued", "running", "waiting_provider"].includes(job.status) }}
                  busy={busyId === job.id}
                  onCancel={() => cancel(job)} />
        ))}
      </div>
    </div>
  );
}

/* ── Health panel ── */
export function HealthPanel({ novelId, ttsVoices }) {
  const [hp, setHp] = useState(null);
  useEffect(() => {
    let cancel = false;
    setHp(null);
    experienceApi.novelHealth(novelId).then(r => { if (!cancel) setHp(r); }).catch(() => { if (!cancel) setHp(false); });
    return () => { cancel = true; };
  }, [novelId]);

  if (hp === false || hp == null) return null;

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

  return (
    <div className="card manage-card manage-span">
      <h3><Icon name="shield" size={16} /> Health</h3>
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
                  <span>{ttsVoiceLabel(v.voice_id, catalog)}</span>
                  <span className="mono muted">{have}/{prose}</span>
                </div>
                <ProgressBar size="xs" tone="ok" value={pct} style={{ marginTop: 7 }} />
                {meta && <div className="health-voice-meta muted">{meta}</div>}
              </div>
            );
          })}
        </div>
      )}
      <div className="health-notes">
        {hp.codex.missing && <div>• Codex is enabled but empty — build it from the pipeline.</div>}
        {!hp.codex.missing && hp.codex.stale && (
          <div>• Codex covers up to ch. {hp.codex.coverage_chapter} of {hp.book_max_chapter} — rebuild to catch up.</div>
        )}
        {hp.source_last_scraped && <div>• Source last scraped {new Date(hp.source_last_scraped).toLocaleString()}.</div>}
        {(hp.recent_errors || []).slice(0, 3).map((e, i) => (
          <div key={i} className="health-err" title={e.error}>• {e.kind} error: {(e.error || "").slice(0, 80)}</div>
        ))}
      </div>
    </div>
  );
}

/* ── Glossary ── */
export function GlossaryCard({ novelId }) {
  const [glossary, setGlossary] = useState([]);
  const [st, setSt] = useState("");
  const [tr, setTr] = useState("");
  const [type, setType] = useState("name");
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  const reload = useCallback(() => {
    translationApi.glossary(novelId).then(setGlossary).catch(() => setGlossary([]));
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
  const toggleLock = async (g) => {
    await translationApi.upsertGlossary(novelId, { source_term: g.source_term, translation: g.translation, term_type: g.term_type, notes: g.notes, locked: !g.locked });
    reload();
  };
  const del = async (g) => { await translationApi.delGlossary(novelId, g.id); reload(); };

  return (
    <div className="card manage-card manage-span">
      <h3><Icon name="globe" size={16} /> Translation glossary <span className="muted" style={{ fontWeight: 400 }}>({glossary.length})</span></h3>
      <form className="row wrap" style={{ gap: 8 }} onSubmit={add}>
        <input className="input" style={{ flex: "1 1 150px" }} value={st} onChange={e => setSt(e.target.value)} placeholder="Source term (林轩)" />
        <input className="input" style={{ flex: "1 1 150px" }} value={tr} onChange={e => setTr(e.target.value)} placeholder="English (Lin Xuan)" />
        <select className="input" style={{ flex: "0 0 104px", width: "auto" }} value={type} onChange={e => setType(e.target.value)}>
          {["name", "place", "skill", "item", "term"].map(o => <option key={o} value={o}>{o}</option>)}
        </select>
        <Button type="submit" variant="primary" loading={busy}>Add</Button>
      </form>
      {glossary.map(g => (
        <div key={g.id} className="gl-row">
          <span className="gl-src">{g.source_term}</span>
          <Icon name="arrowRight" size={13} className="muted" />
          <span className="gl-tr">{g.translation}</span>
          {g.term_type && <Chip>{g.term_type}</Chip>}
          <div className="grow" />
          <button className={"icon-btn plain" + (g.locked ? " active" : "")}
                  title={g.locked ? "Locked — won't auto-change" : "Click to lock"}
                  aria-label={g.locked ? "Unlock term" : "Lock term"}
                  onClick={() => toggleLock(g)}>
            <Icon name={g.locked ? "lock" : "unlock"} size={15} />
          </button>
          <button className="icon-btn plain" title="Delete" aria-label="Delete term" onClick={() => del(g)}>
            <Icon name="x" size={15} />
          </button>
        </div>
      ))}
    </div>
  );
}

/* ── Contribution inbox ── */
export function ContributionsInbox({ novelId, reloadNovel }) {
  const [items, setItems] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [drafts, setDrafts] = useState({});
  const { toast } = useToast();
  const load = useCallback(() => {
    readingApi.contributions(novelId).then(setItems).catch(() => setItems([]));
  }, [novelId]);
  useEffect(() => { load(); }, [load]);

  if (items == null || items.length === 0) return null;

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
      load(); reloadNovel && reloadNovel();
      toast(accept ? "Contribution merged." : "Contribution rejected.", { tone: "ok" });
    } catch (e) { toast(e.message || "Action failed.", { tone: "danger" }); }
    finally { setBusyId(null); }
  };

  return (
    <div className="card manage-card manage-span">
      <h3><Icon name="merge" size={16} /> Contribution requests <span className="tab-count">{items.length}</span></h3>
      {items.map(c => {
        const draft = drafts[c.id] || "";
        return (
          <div key={c.id} className="contrib-row">
            <div className="row wrap" style={{ gap: 8, marginBottom: 6 }}>
              <Chip className="mono">Ch. {c.chapter}</Chip>
              <span style={{ fontWeight: 600 }}>{c.from_display_name}</span>
              <span className="muted" style={{ fontSize: "var(--text-xs)" }}>@{c.from_username}</span>
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
                          onChange={e => setDrafts(d => ({ ...d, [c.id]: e.target.value }))}
                          placeholder="Paste or edit the resolved translation to merge…" />
              </div>
            )}
            <div className="row" style={{ gap: 8, marginTop: 8 }}>
              <Button variant="primary" icon="check"
                      disabled={busyId === c.id || (c.is_conflict && !draft.trim())}
                      onClick={() => act(c, true)}
                      title={c.is_conflict ? "Merge the resolved text into the shared base" : "Merge into the shared base"}>
                {c.is_conflict ? "Accept merge" : "Accept"}
              </Button>
              <Button variant="ghost" icon="x" disabled={busyId === c.id} onClick={() => act(c, false)}>Reject</Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Tag suggestion inbox ── */
export function TagSuggestionsInbox({ novelId, reloadNovel }) {
  const [items, setItems] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const { toast } = useToast();
  const load = useCallback(() => {
    catalogApi.tagSuggestions(novelId).then(setItems).catch(() => setItems([]));
  }, [novelId]);
  useEffect(() => { load(); }, [load]);

  if (items == null || items.length === 0) return null;

  const act = async (s, accept) => {
    setBusyId(s.id);
    try {
      if (accept) await catalogApi.acceptTagSuggestion(novelId, s.id);
      else await catalogApi.rejectTagSuggestion(novelId, s.id);
      load(); reloadNovel && reloadNovel();
    } catch (e) { toast(e.message || "Action failed.", { tone: "danger" }); }
    finally { setBusyId(null); }
  };

  return (
    <div className="card manage-card manage-span">
      <h3><Icon name="sparkles" size={16} /> Tag suggestions <span className="tab-count">{items.length}</span></h3>
      {items.map(s => (
        <div key={s.id} className="contrib-row">
          <div className="row" style={{ gap: 8, marginBottom: 6 }}>
            <span style={{ fontWeight: 600 }}>{s.from_display_name}</span>
            <span className="muted" style={{ fontSize: "var(--text-xs)" }}>@{s.from_username}</span>
          </div>
          <div className="st-tags" style={{ marginBottom: s.note ? 6 : 0 }}>
            {s.tags.length === 0
              ? <span className="muted" style={{ fontSize: "var(--text-sm)" }}>(clear all tags)</span>
              : s.tags.map(t => <Chip key={t}>{t}</Chip>)}
          </div>
          {s.note && <div className="muted" style={{ fontSize: "var(--text-sm)" }}>{s.note}</div>}
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <Button variant="primary" icon="check" disabled={busyId === s.id} onClick={() => act(s, true)}>Apply</Button>
            <Button variant="ghost" icon="x" disabled={busyId === s.id} onClick={() => act(s, false)}>Reject</Button>
          </div>
        </div>
      ))}
    </div>
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

  return (
    <form className="card manage-card" onSubmit={submit}>
      <h3><Icon name="edit" size={16} /> Details</h3>
      <label className="field">
        <span>Title</span>
        <input value={title} onChange={e => setTitle(e.target.value)} />
      </label>
      <label className="field">
        <span>Author</span>
        <input value={author} onChange={e => setAuthor(e.target.value)} />
      </label>
      <div className="field">
        <span>Cover image</span>
        <div className="cover-edit">
          {cover
            ? <img className="cover-edit-preview" src={cover} alt="" />
            : <div className="cover-edit-preview cover-edit-empty"><Icon name="book" size={20} /></div>}
          <div className="cover-edit-field">
            <input className="input" value={cover} onChange={e => setCover(e.target.value)} placeholder="https://…" />
            <div className="row wrap" style={{ gap: 8 }}>
              <Button variant="ghost" size="sm" icon="upload" disabled={uploadingCover} loading={uploadingCover}
                      onClick={() => coverFileRef.current && coverFileRef.current.click()}>
                Upload cover
              </Button>
              <input ref={coverFileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif"
                     style={{ display: "none" }} onChange={onPickCover} />
              <span className="muted" style={{ fontSize: "var(--text-xs)" }}>PNG/JPG/WebP/GIF, under 10 MB.</span>
            </div>
          </div>
        </div>
      </div>
      <label className="field">
        <span>Description</span>
        <textarea value={description} onChange={e => setDescription(e.target.value)} rows={4} />
      </label>
      <div className="row">
        <Button type="submit" variant="primary" loading={busy} disabled={uploadingCover}>Save details</Button>
      </div>
    </form>
  );
}

/* ── Main Manage screen ── */
