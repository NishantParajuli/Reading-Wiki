/* ============================================================
   Manage → the owner's primary cards: Sources, Pipeline, Sharing, Danger.
   Each owns its own state and API calls (unchanged from the old single
   Manage screen); the page composes them into the section ledger.
   ============================================================ */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { acquisitionApi } from "../acquisition/api.js";
import { catalogApi } from "./api.js";
import { codexApi } from "../codex/api.js";
import { translationApi } from "../translation/api.js";
import { useAuth } from "../../App.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, RelativeTime } from "../../components/ui.jsx";
import { ConfirmDialog, CostConfirmDialog } from "../../components/overlay.jsx";
import { useToast } from "../../components/toast.jsx";
import { useInvalidate } from "../../shared/query/useInvalidate.js";
import { TRANSLATION_TYPE_LABELS } from "../../lib/constants.js";
import { AddSourceForm } from "./AddSourceForm.jsx";
import { EditSourceForm } from "./ManagePanels.jsx";
import { TagEditor, toggleTag } from "./tags.jsx";
import { ChoiceCards, ManageCard, Reveal, Step } from "./ManageKit.jsx";

/* ── Sources ── */
export function SourcesCard({ novel, novelId, reloadNovel, refetchToc }) {
  const [adding, setAdding] = useState(false);
  const [editId, setEditId] = useState(null);
  const { toast } = useToast();
  const sources = novel.sources || [];
  return (
    <ManageCard icon="spider" title="Sources"
      sub="Where this book's chapters are fetched from. An offset lines a raw source up with the translation's numbering."
      meta={sources.length > 0 && <span className="mc-count mono">{sources.length}</span>}>
      {sources.length === 0 ? (
        <div className="mc-empty"><Icon name="link" size={16} /> No sources yet — add one to start fetching chapters.</div>
      ) : (
        <ul className="src-list">
          {sources.map(s => {
            const editing = editId === s.id;
            return (
              <li key={s.id} className={"src-item" + (editing ? " is-editing" : "")}>
                <div className="src-row">
                  <span className="src-mono" aria-hidden="true">{(s.label || s.adapter || "?").trim().charAt(0).toUpperCase()}</span>
                  <div className="src-text">
                    <div className="src-name">
                      <span>{s.label || s.adapter}</span>
                      {s.is_raw && <Chip tone="warn">raw · {s.language}</Chip>}
                      {!s.is_raw && s.language && <Chip className="mono">{s.language}</Chip>}
                    </div>
                    <div className="src-url mono">{s.start_url}</div>
                    {s.last_scraped_at && <div className="src-when">Last scraped <RelativeTime iso={s.last_scraped_at} /></div>}
                  </div>
                  {s.chapter_offset ? <Chip className="mono src-offset" title="Chapter offset">{s.chapter_offset > 0 ? "+" : ""}{s.chapter_offset}</Chip> : null}
                  <button type="button" className={"icon-btn plain" + (editing ? " active" : "")} title="Edit source" aria-label="Edit source"
                          aria-expanded={editing} onClick={() => setEditId(editing ? null : s.id)}>
                    <Icon name="edit" size={15} />
                  </button>
                </div>
                <Reveal show={editing}>
                  <EditSourceForm novelId={novelId} source={s}
                    onCancel={() => setEditId(null)}
                    onSaved={(r) => {
                      setEditId(null);
                      toast(r && r.renumbered ? `Renumbered ${r.renumbered} chapters to the new offset.` : "Source updated.", { tone: "ok" });
                      reloadNovel(); refetchToc();
                    }} />
                </Reveal>
              </li>
            );
          })}
        </ul>
      )}
      <Reveal show={adding}>
        <AddSourceForm novelId={novelId}
          onCancel={() => setAdding(false)}
          onAdded={() => { setAdding(false); reloadNovel(); }} />
      </Reveal>
      {!adding && (
        <div className="mc-foot">
          <Button variant="ghost" size="sm" icon="plus" onClick={() => setAdding(true)}>Add source</Button>
        </div>
      )}
    </ManageCard>
  );
}

/* ── Pipeline: fetch → translate → codex ── */
function BackendSelect({ value, onChange, agy, openai }) {
  return (
    <label className="field mc-backend">
      <span>AI backend</span>
      <select value={value} onChange={e => onChange(e.target.value)}>
        <option value="auto">Auto — admin policy</option>
        {agy && <option value="agy">Antigravity — local queue</option>}
        {openai && <option value="openai_codex">OpenAI Codex — ChatGPT plan</option>}
        <option value="api">API — provider usage</option>
      </select>
    </label>
  );
}

export function PipelineCard({ novel, novelId, reloadNovel, refetchToc }) {
  const { user } = useAuth();
  const { toast } = useToast();
  const [maxCh, setMaxCh] = useState("");
  const [pendingCost, setPendingCost] = useState(null);
  const [translateBackend, setTranslateBackend] = useState("auto");
  const [codexBackend, setCodexBackend] = useState("auto");
  const [codexFromChapter, setCodexFromChapter] = useState("");
  const [codexToChapter, setCodexToChapter] = useState("");

  const agyCapability = user && user.ai_backends && user.ai_backends.agy;
  const openaiCodexCapability = user && user.ai_backends && user.ai_backends.openai_codex;
  const allows = (cap, workload) => !!(cap && cap.enabled && (cap.workloads || []).includes(workload));
  const canAgyTranslate = allows(agyCapability, "translate_batch");
  const canAgyCodex = allows(agyCapability, "codex_extract");
  const canOpenAiTranslate = allows(openaiCodexCapability, "translate_batch");
  const canOpenAiCodex = allows(openaiCodexCapability, "codex_extract");

  useEffect(() => {
    const preferred = (openaiCodexCapability && openaiCodexCapability.default_backend)
      || (agyCapability && agyCapability.default_backend) || "api";
    const translateAllowed = (preferred === "agy" && canAgyTranslate)
      || (preferred === "openai_codex" && canOpenAiTranslate);
    const codexAllowed = (preferred === "agy" && canAgyCodex)
      || (preferred === "openai_codex" && canOpenAiCodex);
    setTranslateBackend(translateAllowed ? preferred : "auto");
    setCodexBackend(codexAllowed ? preferred : "auto");
  }, [user && user.id, agyCapability && agyCapability.default_backend, openaiCodexCapability && openaiCodexCapability.default_backend, canAgyTranslate, canAgyCodex, canOpenAiTranslate, canOpenAiCodex]); // eslint-disable-line react-hooks/exhaustive-deps

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

  let step = 0;
  return (
    <ManageCard icon="cpu" title="Pipeline" className="mc-pipeline"
      sub="Everything here runs in the background — follow it under Activity & health or in Jobs.">
      <div className="mc-steps">
        <Step n={++step} title="Fetch chapters" desc="Scrape new chapters from every source, oldest first.">
          <div className="mc-controls">
            <label className="field mc-num">
              <span>Max chapters</span>
              <input value={maxCh} onChange={e => setMaxCh(e.target.value)} placeholder="(all)" inputMode="numeric" />
            </label>
            <Button variant="primary" icon="refresh" onClick={doScrape}>Scrape</Button>
            <Button variant="ghost" icon="refresh" onClick={() => { refetchToc(); reloadNovel(); }}>Refresh</Button>
          </div>
        </Step>

        {hasRaw && (
          <Step n={++step} title="Translate raws" desc="Reading already translates on demand; this pre-translates the whole raw source.">
            <div className="mc-controls">
              {(canAgyTranslate || canOpenAiTranslate) && (
                <BackendSelect value={translateBackend} onChange={setTranslateBackend} agy={canAgyTranslate} openai={canOpenAiTranslate} />
              )}
              <Button variant="ghost" icon="globe" onClick={doTranslate}>Translate raw chapters</Button>
              {novel.codex_enabled && <Button variant="ghost" icon="merge" onClick={doSeedGlossary}>Seed glossary from codex</Button>}
            </div>
          </Step>
        )}

        <Step n={++step} last title={novel.codex_enabled ? "Extend the Codex" : "Build the Codex"}
              desc="Builds the spoiler-safe knowledge base from scraped chapters. Leave both bounds blank for every available chapter; completed chapters are skipped.">
          <div className="mc-controls">
            {(canAgyCodex || canOpenAiCodex) && (
              <BackendSelect value={codexBackend} onChange={setCodexBackend} agy={canAgyCodex} openai={canOpenAiCodex} />
            )}
            <label className="field mc-num">
              <span>From chapter</span>
              <input type="number" step="any" value={codexFromChapter}
                     onChange={e => setCodexFromChapter(e.target.value)}
                     placeholder={novel.min_chapter != null ? String(novel.min_chapter) : "first"} />
            </label>
            <label className="field mc-num">
              <span>Through chapter</span>
              <input type="number" step="any" value={codexToChapter}
                     onChange={e => setCodexToChapter(e.target.value)} placeholder="latest" />
            </label>
            <Button variant="ghost" icon="brain" onClick={buildCodex}>
              {novel.codex_enabled ? "Extend codex" : "Build codex"}
            </Button>
          </div>
        </Step>
      </div>

      {pendingCost && (
        <CostConfirmDialog
          novelId={novelId} action={pendingCost.action} params={pendingCost.params}
          title={pendingCost.title} actionLabel={pendingCost.actionLabel}
          onCancel={() => setPendingCost(null)}
          onConfirm={async () => { await pendingCost.run(); setPendingCost(null); }} />
      )}
    </ManageCard>
  );
}

/* ── Sharing: visibility, reader edits, tags ── */
const VIS_CHOICES = {
  private: { label: "Private", icon: "lock", desc: "Only you — and admins — can open it." },
  public: { label: "Public", icon: "users", desc: "Any signed-in reader can find it and add it." },
  global: { label: "Global", icon: "globe", desc: "Part of the shared library, curated by admins." },
};

export function SharingCard({ novel, novelId, reloadNovel }) {
  const { user } = useAuth();
  const { toast } = useToast();
  const [busyVis, setBusyVis] = useState(false);
  const [tagBusy, setTagBusy] = useState(false);

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

  const isAdmin = !!(user && user.role === "admin");
  const visOptions = isAdmin ? ["private", "public", "global"]
    : (novel.visibility === "global" ? ["global"] : ["private", "public"]);

  return (
    <ManageCard icon="globe" title="Sharing" className="mc-sharing"
      sub="Who can read this book, and how readers' translation edits reach it.">
      <ChoiceCards legend="Visibility" value={novel.visibility || "private"} busy={busyVis}
        onChange={changeVisibility}
        options={visOptions.map(v => ({ value: v, ...VIS_CHOICES[v] }))}
        note={!isAdmin && novel.visibility === "global" ? "Only an admin can move a book out of the shared library." : null} />
      <ChoiceCards legend="Reader edits" value={novel.contribution_policy || "manual"} busy={busyVis}
        onChange={changePolicy}
        options={[
          { value: "manual", label: "Review edits", icon: "merge", desc: "Offered edits wait in your inbox." },
          { value: "auto", label: "Auto-merge clean edits", icon: "zap", desc: "Merge at once unless the text changed underneath." },
        ]} />
      <div className="mc-tags">
        <p className="choice-legend">Tags</p>
        <TagEditor tags={novel.status_tags || []} onToggle={onToggleTag} disabled={tagBusy} />
        {novel.translation_type && (
          <p className="mc-hint">Auto-detected: {TRANSLATION_TYPE_LABELS[novel.translation_type]}</p>
        )}
      </div>
    </ManageCard>
  );
}

/* ── Danger zone ── */
export function DangerCard({ novel, novelId }) {
  const navigate = useNavigate();
  const { toast } = useToast();
  const invalidate = useInvalidate();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

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

  return (
    <ManageCard icon="alert" title="Delete this novel" tone="danger" className="mc-danger">
      <div className="mc-danger-row">
        <p className="mc-danger-text">
          Deleting removes the novel, its chapters, codex, bookmarks and files for everyone. There is no undo.
        </p>
        <Button variant="ghost" className="is-danger" icon="trash" onClick={() => setConfirmDelete(true)}>Delete novel</Button>
      </div>
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
    </ManageCard>
  );
}
