/* ============================================================
   Novel → Manage tab (owner/admin). All the operator tooling that used to
   interleave with the reader surface, re-homed as cards: sources, pipeline,
   background jobs, health, glossary, contribution + tag inboxes,
   sharing settings, metadata editing, danger zone.
   ============================================================ */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { API } from "../../lib/api.js";
import { useAuth } from "../../App.jsx";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { NovelHeader } from "./NovelHeader.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, StatTile, ProgressBar } from "../../components/ui.jsx";
import { CostConfirmDialog, ConfirmDialog } from "../../components/overlay.jsx";
import { JobRow } from "../../components/JobRow.jsx";
import { DiffView } from "../../lib/diff.jsx";
import { useToast } from "../../components/toast.jsx";
import { TagEditor, toggleTag } from "../../features/tags.jsx";
import { ttsVoiceLabel } from "../../features/toc.jsx";
import { useChaptersQuery, useVoicesQuery, useInvalidate } from "../../lib/queries.js";
import { useTitle } from "../../lib/hooks.js";
import { TRANSLATION_TYPE_LABELS } from "../../lib/constants.js";

/* ── Sources ── */
function AddSourceForm({ novelId, adapters, onAdded, onCancel }) {
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
      await API.addSource(novelId, {
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

function EditSourceForm({ novelId, source, onSaved, onCancel }) {
  const [offset, setOffset] = useState(String(source.chapter_offset || 0));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function save() {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      const r = await API.updateSource(novelId, source.id, { chapter_offset: parseFloat(offset) || 0 });
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
function NovelJobs({ novelId }) {
  const [jobs, setJobs] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const timerRef = useRef(null);
  const { toast } = useToast();

  const load = useCallback(async () => {
    try {
      const r = await API.jobs({ novel_id: novelId, limit: 25 });
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
    try { await API.cancelJob(job.id); await load(); }
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
function HealthPanel({ novelId, ttsVoices }) {
  const [hp, setHp] = useState(null);
  useEffect(() => {
    let cancel = false;
    setHp(null);
    API.novelHealth(novelId).then(r => { if (!cancel) setHp(r); }).catch(() => { if (!cancel) setHp(false); });
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
function GlossaryCard({ novelId }) {
  const [glossary, setGlossary] = useState([]);
  const [st, setSt] = useState("");
  const [tr, setTr] = useState("");
  const [type, setType] = useState("name");
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  const reload = useCallback(() => {
    API.glossary(novelId).then(setGlossary).catch(() => setGlossary([]));
  }, [novelId]);
  useEffect(() => { reload(); }, [reload]);

  async function add(e) {
    e.preventDefault();
    if (!st.trim() || !tr.trim() || busy) return;
    setBusy(true);
    try {
      await API.upsertGlossary(novelId, { source_term: st.trim(), translation: tr.trim(), term_type: type, locked: true });
      setSt(""); setTr(""); reload();
    } catch (e2) {
      toast(e2.message || "Couldn't add the term.", { tone: "danger" });
    } finally { setBusy(false); }
  }
  const toggleLock = async (g) => {
    await API.upsertGlossary(novelId, { source_term: g.source_term, translation: g.translation, term_type: g.term_type, notes: g.notes, locked: !g.locked });
    reload();
  };
  const del = async (g) => { await API.delGlossary(novelId, g.id); reload(); };

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
function ContributionsInbox({ novelId, reloadNovel }) {
  const [items, setItems] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [drafts, setDrafts] = useState({});
  const { toast } = useToast();
  const load = useCallback(() => {
    API.contributions(novelId).then(setItems).catch(() => setItems([]));
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
      if (accept) await API.acceptContribution(novelId, c.id, c.is_conflict ? resolved : undefined);
      else await API.rejectContribution(novelId, c.id);
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
function TagSuggestionsInbox({ novelId, reloadNovel }) {
  const [items, setItems] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const { toast } = useToast();
  const load = useCallback(() => {
    API.tagSuggestions(novelId).then(setItems).catch(() => setItems([]));
  }, [novelId]);
  useEffect(() => { load(); }, [load]);

  if (items == null || items.length === 0) return null;

  const act = async (s, accept) => {
    setBusyId(s.id);
    try {
      if (accept) await API.acceptTagSuggestion(novelId, s.id);
      else await API.rejectTagSuggestion(novelId, s.id);
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
function MetadataCard({ novel, reloadNovel }) {
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
      await API.updateNovel(novel.id, {
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
      const r = await API.uploadNovelCover(novel.id, file);
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
export function Manage() {
  const { novel, novelId, reloadNovel } = useNovel();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const invalidate = useInvalidate();
  const { refetch: refetchToc } = useChaptersQuery(novelId);
  const { data: voicesData } = useVoicesQuery();
  useTitle("Manage", novel.title);

  const [adapters, setAdapters] = useState([]);
  const [addingSource, setAddingSource] = useState(false);
  const [editSourceId, setEditSourceId] = useState(null);
  const [maxCh, setMaxCh] = useState("");
  const [pendingCost, setPendingCost] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [busyVis, setBusyVis] = useState(false);

  const agyCapability = user && user.ai_backends && user.ai_backends.agy;
  const canAgyTranslate = !!(agyCapability && agyCapability.enabled && (agyCapability.workloads || []).includes("translate_batch"));
  const canAgyCodex = !!(agyCapability && agyCapability.enabled && (agyCapability.workloads || []).includes("codex_extract"));
  const [translateBackend, setTranslateBackend] = useState("auto");
  const [codexBackend, setCodexBackend] = useState("auto");
  const [codexFromChapter, setCodexFromChapter] = useState("");
  const [codexToChapter, setCodexToChapter] = useState("");
  const [tagBusy, setTagBusy] = useState(false);

  useEffect(() => {
    const preferred = agyCapability && agyCapability.default_backend === "agy" ? "agy" : "api";
    setTranslateBackend(canAgyTranslate ? preferred : "auto");
    setCodexBackend(canAgyCodex ? preferred : "auto");
  }, [user && user.id, agyCapability && agyCapability.default_backend, canAgyTranslate, canAgyCodex]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { API.adapters().then(setAdapters).catch(() => setAdapters([])); }, []);

  if (!novel.can_edit) {
    return (
      <div className="page page-enter">
        <NovelHeader />
        <EmptyState icon="lock" title="Owners only" body="You don't have permission to manage this novel." />
      </div>
    );
  }

  const hasRaw = (novel.sources || []).some(s => s.is_raw);

  async function doScrape() {
    try {
      await API.scrape(novelId, { max_chapters: maxCh.trim() ? parseInt(maxCh) : null });
      toast("Scrape queued — it runs in the background.", { tone: "ok" });
    } catch (e) {
      toast("Scrape failed: " + (e.message || "error"), { tone: "danger" });
    }
  }

  function codexRangeParams() {
    const fromText = codexFromChapter.trim();
    const toText = codexToChapter.trim();
    const from = fromText ? Number(fromText) : null;
    const to = toText ? Number(toText) : null;
    if ((fromText && !Number.isFinite(from)) || (toText && !Number.isFinite(to))) {
      throw new Error("Codex chapter bounds must be valid numbers.");
    }
    if (from != null && to != null && from > to) {
      throw new Error("The first codex chapter cannot be after the final chapter.");
    }
    return { from_chapter: from, to_chapter: to };
  }

  async function runBuildCodex(params) {
    try {
      const r = await API.codexBuild(novelId, { ...params, ai_backend: codexBackend });
      toast(`Codex build queued on ${(r.execution_backend || "api").toUpperCase()}${r.model ? ` · ${r.model}` : ""}.`, { tone: "ok" });
      reloadNovel();
    } catch (e) { toast("Codex build failed: " + (e.message || "error"), { tone: "danger" }); }
  }

  async function runTranslate() {
    try {
      const r = await API.translate(novelId, { ai_backend: translateBackend });
      toast(`Translation queued on ${(r.execution_backend || "api").toUpperCase()}${r.model ? ` · ${r.model}` : ""}.`, { tone: "ok" });
    } catch (e) { toast("Translate failed: " + (e.message || "error"), { tone: "danger" }); }
  }

  const buildCodex = () => {
    let params;
    try { params = codexRangeParams(); }
    catch (e) { toast(e.message, { tone: "danger" }); return; }
    setPendingCost({
      action: "codex_build", params,
      title: novel.codex_enabled ? "Extend codex" : "Build codex",
      actionLabel: "Start build", run: () => runBuildCodex(params),
    });
  };
  const doTranslate = () => setPendingCost({
    action: "translate", params: {},
    title: "Translate raw chapters", actionLabel: "Start translation", run: runTranslate,
  });

  async function doSeedGlossary() {
    try {
      const r = await API.seedGlossary(novelId);
      toast(`Seeded ${r.seeded} glossary terms from the codex.`, { tone: "ok" });
    } catch (e) { toast("Seed failed: " + (e.message || "error"), { tone: "danger" }); }
  }

  async function changeVisibility(v) {
    setBusyVis(true);
    try { await API.setVisibility(novelId, v); reloadNovel(); toast(`Visibility set to ${v}.`, { tone: "ok" }); }
    catch (e) { toast(e.message || "Could not change visibility.", { tone: "danger" }); }
    finally { setBusyVis(false); }
  }

  async function changePolicy(v) {
    setBusyVis(true);
    try { await API.updateNovel(novelId, { contribution_policy: v }); reloadNovel(); }
    catch (e) { toast(e.message || "Couldn't change the policy.", { tone: "danger" }); }
    finally { setBusyVis(false); }
  }

  async function onToggleTag(t, group) {
    if (tagBusy) return;
    setTagBusy(true);
    try { await API.updateNovel(novelId, { status_tags: toggleTag(novel.status_tags || [], t, group) }); reloadNovel(); }
    catch (e) { toast(e.message || "Update failed.", { tone: "danger" }); }
    finally { setTagBusy(false); }
  }

  async function doDelete() {
    setDeleting(true);
    try {
      await API.deleteNovel(novelId);
      invalidate(["novels"], ["home"]);
      navigate("/library");
    } catch (e) {
      toast("Delete failed: " + (e.message || "error"), { tone: "danger" });
      setDeleting(false);
    }
  }

  const isAdmin = !!(user && user.role === "admin");
  const visOptions = isAdmin ? ["private", "public", "global"]
    : (novel.visibility === "global" ? ["global"] : ["private", "public"]);

  return (
    <div className="page page-enter">
      <NovelHeader />

      <div className="manage-grid">
        {/* Sources */}
        <div className="card manage-card">
          <h3><Icon name="spider" size={16} /> Sources</h3>
          {(novel.sources || []).map(s => (
            <div key={s.id}>
              <div className="source-row">
                <div className="grow" style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600 }}>
                    {s.label || s.adapter}
                    {s.is_raw && <Chip style={{ marginLeft: 8 }}>raw · {s.language}</Chip>}
                  </div>
                  <div className="muted" style={{ fontSize: "var(--text-xs)", wordBreak: "break-all" }}>{s.start_url}</div>
                </div>
                {s.chapter_offset ? <Chip className="mono">{s.chapter_offset > 0 ? "+" : ""}{s.chapter_offset}</Chip> : null}
                <button className="icon-btn plain" title="Edit offset" aria-label="Edit offset"
                        onClick={() => setEditSourceId(editSourceId === s.id ? null : s.id)}>
                  <Icon name="edit" size={15} />
                </button>
              </div>
              {editSourceId === s.id && (
                <EditSourceForm novelId={novelId} source={s}
                  onCancel={() => setEditSourceId(null)}
                  onSaved={(r) => {
                    setEditSourceId(null);
                    toast(r && r.renumbered ? `Renumbered ${r.renumbered} chapters to the new offset.` : "Source updated.", { tone: "ok" });
                    reloadNovel(); refetchToc();
                  }} />
              )}
            </div>
          ))}
          {(novel.sources || []).length === 0 && <div className="muted" style={{ padding: 8 }}>No sources yet.</div>}
          {!addingSource
            ? <div><Button variant="ghost" size="sm" icon="plus" onClick={() => setAddingSource(true)}>Add source</Button></div>
            : <AddSourceForm novelId={novelId} adapters={adapters}
                onCancel={() => setAddingSource(false)}
                onAdded={() => { setAddingSource(false); reloadNovel(); }} />}
        </div>

        {/* Pipeline */}
        <div className="card manage-card">
          <h3><Icon name="cpu" size={16} /> Pipeline</h3>
          <div className="row wrap" style={{ gap: 10, alignItems: "flex-end" }}>
            <label className="field" style={{ flex: "0 0 120px" }}>
              <span>Max chapters</span>
              <input value={maxCh} onChange={e => setMaxCh(e.target.value)} placeholder="(all)" inputMode="numeric" />
            </label>
            <Button variant="primary" icon="refresh" onClick={doScrape}>Scrape</Button>
            <Button variant="ghost" icon="refresh" onClick={() => { refetchToc(); reloadNovel(); }}>Refresh</Button>
          </div>

          {hasRaw && (
            <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
              {canAgyTranslate && (
                <label className="field" style={{ maxWidth: 300, marginBottom: 10 }}>
                  <span>AI backend</span>
                  <select value={translateBackend} onChange={e => setTranslateBackend(e.target.value)}>
                    <option value="agy">Antigravity — local subscription queue</option>
                    <option value="api">API — provider usage</option>
                  </select>
                </label>
              )}
              <div className="row wrap" style={{ gap: 10 }}>
                <Button variant="ghost" icon="globe" onClick={doTranslate}>Translate raw chapters</Button>
                {novel.codex_enabled && <Button variant="ghost" icon="merge" onClick={doSeedGlossary}>Seed glossary from codex</Button>}
              </div>
              <p className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 8, marginBottom: 0 }}>
                Reading already translates on demand; this pre-translates the whole raw source.
              </p>
            </div>
          )}

          <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 }}>
            <div className="row wrap" style={{ gap: 10, alignItems: "flex-end", marginBottom: 10 }}>
              {canAgyCodex && (
                <label className="field" style={{ flex: "1 1 220px", maxWidth: 300 }}>
                  <span>AI backend</span>
                  <select value={codexBackend} onChange={e => setCodexBackend(e.target.value)}>
                    <option value="agy">Antigravity — local subscription queue</option>
                    <option value="api">API — provider usage</option>
                  </select>
                </label>
              )}
              <label className="field" style={{ flex: "0 0 105px" }}>
                <span>From chapter</span>
                <input type="number" step="any" value={codexFromChapter}
                       onChange={e => setCodexFromChapter(e.target.value)}
                       placeholder={novel.min_chapter != null ? String(novel.min_chapter) : "first"} />
              </label>
              <label className="field" style={{ flex: "0 0 115px" }}>
                <span>Through chapter</span>
                <input type="number" step="any" value={codexToChapter}
                       onChange={e => setCodexToChapter(e.target.value)} placeholder="latest" />
              </label>
              <Button variant="ghost" icon="brain" onClick={buildCodex}>
                {novel.codex_enabled ? "Extend codex" : "Build codex"}
              </Button>
            </div>
            <p className="muted" style={{ fontSize: "var(--text-xs)", margin: 0 }}>
              Builds the spoiler-safe knowledge base from scraped chapters. Leave both bounds blank for every available chapter; completed chapters are skipped.
            </p>
          </div>
        </div>

        {/* Sharing + tags */}
        <div className="card manage-card">
          <h3><Icon name="globe" size={16} /> Sharing</h3>
          <label className="field" style={{ maxWidth: 260 }}>
            <span>Visibility</span>
            <select value={novel.visibility || "private"} disabled={busyVis} onChange={e => changeVisibility(e.target.value)}>
              {visOptions.map(v => <option key={v} value={v}>{{ private: "Private", public: "Public", global: "Global" }[v]}</option>)}
            </select>
          </label>
          <label className="field" style={{ maxWidth: 260 }}>
            <span>Reader edits</span>
            <select value={novel.contribution_policy || "manual"} disabled={busyVis} onChange={e => changePolicy(e.target.value)}>
              <option value="manual">Review edits</option>
              <option value="auto">Auto-merge clean edits</option>
            </select>
          </label>
          <div className="field">
            <span>Tags</span>
            <TagEditor tags={novel.status_tags || []} onToggle={onToggleTag} disabled={tagBusy} />
            {novel.translation_type && (
              <span className="muted" style={{ fontSize: "var(--text-xs)", textTransform: "none", letterSpacing: 0, fontWeight: 500 }}>
                Auto-detected: {TRANSLATION_TYPE_LABELS[novel.translation_type]}
              </span>
            )}
          </div>
        </div>

        <MetadataCard key={novel.id + ":" + novel.title} novel={novel} reloadNovel={reloadNovel} />

        <NovelJobs novelId={novelId} />
        <HealthPanel novelId={novelId} ttsVoices={(voicesData && voicesData.voices) || []} />
        {(hasRaw || true) && <GlossaryCard novelId={novelId} />}
        <ContributionsInbox novelId={novelId} reloadNovel={reloadNovel} />
        <TagSuggestionsInbox novelId={novelId} reloadNovel={reloadNovel} />

        {/* Danger zone */}
        <div className="card manage-card danger-zone manage-span">
          <h3><Icon name="alert" size={16} /> Danger zone</h3>
          <p className="muted" style={{ margin: 0, fontSize: "var(--text-sm)" }}>
            Deleting removes the novel, its chapters, codex, bookmarks and files for everyone. There is no undo.
          </p>
          <div><Button variant="ghost" className="is-danger" icon="trash" onClick={() => setConfirmDelete(true)}>Delete novel</Button></div>
        </div>
      </div>

      {pendingCost && (
        <CostConfirmDialog
          novelId={novelId} action={pendingCost.action} params={pendingCost.params}
          title={pendingCost.title} actionLabel={pendingCost.actionLabel}
          onCancel={() => setPendingCost(null)}
          onConfirm={async () => { await pendingCost.run(); setPendingCost(null); }} />
      )}

      {confirmDelete && (
        <ConfirmDialog
          title={`Delete “${novel.title}”?`}
          requireText={novel.title}
          confirmLabel="Delete permanently"
          busy={deleting}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={doDelete}
          body="This permanently removes the novel and everything tied to it — chapters, codex, bookmarks, imported files. There's no undo."
        />
      )}
    </div>
  );
}
