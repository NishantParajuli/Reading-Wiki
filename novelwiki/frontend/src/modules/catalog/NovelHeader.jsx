/* ============================================================
   Novel hero — the book's own world, shared by Overview (full) and
   Chapters / Manage (compact). Section navigation lives in the shell's
   novel capsule; this is the book itself:
     · a floating jacket (tilt + glare) glowing in the cover's colours, with
       a still reflection on the water beneath it. It carries the
       `hero-cover` view-transition name, so a clicked card's jacket flies
       straight into it — and from the full hero into the compact one.
     · display title (word-by-word rise), italic author, an editorial spec
       strip, the synopsis with a height-tide expand
     · Continue / Start reading with a progress ring; glass secondary pills
     · the tideline: reading progress across the whole book
   Arrival choreography depends on how we got here (see useArrival).
   ============================================================ */
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

import { catalogApi } from "./api.js";
import { useAuth } from "../../App.jsx";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Cover, ProgressRing } from "../../components/ui.jsx";
import { ConfirmDialog } from "../../components/overlay.jsx";
import { useToast } from "../../components/toast.jsx";
import { TextReveal } from "../../motion/TextReveal.jsx";
import { NarrateBookControl } from "../narration/index.js";
import { ShelfControl } from "./tags.jsx";
import {
  ExpandableText, HeroFacts, NovelKebab, Tideline,
  fmtNum, tagLine, titleScale, useArrival, useBookmarksQuery,
} from "./NovelHeroParts.jsx";
import { useAudioCoverageQuery } from "../../modules/narration/queries.js";
import { useChaptersQuery } from "../../modules/reading/queries.js";
import { useInvalidate } from "../../shared/query/useInvalidate.js";

export function NovelHeader({ compact = false }) {
  const { novel, novelId, reloadNovel } = useNovel();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const invalidate = useInvalidate();
  const arrival = useArrival();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const { data: audioCoverage } = useAudioCoverageQuery(novelId);
  const { data: toc } = useChaptersQuery(novelId);
  const { data: bookmarks } = useBookmarksQuery(novelId);

  const canEdit = !!novel.can_edit;
  const progress = novel.progress || {};
  const started = progress.last_chapter != null;
  const startAt = started ? progress.last_chapter : (novel.min_chapter || 1);
  const hasChapters = (novel.chapter_count || 0) > 0;
  const hasAudio = !!(audioCoverage && audioCoverage.chapters && audioCoverage.chapters.length > 0);
  const maxRead = progress.max_chapter_read || 0;
  const pct = novel.max_chapter ? Math.round(Math.min(100, (maxRead / novel.max_chapter) * 100)) : 0;
  const startTitle = (toc || []).find(c => Number(c.number) === Number(startAt));
  const eyebrow = tagLine(novel);

  // Tab switches inside the same book keep the hero still (the view
  // transition morphs it); every other arrival gets the full choreography.
  const animate = arrival !== "novel-tab";
  const coverIn = arrival === "direct";
  const rise = (i) => (animate ? { className: "rise", style: { "--i": i } } : { className: "", style: undefined });
  const cls = (base, i) => { const r = rise(i); return { className: [base, r.className].filter(Boolean).join(" "), style: r.style }; };

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

  const TitleTag = animate
    ? <TextReveal as="h1" className={`nh-title ${titleScale(novel.title)}`} text={novel.title} delay={compact ? 60 : 160} step={compact ? 45 : 75} />
    : <h1 className={`nh-title ${titleScale(novel.title)}`}>{novel.title}</h1>;

  return (
    <header className={"nh" + (compact ? " nh--compact" : " nh--full")} data-arrival={arrival}>
      <div className="nh-stage">
        <div className={"nh-art" + (coverIn ? " is-entering" : "")}>
          <span className="nh-glow" aria-hidden="true" />
          <div className="nh-cover-float">
            <Cover src={novel.cover_url} title={novel.title} author={novel.author} tilt={compact ? 7 : 9} vtName="hero-cover" className="nh-cover" />
          </div>
          {!compact && (
            <div className="nh-reflection" aria-hidden="true">
              <Cover src={novel.cover_url} title={novel.title} author={novel.author} />
            </div>
          )}
        </div>

        <div className="nh-body">
          {!compact && eyebrow.length > 0 && (
            <p {...cls("nh-eyebrow", 0)}>
              {eyebrow.map((t, i) => <span key={t}>{i > 0 && <i aria-hidden="true" />}{t}</span>)}
            </p>
          )}
          {/* First in the DOM so Tab follows the eye: the shelf and ⋯ sit top-right
              on wide screens (CSS places them); phones show them last and let
              reading-flow keep Tab in visual order where supported. */}
          <div {...cls("nh-utility", compact ? 7 : 1)}>
            <ShelfControl novel={novel} reloadNovel={reloadNovel} />
            <NovelKebab novel={novel} canEdit={canEdit} onDelete={() => setConfirmDelete(true)} />
          </div>
          {TitleTag}
          {novel.author && <p {...cls("nh-author", 2)}><span className="nh-by">by</span> {novel.author}</p>}

          <HeroFacts novel={novel} animate={animate} compact={compact} baseIndex={3} />

          {!compact && novel.description && (
            <ExpandableText text={novel.description} lines={4} {...cls("", 8)} />
          )}

          <div {...cls("nh-actions", compact ? 6 : 9)}>
            {hasChapters && (
              <Button variant="primary" size={compact ? undefined : "lg"} className="nh-cta" iconRight="arrowRight"
                      onClick={() => navigate(`/n/${novelId}/read/${startAt}`)}>
                <span className="nh-cta-ring" aria-hidden="true">
                  {started
                    ? <ProgressRing value={pct} size={compact ? 28 : 34} stroke={2.4}>{compact ? null : `${pct}%`}</ProgressRing>
                    : <Icon name="bookOpen" size={compact ? 15 : 17} />}
                </span>
                <span className="nh-cta-text">
                  <span className="nh-cta-label">{started ? `Continue · Ch. ${fmtNum(startAt)}` : "Start reading"}</span>
                  {!compact && startTitle && startTitle.title && <span className="nh-cta-sub">{startTitle.title}</span>}
                </span>
              </Button>
            )}
            {hasChapters && hasAudio && (
              <Button variant="ghost" icon="headphones" size={compact ? "sm" : undefined} className="nh-pill"
                      onClick={() => navigate(`/n/${novelId}/read/${startAt}?listen=1`)}><span className="nh-pill-text">Listen</span></Button>
            )}
            {novel.codex_enabled && (
              <Button variant="ghost" icon="compass" size={compact ? "sm" : undefined} className="nh-pill"
                      onClick={() => navigate(`/n/${novelId}/codex`)}><span className="nh-pill-text">Codex</span></Button>
            )}
            {hasChapters && (
              <NarrateBookControl novelId={novelId} novel={novel} user={user} audioCoverage={audioCoverage}
                                  compact={compact} onChange={() => invalidate(["audio-coverage", novelId])} />
            )}
          </div>

          {compact && hasChapters && (
            <div {...cls("nh-tide", 8)}>
              <Tideline novel={novel} bookmarks={bookmarks} toc={toc} compact animate={animate} />
            </div>
          )}
        </div>
      </div>

      {!compact && hasChapters && (
        <div {...cls("nh-tide", 10)}>
          <Tideline novel={novel} bookmarks={bookmarks} toc={toc} animate={animate} />
        </div>
      )}

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
    </header>
  );
}
