/* ============================================================
   Novel → Manage tab (owner/admin). All the operator tooling that used to
   interleave with the reader surface, re-homed as cards: sources, pipeline,
   background jobs, health, glossary, contribution + tag inboxes,
   sharing settings, metadata editing, danger zone.
   ============================================================ */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { acquisitionApi } from "../../modules/acquisition/api.js";
import { catalogApi } from "../../modules/catalog/api.js";
import { codexApi } from "../../modules/codex/api.js";
import { experienceApi } from "../../modules/experience/api.js";
import { readingApi } from "../../modules/reading/api.js";
import { translationApi } from "../../modules/translation/api.js";
import { workApi } from "../../modules/work/api.js";
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
import { useVoicesQuery } from "../../modules/narration/queries.js";
import { useChaptersQuery } from "../../modules/reading/queries.js";
import { useInvalidate } from "../../shared/query/useInvalidate.js";
import { useTitle } from "../../lib/hooks.js";
import { TRANSLATION_TYPE_LABELS } from "../../lib/constants.js";

/* ── Sources ── */
import {
  AddSourceForm, ContributionsInbox, EditSourceForm, GlossaryCard, HealthPanel,
  MetadataCard, NovelJobs, TagSuggestionsInbox,
} from "../../modules/catalog/ManagePanels.jsx";

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

  useEffect(() => { acquisitionApi.adapters().then(setAdapters).catch(() => setAdapters([])); }, []);

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
      await acquisitionApi.scrape(novelId, { max_chapters: maxCh.trim() ? parseInt(maxCh) : null });
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
      const r = await codexApi.codexBuild(novelId, { ...params, ai_backend: codexBackend });
      toast(`Codex build queued on ${(r.execution_backend || "api").toUpperCase()}${r.model ? ` · ${r.model}` : ""}.`, { tone: "ok" });
      reloadNovel();
    } catch (e) { toast("Codex build failed: " + (e.message || "error"), { tone: "danger" }); }
  }

  async function runTranslate() {
    try {
      const r = await translationApi.translate(novelId, { ai_backend: translateBackend });
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
      const r = await translationApi.seedGlossary(novelId);
      toast(`Seeded ${r.seeded} glossary terms from the codex.`, { tone: "ok" });
    } catch (e) { toast("Seed failed: " + (e.message || "error"), { tone: "danger" }); }
  }

  async function changeVisibility(v) {
    setBusyVis(true);
    try { await catalogApi.setVisibility(novelId, v); reloadNovel(); toast(`Visibility set to ${v}.`, { tone: "ok" }); }
    catch (e) { toast(e.message || "Could not change visibility.", { tone: "danger" }); }
    finally { setBusyVis(false); }
  }

  async function changePolicy(v) {
    setBusyVis(true);
    try { await catalogApi.updateNovel(novelId, { contribution_policy: v }); reloadNovel(); }
    catch (e) { toast(e.message || "Couldn't change the policy.", { tone: "danger" }); }
    finally { setBusyVis(false); }
  }

  async function onToggleTag(t, group) {
    if (tagBusy) return;
    setTagBusy(true);
    try { await catalogApi.updateNovel(novelId, { status_tags: toggleTag(novel.status_tags || [], t, group) }); reloadNovel(); }
    catch (e) { toast(e.message || "Update failed.", { tone: "danger" }); }
    finally { setTagBusy(false); }
  }

  async function doDelete() {
    setDeleting(true);
    try {
      await catalogApi.deleteNovel(novelId);
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
