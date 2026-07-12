/* Novel → Overview tab: latest chapters, your bookmarks, tags, about. */
import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { readingApi } from "../../modules/reading/api.js";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { NovelHeader } from "./NovelHeader.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, Loading } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { TagSuggestForm, TagChips } from "./tags.jsx";
import { useChaptersQuery } from "../../modules/reading/queries.js";
import { useTitle } from "../../lib/hooks.js";
import { fmtChapter } from "../../lib/utils.js";
import { VIS_LABELS } from "../../lib/constants.js";

export function Overview() {
  const { novel, novelId } = useNovel();
  const { data: toc, isLoading: tocLoading } = useChaptersQuery(novelId);
  const [bookmarks, setBookmarks] = useState([]);
  const [suggesting, setSuggesting] = useState(false);
  const navigate = useNavigate();
  const { toast } = useToast();
  useTitle(novel.title);

  const loadBookmarks = () => readingApi.bookmarks(novelId).then(setBookmarks).catch(() => setBookmarks([]));
  useEffect(() => { loadBookmarks(); }, [novelId]); // eslint-disable-line react-hooks/exhaustive-deps

  const maxRead = (novel.progress && novel.progress.max_chapter_read) || 0;
  const latest = (toc || []).filter(c => !c.kind || c.kind === "chapter").slice(-5).reverse();

  return (
    <div className="page page-enter">
      <NovelHeader />

      {(novel.chapter_count || 0) === 0 ? (
        <EmptyState icon="book" title="No chapters yet"
          body={novel.can_edit ? "Scrape the source from the Manage tab to fetch chapters." : "The owner hasn't added chapters yet."}
          primaryAction={novel.can_edit ? <Button variant="primary" icon="sliders" onClick={() => navigate(`/n/${novelId}/manage`)}>Open Manage</Button> : null} />
      ) : (
        <>
          <section style={{ marginBottom: 26 }}>
            <div className="row" style={{ alignItems: "baseline", marginBottom: 10 }}>
              <h2 className="section-title" style={{ margin: 0 }}>Latest chapters</h2>
              <Link className="linkish" style={{ marginLeft: "auto" }} to={`/n/${novelId}/chapters`}>
                All {novel.chapter_count} <Icon name="arrowRight" size={13} />
              </Link>
            </div>
            {tocLoading ? <Loading /> : (
              <div className="card toc">
                {latest.map(ch => (
                  <button key={ch.number} className="toc-row" onClick={() => navigate(`/n/${novelId}/read/${ch.number}`)}>
                    <span className="toc-num">{fmtChapter(ch.number)}</span>
                    <span className="toc-title">{ch.title || `Chapter ${fmtChapter(ch.number)}`}</span>
                    {maxRead > 0 && ch.number > maxRead && <span className="toc-new-dot" title="Unread" />}
                    <Icon name="arrowRight" size={14} className="muted" />
                  </button>
                ))}
              </div>
            )}
          </section>

          {bookmarks.length > 0 && (
            <section style={{ marginBottom: 26 }}>
              <h2 className="section-title">Your bookmarks</h2>
              <div className="card toc">
                {bookmarks.map(b => (
                  <div key={b.id} className="toc-row" style={{ cursor: "default" }}>
                    <button className="row grow" style={{ border: "none", background: "none", padding: 0, textAlign: "left", minWidth: 0 }}
                            onClick={() => navigate(`/n/${novelId}/read/${b.chapter}`)}>
                      <Icon name="bookmark" size={14} className="muted" />
                      <span className="toc-num">Ch. {fmtChapter(b.chapter)}</span>
                      <span className="toc-title">{b.note || "Bookmarked"}</span>
                    </button>
                    <button className="icon-btn plain" aria-label="Remove bookmark"
                            onClick={async () => { await readingApi.delBookmark(novelId, b.id); loadBookmarks(); toast("Bookmark removed.", { tone: "ok" }); }}>
                      <Icon name="x" size={14} />
                    </button>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      <section style={{ marginBottom: 26 }}>
        <h2 className="section-title">Tags</h2>
        <div className="row wrap" style={{ gap: 7 }}>
          <TagChips novel={novel} />
          {(novel.status_tags || []).length === 0 && <span className="muted" style={{ fontSize: "var(--text-sm)" }}>No tags yet.</span>}
          {novel.can_suggest_tags && !suggesting && (
            <Button variant="ghost" size="sm" icon="sparkles" onClick={() => setSuggesting(true)}>Suggest tags</Button>
          )}
        </div>
        {suggesting && <TagSuggestForm novel={novel} current={novel.status_tags || []} onClose={() => setSuggesting(false)} />}
      </section>

      <section>
        <h2 className="section-title">About</h2>
        <div className="card pad-lg" style={{ maxWidth: 760 }}>
          {novel.description
            ? <p style={{ margin: 0, lineHeight: 1.65, color: "var(--ink-2)", whiteSpace: "pre-line" }}>{novel.description}</p>
            : <p className="muted" style={{ margin: 0 }}>No description.</p>}
          <div className="row wrap" style={{ gap: 6, marginTop: 14 }}>
            {(novel.sources || []).map(s => (
              <Chip key={s.id} title={s.start_url}>{s.label || s.adapter}{s.is_raw ? " · raw" : ""}</Chip>
            ))}
            <Chip tone="info">{VIS_LABELS[novel.visibility] || novel.visibility}</Chip>
          </div>
        </div>
      </section>
    </div>
  );
}
