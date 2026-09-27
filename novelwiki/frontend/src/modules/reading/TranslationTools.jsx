import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { readingApi } from "./api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, SegmentedControl } from "../../components/ui.jsx";
import { DiffView } from "../../lib/diff.jsx";
import { useFocusTrap } from "../../lib/hooks.js";
import { fmtChapter } from "../../lib/utils.js";
import "./TranslationTools.css";

function DiscardPrompt({ action, onCancel, onConfirm }) {
  const ref = useFocusTrap(true);
  const titleId = useId();
  return (
    <div className="translation-confirm-scrim" onClick={event => { if (event.target === event.currentTarget) onCancel(); }}>
      <section ref={ref} className="translation-confirm" role="alertdialog" aria-modal="true" aria-labelledby={titleId}>
        <h3 id={titleId}>{action.title}</h3>
        <p>{action.body}</p>
        <div className="translation-confirm-actions">
          <Button variant="secondary" onClick={onCancel}>Keep editing</Button>
          <Button variant="danger" onClick={onConfirm}>{action.label}</Button>
        </div>
      </section>
    </div>
  );
}

export function TranslationTools({ novelId, ch, onClose, onChanged }) {
  const [draft, setDraft] = useState(ch.content || "");
  const [operation, setOperation] = useState(null);
  const [message, setMessage] = useState(null);
  const [pendingAction, setPendingAction] = useState(null);
  const [view, setView] = useState("edit");
  const [showComparison, setShowComparison] = useState(false);
  const trapRef = useFocusTrap(true);
  const inFlight = useRef(false);
  const titleId = useId();
  const descriptionId = useId();
  const busy = operation != null;
  const dirty = draft !== (ch.content || "");
  const canEditBase = !!ch.can_edit_base;
  const hasOverlay = !!ch.overlay;
  const conflict = !!ch.overlay_conflict;
  const isOwner = !!ch.is_owner;
  const paragraphs = useMemo(() => draft.trim() ? draft.trim().split(/\n\s*\n/) : [], [draft]);
  const wordCount = useMemo(() => draft.trim() ? draft.trim().split(/\s+/u).length : 0, [draft]);
  const saveLabel = canEditBase ? "Save for everyone" : conflict ? "Save merged version" : "Save my version";
  const canSave = !busy && !!draft.trim() && (dirty || conflict);

  async function run(label, action, { close = true } = {}) {
    if (inFlight.current) return;
    inFlight.current = true;
    setOperation(label); setMessage(null);
    try {
      const result = await action();
      if (close || result?.status === "auto_merged") onChanged();
      else setMessage({ tone: "success", text: "Your saved version was sent to the owner for review." });
    } catch (error) {
      setMessage({ tone: "error", text: error.message || "The change couldn't be saved. Your draft is still here; please try again." });
    } finally {
      inFlight.current = false;
      setOperation(null);
    }
  }

  function save() {
    if (!canSave) return;
    return run(canEditBase ? "Saving the shared chapter…" : "Saving your translation…", () => (
      canEditBase ? readingApi.editBaseContent(novelId, ch.number, draft)
        : conflict ? readingApi.resolveOverlay(novelId, ch.number, "merge", draft)
          : readingApi.saveOverlay(novelId, ch.number, draft)
    ));
  }

  const requestClose = useCallback(() => {
    if (inFlight.current) return;
    if (!dirty) { onClose(); return; }
    setPendingAction({
      title: "Discard your unsaved changes?",
      body: "Your changes haven't been saved. Keep editing to finish your translation, or discard them and return to reading.",
      label: "Discard changes", run: onClose,
    });
  }, [dirty, onClose]);

  function replaceDraft(label, action, { always = false, body } = {}) {
    const perform = () => run(label, action);
    if (!dirty && !always) { perform(); return; }
    setPendingAction({ title: "Replace your translation?", body: body || "This replaces your unsaved changes. Your current draft will be discarded.", label: "Replace translation", run: perform });
  }

  useEffect(() => {
    const onKey = event => {
      if (event.key === "Escape") {
        event.preventDefault(); event.stopImmediatePropagation();
        if (pendingAction) setPendingAction(null);
        else requestClose();
      } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault(); event.stopImmediatePropagation();
        if (!pendingAction) save();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  });

  useEffect(() => {
    if (!dirty && !busy) return;
    const warnBeforeLeaving = event => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warnBeforeLeaving);
    return () => window.removeEventListener("beforeunload", warnBeforeLeaving);
  }, [dirty, busy]);

  return createPortal(
    <div className="translation-editor-scrim" onClick={event => {
      event.stopPropagation();
      if (event.target === event.currentTarget) requestClose();
    }}>
      <section ref={trapRef} className="translation-editor" role="dialog" aria-modal="true"
               aria-labelledby={titleId} aria-describedby={descriptionId} aria-busy={busy}>
        <header className="translation-editor-head">
          <div>
            <h2 id={titleId}>Edit chapter translation</h2>
            <p className="translation-chapter-name">{ch.title || `Chapter ${fmtChapter(ch.number)}`}</p>
          </div>
          <button type="button" className="icon-btn plain" aria-label="Close translation editor" disabled={busy} onClick={requestClose}>
            <Icon name="x" size={20} />
          </button>
        </header>
        <div className="translation-editor-context">
          <p id={descriptionId}>{canEditBase ? "Shared chapter. Saving updates the text for every reader." : "Your personal version. The shared chapter stays unchanged."}</p>
          <span className="translation-draft-state">{dirty ? "Unsaved changes" : "No unsaved changes"}</span>
        </div>
        {conflict && <div className="translation-conflict">
          <div>
            <b>The shared translation has changed.</b>
            <p>Compare the versions, then save your merged text or choose which version to keep.</p>
          </div>
          <div className="translation-conflict-actions">
            {ch.base_content && <Button variant="ghost" size="sm" aria-expanded={showComparison} onClick={() => setShowComparison(value => !value)}>{showComparison ? "Hide comparison" : "Compare versions"}</Button>}
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => replaceDraft("Keeping your saved version…", () => readingApi.resolveOverlay(novelId, ch.number, "mine"))}>Keep saved version</Button>
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => replaceDraft("Using the latest shared version…", () => readingApi.resolveOverlay(novelId, ch.number, "base"))}>Use latest shared version</Button>
          </div>
        </div>}
        <div className="translation-mobile-views">
          <SegmentedControl value={view} onChange={setView} ariaLabel="Translation view" options={[{ value: "edit", label: "Edit" }, { value: "preview", label: "Preview" }]} />
        </div>
        <div className={`translation-editor-body view-${view}`}>
          {showComparison && conflict && ch.base_content ? <section className="translation-comparison" aria-label="Translation comparison">
            <DiffView oldText={ch.base_content} newText={draft} oldLabel="Latest shared version" newLabel="Your draft" />
          </section> : null}
          <div className="translation-panes">
            <section className="translation-edit-pane">
              <div className="translation-pane-head"><label htmlFor={`${titleId}-draft`}>Chapter text</label><span>{wordCount.toLocaleString()} words</span></div>
              <textarea id={`${titleId}-draft`} className="translation-textarea" value={draft} disabled={busy}
                        aria-label="Chapter translation" onChange={event => { setDraft(event.target.value); setMessage(null); }}
                        placeholder="Write your chapter translation here…" spellCheck />
            </section>
            <section className="translation-preview-pane" aria-label="Reading preview">
              <div className="translation-pane-head"><h3>Reading preview</h3><span>Updates as you type</span></div>
              <div className="translation-preview" tabIndex={0}>
                {paragraphs.length ? paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>) : <p className="muted">Your translation will appear here as you write.</p>}
              </div>
            </section>
          </div>
        </div>
        <footer className="translation-editor-foot">
          {(operation || message) && <p className={`translation-feedback ${message?.tone || ""}`} role={message?.tone === "error" ? "alert" : "status"}>
            {operation || message.text}{operation?.startsWith("Translating") ? " This can take a few minutes." : ""}
          </p>}
          <div className="translation-footer-actions">
            <div className="translation-secondary-actions">
              {ch.has_original && <Button variant="ghost" size="sm" disabled={busy} onClick={() => replaceDraft("Translating your personal copy…", () => readingApi.selfTranslate(novelId, ch.number))} title="Generate a new personal translation using your quota">Re-translate for me</Button>}
              {hasOverlay && !canEditBase && !isOwner && <Button variant="ghost" size="sm" disabled={busy || dirty || conflict} onClick={() => run("Sending to the owner…", () => readingApi.contribute(novelId, ch.number), { close: false })} title={dirty || conflict ? "Save your changes and resolve the shared update before offering your version." : "Offer your saved version to the owner"}>Offer to owner</Button>}
              {hasOverlay && <Button variant="ghost" size="sm" className="is-danger" disabled={busy} onClick={() => replaceDraft("Restoring the shared version…", () => readingApi.deleteOverlay(novelId, ch.number), { always: true, body: "Your personal translation will be deleted and the shared version restored. Unsaved changes will also be discarded." })}>Revert to shared version</Button>}
            </div>
            <div className="translation-save-actions">
              <Button variant="secondary" disabled={busy} onClick={requestClose}>Cancel</Button>
              <Button variant="primary" disabled={!canSave} loading={busy} onClick={save}>{busy ? "Working…" : saveLabel}</Button>
            </div>
          </div>
          <p className="translation-save-hint">{canEditBase ? "Shared edits affect everyone reading this chapter." : "Only you see your saved version unless you offer it to the owner."} <span>Ctrl / ⌘ S to save</span></p>
        </footer>
      </section>
      {pendingAction && <DiscardPrompt action={pendingAction} onCancel={() => setPendingAction(null)} onConfirm={() => { const action = pendingAction; setPendingAction(null); action.run(); }} />}
    </div>, document.body,
  );
}
