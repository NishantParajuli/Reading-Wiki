/* ============================================================
   Novel → Overview: the book's front room. Under the hero: the latest
   chapters (mono numerals, display titles, unread dots), your bookmarks,
   and an aside with the book's tags and where its text comes from.
   ============================================================ */
import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { readingApi } from "../../modules/reading/api.js";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { NovelHeader } from "./NovelHeader.jsx";
import { fmtNum, languageName, useArrival, useBookmarksQuery } from "./NovelHeroParts.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, RelativeTime, Skeleton } from "../../components/ui.jsx";
import { ProvenanceBadges } from "../../components/ProvenanceBadges.jsx";
import { useToast } from "../../components/toast.jsx";
import { AnimatePresence, motion, springs } from "../../motion/index.js";
import { TagSuggestForm, TagChips } from "./tags.jsx";
import { useChaptersQuery } from "../../modules/reading/queries.js";
import { useTitle } from "../../lib/hooks.js";
import { fmtChapter } from "../../lib/utils.js";
import { VIS_LABELS } from "../../lib/constants.js";

const reveal = {
  initial: { height: 0, opacity: 0 },
  animate: { height: "auto", opacity: 1, transition: { height: springs.smooth, opacity: { duration: 0.3, delay: 0.08 } } },
  exit: { height: 0, opacity: 0, transition: { height: { duration: 0.28, ease: [0.55, 0, 1, 0.45] }, opacity: { duration: 0.16 } } },
};

function sourceHost(url) {
  try { return new URL(url).host.replace(/^www\./, ""); } catch { return url || ""; }
}

function LatestChapters({ novel, novelId }) {
  const { data: toc, isLoading, isError, refetch } = useChaptersQuery(novelId);
  const maxRead = (novel.progress && novel.progress.max_chapter_read) || 0;
  const current = novel.progress && novel.progress.last_chapter != null ? Number(novel.progress.last_chapter) : null;
  const latest = (toc || []).filter(c => !c.kind || c.kind === "chapter").slice(-5).reverse();

  if (isLoading) {
    return (
      <div className="card ov-list" aria-busy="true">
        {[0, 1, 2, 3, 4].map(i => (
          <div key={i} className="ov-row is-skeleton"><Skeleton variant="text" width={42} /><Skeleton variant="text" width={`${46 + ((i * 17) % 30)}%`} /></div>
        ))}
      </div>
    );
  }
  if (isError) {
    return (
      <div className="card ov-list ov-error" role="alert">
        <Icon name="alert" size={16} /> <span>The chapter list couldn't load.</span>
        <Button variant="ghost" size="sm" icon="refresh" onClick={() => refetch()}>Try again</Button>
      </div>
    );
  }
  return (
    <div className="card ov-list" data-spotlight>
      {latest.map((ch, i) => {
        const unread = maxRead > 0 && ch.number > maxRead;
        const here = current != null && Number(ch.number) === current;
        return (
          <Link key={ch.number} to={`/n/${novelId}/read/${ch.number}`} className={"ov-row rise" + (unread ? " is-new" : "")} style={{ "--i": i, "--rise-delay": "420ms" }}>
            <span className="ov-num">{fmtChapter(ch.number)}</span>
            <span className="ov-title">{ch.title || `Chapter ${fmtChapter(ch.number)}`}</span>
            {here && <span className="ov-here">Reading</span>}
            {unread && <span className="ov-dot" role="img" aria-label="Unread" title="Unread" />}
            <Icon name="arrowRight" size={15} className="ov-go" />
          </Link>
        );
      })}
    </div>
  );
}

function Bookmarks({ novelId }) {
  const { data: bookmarks } = useBookmarksQuery(novelId);
  const qc = useQueryClient();
  const { toast } = useToast();
  const key = ["bookmarks", Number(novelId)];
  const list = bookmarks || [];
  if (list.length === 0) return null;

  async function remove(b) {
    const before = qc.getQueryData(key);
    qc.setQueryData(key, (old) => (old || []).filter(x => x.id !== b.id));
    try {
      await readingApi.delBookmark(novelId, b.id);
      toast("Bookmark removed.", { tone: "ok" });
    } catch (e) {
      qc.setQueryData(key, before);
      toast(e.message || "Couldn't remove the bookmark.", { tone: "danger" });
    } finally {
      qc.invalidateQueries({ queryKey: key });
    }
  }

  return (
    <section className="ov-section" aria-labelledby="ov-bookmarks">
      <div className="ov-section-head">
        <h2 id="ov-bookmarks" className="section-title">Your bookmarks</h2>
        <span className="ov-count mono">{list.length}</span>
      </div>
      <div className="card ov-list ov-marks" data-spotlight>
        <AnimatePresence initial={false}>
          {[...list].sort((a, b) => a.chapter - b.chapter).map(b => (
            <motion.div key={b.id} className="ov-mark" {...reveal}>
              <Link to={`/n/${novelId}/read/${b.chapter}`} className="ov-mark-link">
                <span className="ov-ribbon" aria-hidden="true"><Icon name="bookmark" size={15} /></span>
                <span className="ov-num">Ch. {fmtChapter(b.chapter)}</span>
                <span className={"ov-note" + (b.note ? "" : " is-empty")}>{b.note || "Bookmarked"}</span>
              </Link>
              <button type="button" className="icon-btn plain ov-mark-x" aria-label="Remove bookmark" title="Remove bookmark" onClick={() => remove(b)}>
                <Icon name="x" size={14} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </section>
  );
}

/* Spoiler-safe counts from the Codex at the reader's own ceiling — numbers
   only, never names, and only once the stats match the current ceiling. */
function CodexCard({ novelId }) {
  const { stats, ceiling } = useNovel();
  const current = stats && stats.effective_ceiling != null && Number(stats.effective_ceiling) === Number(ceiling);
  const figures = current ? [
    ["Entries", stats.entities_revealed],
    ["Facts", stats.facts_known],
    ["Connections", stats.relationships_known],
  ].filter(([, v]) => v != null) : [];
  return (
    <section className="card ov-card ov-codex" aria-labelledby="ov-codex" data-spotlight>
      <div className="ov-card-head">
        <h2 id="ov-codex" className="ov-card-title"><Icon name="compass" size={15} /> Codex</h2>
        <Link className="linkish" to={`/n/${novelId}/codex`}>Open <Icon name="arrowRight" size={13} /></Link>
      </div>
      {figures.length > 0 ? (
        <dl className="ov-codex-figs">
          {figures.map(([label, value]) => (
            <div key={label}><dt>{label}</dt><dd>{fmtNum(value)}</dd></div>
          ))}
        </dl>
      ) : null}
      <p className="ov-codex-note">
        <Icon name="shield" size={13} />
        {current ? `Spoiler-safe up to Ch. ${fmtNum(stats.effective_ceiling)}.` : "Spoiler-safe: only what you've already read."}
      </p>
    </section>
  );
}

function TagsCard({ novel }) {
  const [suggesting, setSuggesting] = useState(false);
  const tags = novel.status_tags || [];
  return (
    <section className="card ov-card" aria-labelledby="ov-tags" data-spotlight>
      <div className="ov-card-head">
        <h2 id="ov-tags" className="ov-card-title"><Icon name="sparkles" size={15} /> Tags</h2>
        {novel.can_suggest_tags && !suggesting && (
          <Button variant="ghost" size="sm" icon="sparkles" onClick={() => setSuggesting(true)}>Suggest tags</Button>
        )}
      </div>
      <div className="ov-tags">
        <TagChips novel={novel} />
        {tags.length === 0 && <span className="muted ov-empty-line">No tags yet.</span>}
      </div>
      <AnimatePresence initial={false}>
        {suggesting && (
          <motion.div key="suggest" className="ov-reveal" {...reveal}>
            <TagSuggestForm novel={novel} current={tags} onClose={() => setSuggesting(false)} />
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

function SourcesCard({ novel }) {
  const sources = novel.sources || [];
  const lang = languageName(novel.original_language);
  return (
    <section className="card ov-card" aria-labelledby="ov-sources" data-spotlight>
      <div className="ov-card-head">
        <h2 id="ov-sources" className="ov-card-title"><Icon name="link" size={15} /> Sources</h2>
        <Chip tone="info">{VIS_LABELS[novel.visibility] || novel.visibility}</Chip>
      </div>
      {sources.length === 0 ? (
        <p className="muted ov-empty-line">{novel.can_edit ? "No sources yet — add one from Manage." : "Source details are kept by the owner."}</p>
      ) : (
        <ul className="ov-sources">
          {sources.map(s => (
            <li key={s.id} className="ov-source" title={s.start_url}>
              <span className="ov-source-mono" aria-hidden="true">{(s.label || s.adapter || "?").trim().charAt(0).toUpperCase()}</span>
              <span className="ov-source-text">
                <span className="ov-source-name">{s.label || s.adapter}{s.is_raw ? <em> · raw</em> : null}</span>
                <span className="ov-source-meta">
                  <span className="mono">{sourceHost(s.start_url)}</span>
                  {s.last_scraped_at && <> · <RelativeTime iso={s.last_scraped_at} prefix="updated " /></>}
                </span>
              </span>
              {s.language && <Chip className="mono">{s.language}</Chip>}
            </li>
          ))}
        </ul>
      )}
      <dl className="ov-details">
        {lang && <div><dt>Original language</dt><dd>{lang}</dd></div>}
        <div><dt>Chapters</dt><dd className="mono">{fmtNum(novel.chapter_count || 0)}</dd></div>
      </dl>
      <ProvenanceBadges provenance={novel.provenance} className="ov-prov" />
    </section>
  );
}

export function Overview() {
  const { novel, novelId } = useNovel();
  const navigate = useNavigate();
  const arrival = useArrival();
  useTitle(novel.title);

  const empty = (novel.chapter_count || 0) === 0;
  return (
    <div className={"page nv-page ov-page" + (arrival === "direct" ? " page-enter" : "")}>
      <NovelHeader />

      <div className="ov-grid">
        <div className="ov-main">
          {empty ? (
            <EmptyState icon="book" title="No chapters yet"
              body={novel.can_edit ? "Scrape the source from the Manage tab to fetch chapters." : "The owner hasn't added chapters yet."}
              primaryAction={novel.can_edit ? <Button variant="primary" icon="sliders" onClick={() => navigate(`/n/${novelId}/manage`)}>Open Manage</Button> : null} />
          ) : (
            <>
              <section className="ov-section" aria-labelledby="ov-latest">
                <div className="ov-section-head">
                  <h2 id="ov-latest" className="section-title">Latest chapters</h2>
                  <Link className="linkish" to={`/n/${novelId}/chapters`}>
                    All {fmtNum(novel.chapter_count)} <Icon name="arrowRight" size={13} />
                  </Link>
                </div>
                <LatestChapters novel={novel} novelId={novelId} />
              </section>
              <Bookmarks novelId={novelId} />
            </>
          )}
        </div>
        <aside className="ov-aside" aria-label="About this book">
          {novel.codex_enabled && <CodexCard novelId={novelId} />}
          <TagsCard novel={novel} />
          <SourcesCard novel={novel} />
        </aside>
      </div>
    </div>
  );
}
