/* ============================================================
   Reader v2 (§6.7) — calm chrome (4 targets), top progress rail, auto-hiding
   bars, ch-based measure, sepia + true-black night tones, end-of-chapter card,
   translation tools, TOC drawer, audio player with
   ±15s skips. Progress (chapter + scroll fraction) still lives server-side.
   ============================================================ */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { identityApi } from "../../modules/identity/api.js";
import { readingApi } from "../../modules/reading/api.js";
import { useAuth } from "../../App.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, Loading } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { Drawer } from "../../components/overlay.jsx";
import { ProvenanceBadges } from "../../components/ProvenanceBadges.jsx";
import { VolumeTOC } from "./toc.jsx";
import { NarratedProse } from "./NarratedProse.jsx";
import { readTtsPrefs } from "../narration/index.js";
import { useNovelQuery } from "../../modules/catalog/queries.js";
import { useAudioCoverageQuery, useVoicesQuery } from "../../modules/narration/queries.js";
import { useTitle } from "../../lib/hooks.js";
import { fmtChapter, minutesLeft, clamp } from "../../lib/utils.js";

import {
  AUTOSCROLL_PX_PER_SEC, AudioPlayer, EndOfChapterCard,
  RichContent, loadReaderPrefs,
} from "../../modules/reading/ReaderParts.jsx";
import { ReaderToolbar } from "./ReaderToolbar.jsx";
import { useNarrationGuide } from "./useNarrationGuide.js";

export function Reader() {
  const { novelId: novelIdParam, number: numberParam } = useParams();
  const novelId = Number(novelIdParam);
  const number = Number(numberParam);
  const [sp] = useSearchParams();
  const navigate = useNavigate();
  const { user, onUserUpdate } = useAuth();
  const { toast } = useToast();
  const qc = useQueryClient();

  const { data: novel } = useNovelQuery(novelId);
  const { data: voicesData } = useVoicesQuery();
  const { data: audioCoverage, refetch: refetchCoverage } = useAudioCoverageQuery(novelId);

  const [ch, setCh] = useState(null);
  const [status, setStatus] = useState("loading");
  const [prefs, setPrefs] = useState(() => loadReaderPrefs(user));
  const [showSettings, setShowSettings] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [showToc, setShowToc] = useState(false);
  const [toc, setToc] = useState(null);
  const [bookmarks, setBookmarks] = useState([]);
  const [chrome, setChrome] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [readPct, setReadPct] = useState(0);
  const [coach, setCoach] = useState(() => {
    try { return !localStorage.getItem("nw-reader-coached"); } catch { return true; }
  });
  const [bookmarkBusy, setBookmarkBusy] = useState(false);
  const [tocError, setTocError] = useState(null);
  const scrollSaved = useRef(0);
  const lastScrollY = useRef(0);

  const listen = sp.get("listen") === "1";
  const {
    readerRef, narrationGuide, preparedNarration, setNarrationGuide,
  } = useNarrationGuide({ ch, novelId, number, chrome });

  useTitle(ch ? `Ch. ${fmtChapter(number)}` : null, novel ? novel.title : null);

  const openReader = useCallback((n, opts = {}) => {
    navigate(`/n/${novelId}/read/${n}${opts.listen ? "?listen=1" : ""}`);
  }, [navigate, novelId]);

  // Persist prefs locally + sync to the account (debounced).
  useEffect(() => {
    try { localStorage.setItem("nw-reader", JSON.stringify(prefs)); } catch { /* Storage may be unavailable. */ }
    if (!user) return;
    const t = setTimeout(() => {
      identityApi.updateMe({ prefs: { reader: prefs } })
        .then(u => { onUserUpdate && onUserUpdate(u); })
        .catch(() => {});
    }, 700);
    return () => clearTimeout(t);
  }, [prefs, user && user.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load the chapter + record progress; restore the saved scroll fraction.
  useEffect(() => {
    let cancel = false;
    setStatus("loading"); setCh(null); setReadPct(0);
    setChrome(true); setShowSettings(false); setShowTools(false);
    lastScrollY.current = 0;
    window.scrollTo({ top: 0 });
    Promise.all([
      readingApi.chapter(novelId, number),
      readingApi.getProgress(novelId).catch(() => null),
    ])
      .then(([c, prog]) => {
        if (cancel) return;
        setCh(c);
        setStatus("ok");
        const resume = prog && Number(prog.last_chapter) === Number(number) ? (prog.scroll_pct || 0) : 0;
        readingApi.setProgress(novelId, { last_chapter: Number(number), scroll_pct: resume }).catch(() => {});
        scrollSaved.current = Date.now();
        // Reflect progress in the cached novel so the codex ceiling follows reading.
        qc.setQueryData(["novel", novelId], (old) => old ? {
          ...old,
          progress: {
            ...old.progress,
            last_chapter: Number(number),
            max_chapter_read: Math.max((old.progress && old.progress.max_chapter_read) || 0, Number(number)),
          },
        } : old);
        if (resume > 0.002) {
          const applyScroll = () => {
            const h = document.documentElement;
            window.scrollTo({ top: resume * (h.scrollHeight - h.clientHeight) });
          };
          // Double rAF: first commits the DOM, second measures it.
          requestAnimationFrame(() => requestAnimationFrame(() => { if (!cancel) applyScroll(); }));
          // Imported rich chapters shift layout as images decode — re-apply once loaded.
          setTimeout(() => {
            if (cancel) return;
            const imgs = Array.from(document.querySelectorAll(".reader-rich img"));
            let pending = imgs.filter(im => !im.complete).length;
            if (!pending) return;
            const onDone = () => { if (--pending <= 0 && !cancel) applyScroll(); };
            imgs.forEach(im => { if (!im.complete) { im.addEventListener("load", onDone); im.addEventListener("error", onDone); } });
          }, 0);
        }
      })
      .catch(e => { if (!cancel) { setStatus(e.status === 404 ? "notfound" : "error"); } });
    return () => { cancel = true; };
  }, [novelId, number, reloadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadBookmarks = useCallback(() => {
    readingApi.bookmarks(novelId).then(setBookmarks).catch(() => setBookmarks([]));
  }, [novelId]);
  useEffect(() => { loadBookmarks(); }, [loadBookmarks]);
  useEffect(() => { setToc(null); setTocError(null); }, [novelId]);

  // Scroll saves this chapter only. Fetching another chapter advances the trusted
  // spoiler boundary, so chapter requests must wait for actual navigation.
  useEffect(() => {
    if (status !== "ok" || !ch || Number(ch.number) !== number) return;
    let saveTimer;
    const onScroll = () => {
      const h = document.documentElement;
      const denom = h.scrollHeight - h.clientHeight;
      const pct = denom > 0 ? clamp(h.scrollTop / denom, 0, 1) : 0;
      setReadPct(pct);

      const now = Date.now();
      if (now - scrollSaved.current > 2000) {
        scrollSaved.current = now;
        readingApi.setProgress(novelId, { last_chapter: number, scroll_pct: pct }).catch(() => {});
      }
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        readingApi.setProgress(novelId, { last_chapter: number, scroll_pct: pct }).catch(() => {});
      }, 500);

      // Auto-hide on scroll down, reveal on scroll up.
      const y = h.scrollTop;
      const dy = y - lastScrollY.current;
      if (Math.abs(dy) > 12) {
        if (dy > 0 && y > 160 && !showSettings && !showTools && !showToc
          && !document.activeElement?.closest(".reader-bar, .audio-bar")) setChrome(false);
        else if (dy < 0) setChrome(true);
        lastScrollY.current = y;
      }


    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { window.removeEventListener("scroll", onScroll); clearTimeout(saveTimer); };
  }, [novelId, number, ch, qc, status, showSettings, showTools, showToc]);

  // Auto-scroll engine.
  useEffect(() => {
    if (
      !prefs.autoScroll || narrationGuide.engaged || showSettings || showTools || showToc
      || status !== "ok" || !ch || (!ch.content && !ch.rich_html)
    ) return;
    let raf, last = performance.now(), acc = 0;
    const step = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      const h = document.documentElement;
      const maxTop = h.scrollHeight - h.clientHeight;
      if (maxTop > 4) {
        acc += AUTOSCROLL_PX_PER_SEC(prefs.autoSpeed) * dt;
        if (h.scrollTop >= maxTop - 1) {
          if (ch.next != null) { openReader(ch.next); return; }
          return;
        }
        if (acc >= 1) { const dy = Math.floor(acc); acc -= dy; window.scrollBy(0, dy); }
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [prefs.autoScroll, prefs.autoSpeed, narrationGuide.engaged, status, ch, openReader, showSettings, showTools, showToc]);

  // Keyboard prev/next.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") { setShowSettings(false); setShowTools(false); setChrome(true); return; }
      if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || showSettings || showTools || showToc) return;
      if (e.target.closest?.("input, textarea, select, button, a, [contenteditable], [role='dialog']")) return;
      if (e.key === "ArrowLeft" && ch && ch.prev != null) { e.preventDefault(); openReader(ch.prev); }
      if (e.key === "ArrowRight" && ch && ch.next != null) { e.preventDefault(); openReader(ch.next); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ch, openReader, showSettings, showTools, showToc]);

  // One-time coach mark.
  useEffect(() => {
    if (!coach) return;
    const t = setTimeout(() => {
      setCoach(false);
      try { localStorage.setItem("nw-reader-coached", "1"); } catch { /* Storage may be unavailable. */ }
    }, 5000);
    return () => clearTimeout(t);
  }, [coach]);

  function openTocDrawer() {
    if (toc == null) {
      setTocError(null);
      readingApi.chapters(novelId).then(setToc).catch(error => setTocError(error.message || "Could not load the contents."));
    }
    setShowToc(true);
  }

  const bookmark = bookmarks.find(b => b.chapter === Number(number));
  async function toggleBookmark() {
    if (bookmarkBusy) return;
    setBookmarkBusy(true);
    try {
      if (bookmark) { await readingApi.delBookmark(novelId, bookmark.id); toast("Bookmark removed.", { tone: "ok" }); }
      else { await readingApi.addBookmark(novelId, { chapter: Number(number) }); toast("Bookmarked.", { tone: "ok" }); }
      loadBookmarks();
    } catch (error) { toast(error.message || "Could not update your bookmark. Try again.", { tone: "danger" }); }
    finally { setBookmarkBusy(false); }
  }

  const fontFamily = prefs.font === "serif" ? "var(--serif)" : "var(--sans)";
  const colStyle = { fontFamily, fontSize: prefs.size, lineHeight: prefs.line };
  const widthCls = { narrow: "w-narrow", normal: "w-normal", wide: "w-wide", full: "w-full", ultra: "w-full" }[prefs.width] || "w-normal";

  const tapToggle = (e) => {
    if (e.target.closest("button, a, input, select, textarea, .reader-settings, .translate-tools, .drawer, .audio-bar, .popover")) return;
    if (showSettings) { setShowSettings(false); return; }
    if (showTools) { setShowTools(false); return; }
    setChrome(c => !c);
  };

  const minsLeft = ch && ch.word_count ? minutesLeft(ch.word_count, readPct) : null;
  const total = novel && novel.max_chapter != null ? fmtChapter(novel.max_chapter) : null;

  const markDoneAndNext = () => {
    readingApi.setProgress(novelId, { last_chapter: Number(number), scroll_pct: 1 }).catch(() => {});
    if (ch.next != null) openReader(ch.next, { listen });
  };

  return (
    <div ref={readerRef} className={"reader tone-" + prefs.tone + (chrome ? "" : " chrome-hidden")} onClick={tapToggle} onFocusCapture={() => setChrome(true)}>
      <div className="reader-rail" aria-hidden><div style={{ width: "100%", transform: `scaleX(${readPct})` }} /></div>

      <ReaderToolbar chrome={chrome} setChrome={setChrome} novel={novel} novelId={novelId}
        number={number} total={total} ch={ch} status={status} bookmark={bookmark}
        bookmarkBusy={bookmarkBusy} toggleBookmark={toggleBookmark} prefs={prefs} setPrefs={setPrefs}
        showSettings={showSettings} setShowSettings={setShowSettings} showTools={showTools} setShowTools={setShowTools}
        onBack={() => navigate(`/n/${novelId}`)} onOpenContents={openTocDrawer} onReload={() => setReloadKey(k => k + 1)} />

      {/* audio player */}
      {status === "ok" && ch && (ch.content || ch.rich_html) && (
        <AudioPlayer novelId={novelId} number={number} ch={ch} user={user} onUserUpdate={onUserUpdate}
                     openReader={(n) => openReader(n, { listen: true })}
                     onAudioChange={refetchCoverage} autoEngage={listen}
                     narrationChunks={preparedNarration.chunks}
                     onNarrationGuideChange={setNarrationGuide} />
      )}

      {/* body */}
      {status === "loading" && <div className={"reader-col " + widthCls} style={colStyle}><Loading label="Loading chapter…" /></div>}
      {status === "notfound" && (
        <div className={"reader-col " + widthCls} style={colStyle}>
          <EmptyState icon="x" title="Chapter not found" body="It may not have been scraped yet."
                      primaryAction={<Button variant="ghost" onClick={() => navigate(`/n/${novelId}/chapters`)}>Contents</Button>} />
        </div>
      )}
      {status === "error" && (
        <div className={"reader-col " + widthCls} style={colStyle}>
          <EmptyState icon="x" title="Couldn't load this chapter"
                      primaryAction={<Button variant="ghost" icon="refresh" onClick={() => setReloadKey(k => k + 1)}>Retry</Button>} />
        </div>
      )}

      {status === "ok" && ch && (
        <div className={"reader-col reader-fade-in " + widthCls} style={colStyle} key={ch.number}>
          <h1 className="reader-title">{ch.title || `Chapter ${fmtChapter(ch.number)}`}</h1>
          <div className="reader-chapnum">Chapter {fmtChapter(ch.number)}</div>
          {ch.provenance && <ProvenanceBadges provenance={ch.provenance} className="reader-prov" />}
          {(ch.overlay || ch.overlay_conflict) && (
            <div style={{ textAlign: "center", marginBottom: 12 }}>
              <Chip tone={ch.overlay_conflict ? "danger" : "accent"} icon={ch.overlay_conflict ? "alert" : "edit"}
                    style={{ cursor: "pointer" }}
                    onClick={e => { e.stopPropagation(); setShowTools(true); }}>
                {ch.overlay_conflict ? "Update available" : "Your translation"}
              </Chip>
            </div>
          )}
          {(!ch.content && !ch.rich_html) ? (
            <div className="reader-raw-note card">
              <Icon name="alert" size={18} className="muted" />
              <div className="grow">
                <b>{ch.translation_status === "failed" ? "Translation failed" : "No text available"}</b>
                <p className="muted" style={{ margin: "4px 0 10px", fontSize: "var(--text-md)" }}>
                  {ch.translation_status === "failed"
                    ? `Couldn't translate this raw chapter (${ch.language || "foreign"}). Try again.`
                    : "This chapter has no readable text yet."}
                </p>
                <Button variant="ghost" icon="refresh" onClick={() => setReloadKey(k => k + 1)}>Retry</Button>
              </div>
            </div>
          ) : preparedNarration.kind === "rich" ? (
            // Imported chapters ship sanitized rich HTML (server-side nh3).
            <RichContent html={preparedNarration.html} />
          ) : (
            <NarratedProse prepared={preparedNarration}
                           justify={prefs.justify} indent={prefs.indent} />
          )}

          {(ch.content || ch.rich_html) && (
            <EndOfChapterCard ch={ch} novelId={novelId}
                              onNext={markDoneAndNext}
                              onPrev={() => ch.prev != null && openReader(ch.prev)} />
          )}
        </div>
      )}

      {/* footer position line */}
      {status === "ok" && ch && (
        <div className={"reader-foot" + (chrome ? "" : " hidden")} onFocusCapture={() => setChrome(true)}>
          <button className="reader-chapter-nav" disabled={ch.prev == null} onClick={() => openReader(ch.prev, { listen })} aria-label="Previous chapter">
            <Icon name="arrowLeft" size={16} /><span>Previous</span>
          </button>
          <div className="reader-position"><span>{Math.round(readPct * 100)}% read</span>
            {minsLeft != null && <span>About {minsLeft} min left</span>}
          </div>
          <button className="reader-chapter-nav" disabled={ch.next == null} onClick={markDoneAndNext} aria-label="Next chapter">
            <span>Next chapter</span><Icon name="arrowRight" size={16} />
          </button>
        </div>
      )}

      {coach && status === "ok" && (
        <div className="coach-mark" role="status">
          <Icon name="sparkles" size={14} /> Tap the page to show or hide controls
        </div>
      )}

      {/* TOC drawer */}
      {showToc && (
        <Drawer title="Contents" onClose={() => setShowToc(false)}>
          {tocError ? <EmptyState icon="alert" title="Contents couldn't load" body={tocError}
            primaryAction={<Button variant="ghost" onClick={openTocDrawer}>Try again</Button>} /> : toc == null
            ? <Loading label="Loading…" />
            : <VolumeTOC toc={toc} currentNumber={Number(number)}
                         maxRead={novel && novel.progress ? novel.progress.max_chapter_read : null}
                         virtualize={false}
                         onOpen={(n) => { setShowToc(false); openReader(n); }}
                         audioCoverage={audioCoverage}
                         voices={(voicesData && voicesData.voices) || []}
                         preferredVoice={readTtsPrefs(user).voice} />}
        </Drawer>
      )}
    </div>
  );
}
