/* ============================================================
   Novel hero + URL-synced tabs (§6.6) — shared by Overview / Chapters /
   Manage. Reader-facing actions up top; operator tooling lives in Manage.
   ============================================================ */
import React, { useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { catalogApi } from "../../modules/catalog/api.js";
import { readingApi } from "../../modules/reading/api.js";
import { useAuth } from "../../App.jsx";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, Cover, ProgressBar } from "../../components/ui.jsx";
import { Popover, MenuItem, ConfirmDialog } from "../../components/overlay.jsx";
import { ProvenanceBadges } from "../../components/ProvenanceBadges.jsx";
import { useToast } from "../../components/toast.jsx";
import { NarrateBookControl } from "../../features/narrate.jsx";
import { ShelfControl } from "../../features/tags.jsx";
import { useAudioCoverageQuery } from "../../modules/narration/queries.js";
import { useInvalidate } from "../../shared/query/useInvalidate.js";
import { TRANSLATION_TYPE_LABELS, VIS_LABELS } from "../../lib/constants.js";
import { fmtChapter, relativeTime } from "../../lib/utils.js";

function NovelKebab({ novel, canEdit, onDelete }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { toast } = useToast();
  const qc = useQueryClient();

  async function removeFromLibrary() {
    setOpen(false);
    try {
      await catalogApi.removeFromLibrary(novel.id);
      qc.invalidateQueries({ queryKey: ["novels"] });
      toast(`Removed “${novel.title}” from your library.`, { tone: "ok" });
      navigate("/library");
    } catch (e) {
      toast(e.message || "Couldn't remove it.", { tone: "danger" });
    }
  }

  return (
    <Popover open={open} onClose={() => setOpen(false)} trigger={
      <button className="icon-btn" aria-label="More actions" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <Icon name="more" size={17} sw={2.4} />
      </button>
    }>
      {canEdit && <MenuItem icon="edit" onClick={() => { setOpen(false); navigate(`/n/${novel.id}/manage`); }}>Edit novel</MenuItem>}
      <MenuItem icon="link" onClick={() => {
        setOpen(false);
        navigator.clipboard.writeText(window.location.origin + `/n/${novel.id}`)
          .then(() => toast("Link copied.", { tone: "ok" }))
          .catch(() => toast("Couldn't copy the link.", { tone: "danger" }));
      }}>Copy link</MenuItem>
      <MenuItem icon="x" onClick={removeFromLibrary}>Remove from library</MenuItem>
      {canEdit && (
        <>
          <div className="menu-sep" />
          <MenuItem icon="trash" danger onClick={() => { setOpen(false); onDelete(); }}>Delete novel…</MenuItem>
        </>
      )}
    </Popover>
  );
}

export function NovelHeader() {
  const { novel, novelId, reloadNovel } = useNovel();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const invalidate = useInvalidate();
  const [descOpen, setDescOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [inboxCount, setInboxCount] = useState(0);
  const { data: audioCoverage } = useAudioCoverageQuery(novelId);

  const canEdit = !!novel.can_edit;
  const progress = novel.progress || {};
  const started = progress.last_chapter != null;
  const startAt = started ? progress.last_chapter : (novel.min_chapter || 1);
  const hasChapters = (novel.chapter_count || 0) > 0;
  const hasAudio = !!(audioCoverage && audioCoverage.chapters && audioCoverage.chapters.length > 0);
  const maxRead = progress.max_chapter_read || 0;
  const newCount = novel.max_chapter != null && maxRead > 0 ? Math.max(0, Math.round(novel.max_chapter - maxRead)) : 0;
  const pct = novel.max_chapter ? Math.round(Math.min(100, (maxRead / novel.max_chapter) * 100)) : 0;
  const tt = novel.translation_type ? TRANSLATION_TYPE_LABELS[novel.translation_type] : null;

  // Pending-inbox badge on the Manage tab (owner/admin only).
  useEffect(() => {
    if (!canEdit) return;
    let cancel = false;
    Promise.all([
      readingApi.contributions(novelId).catch(() => []),
      catalogApi.tagSuggestions(novelId).catch(() => []),
    ]).then(([c, t]) => { if (!cancel) setInboxCount((c || []).length + (t || []).length); });
    return () => { cancel = true; };
  }, [novelId, canEdit]);

  async function doDelete() {
    setDeleting(true);
    try {
      await catalogApi.deleteNovel(novelId);
      invalidate(["novels"], ["home"]);
      toast(`Deleted “${novel.title}”.`, { tone: "ok" });
      navigate("/library");
    } catch (e) {
      toast("Delete failed: " + (e.message || "error"), { tone: "danger" });
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  return (
    <>
      <div className="novel-hero">
        {novel.cover_url && <div className="novel-hero-backdrop" style={{ backgroundImage: `url(${JSON.stringify(novel.cover_url)})` }} aria-hidden />}
        <Cover src={novel.cover_url} title={novel.title} />
        <div className="novel-hero-body">
          <h1 className="novel-hero-title">{novel.title}</h1>
          {novel.author && <p className="novel-hero-author">{novel.author}</p>}
          <ProvenanceBadges provenance={novel.provenance} />
          <div className="novel-hero-chips">
            <Chip className="mono">{novel.chapter_count} chapters</Chip>
            {novel.max_chapter != null && <Chip className="mono">ch. {fmtChapter(novel.min_chapter)}–{fmtChapter(novel.max_chapter)}</Chip>}
            {novel.original_language && novel.original_language !== "en" && <Chip>{novel.original_language}</Chip>}
            {tt && <Chip tone="accent">{tt}</Chip>}
            {novel.visibility !== "private" && <Chip tone="info">{VIS_LABELS[novel.visibility]}</Chip>}
          </div>
          {novel.description && (
            <>
              <p className={"novel-desc" + (descOpen ? "" : " clamped")}>{novel.description}</p>
              {novel.description.length > 180 && (
                <button className="linkish" onClick={() => setDescOpen(o => !o)}>{descOpen ? "Less" : "More"}</button>
              )}
            </>
          )}
          <div className="novel-hero-actions">
            {hasChapters && (
              <Button variant="primary" size="lg" icon="book" onClick={() => navigate(`/n/${novelId}/read/${startAt}`)}>
                {started ? `Continue · Ch. ${fmtChapter(startAt)}` : "Start reading"}
              </Button>
            )}
            {hasChapters && hasAudio && (
              <Button variant="ghost" icon="headphones" onClick={() => navigate(`/n/${novelId}/read/${startAt}?listen=1`)}>Listen</Button>
            )}
            {novel.codex_enabled && (
              <Button variant="ghost" icon="compass" onClick={() => navigate(`/n/${novelId}/codex`)}>Codex</Button>
            )}
            {hasChapters && <NarrateBookControl novelId={novelId} novel={novel} user={user} audioCoverage={audioCoverage} onChange={() => invalidate(["audio-coverage", novelId])} />}
            <ShelfControl novel={novel} reloadNovel={reloadNovel} />
            <NovelKebab novel={novel} canEdit={canEdit} onDelete={() => setConfirmDelete(true)} />
          </div>
          {started && (
            <div className="novel-progress-line">
              <ProgressBar size="xs" value={pct} label="Reading progress" />
              <span>{pct}% read{newCount > 0 ? ` · ${newCount} new since you last read` : ""}</span>
            </div>
          )}
        </div>
      </div>

      <nav className="novel-tabs" aria-label="Novel sections">
        <NavLink to={`/n/${novelId}`} end className={({ isActive }) => "novel-tab" + (isActive ? " active" : "")}>
          <Icon name="book" size={15} /> Overview
        </NavLink>
        <NavLink to={`/n/${novelId}/chapters`} className={({ isActive }) => "novel-tab" + (isActive ? " active" : "")}>
          <Icon name="list" size={15} /> Chapters
        </NavLink>
        {canEdit && (
          <NavLink to={`/n/${novelId}/manage`} className={({ isActive }) => "novel-tab" + (isActive ? " active" : "")}>
            <Icon name="sliders" size={15} /> Manage
            {inboxCount > 0 && <span className="tab-count">{inboxCount}</span>}
          </NavLink>
        )}
      </nav>

      {confirmDelete && (
        <ConfirmDialog
          title={`Delete “${novel.title}”?`}
          requireText={novel.title}
          confirmLabel="Delete permanently"
          busy={deleting}
          onCancel={() => setConfirmDelete(false)}
          onConfirm={doDelete}
          body={
            <div>
              <p className="muted" style={{ fontSize: "var(--text-sm)", lineHeight: 1.55, margin: "0 0 8px" }}>
                This permanently removes the novel and everything tied to it — there's no undo.
              </p>
              <ul className="muted" style={{ fontSize: "var(--text-sm)", lineHeight: 1.6, margin: 0, paddingLeft: 18 }}>
                <li>{novel.chapter_count || 0} chapters (text + translations)</li>
                <li>the codex, bookmarks, glossary and reading progress</li>
                <li>imported files, covers and illustrations on disk</li>
              </ul>
            </div>
          }
        />
      )}
    </>
  );
}
