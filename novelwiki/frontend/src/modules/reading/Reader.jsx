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
import { Drawer, OverlayHostProvider } from "../../components/overlay.jsx";
import { ProvenanceBadges } from "../../components/ProvenanceBadges.jsx";
import { VolumeTOC } from "./toc.jsx";
import { NarratedProse } from "./NarratedProse.jsx";
import { readTtsPrefs } from "../narration/index.js";
import { ChapterIllustrations } from "../codex/index.js";
import { useNovelQuery } from "../../modules/catalog/queries.js";
import { useAudioCoverageQuery, useVoicesQuery } from "../../modules/narration/queries.js";
import { useTitle } from "../../lib/hooks.js";
import { fmtChapter, minutesLeft, clamp } from "../../lib/utils.js";

import {
  AUTOSCROLL_PX_PER_SEC, AudioPlayer, EndOfChapterCard,
  RichContent, loadReaderPrefs, readerFontFamily,
} from "../../modules/reading/ReaderParts.jsx";
import { ChapterOpening, CoachMark, ReaderFooter, ReaderToolbar } from "./ReaderToolbar.jsx";
import { useNarrationGuide } from "./useNarrationGuide.js";
import { useReadySignal } from "../../motion/navigation.js";
import { useBookAtmosphere } from "../../atmosphere/store.js";

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
  const [loadedFor, setLoadedFor] = useState(null);
  const [prefs, setPrefs] = useState(() => loadReaderPrefs(user));
  const [showSettings, setShowSettings] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [showToc, setShowToc] = useState(false);
  const [toc, setToc] = useState(null);
  const [bookmarks, setBookmarks] = useState([]);
  const [chrome, setChrome] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [readPct, setReadPct] = useState(0);
  const [bookmarkBusy, setBookmarkBusy] = useState(false);
  const [tocError, setTocError] = useState(null);
  const scrollSaved = useRef(0);
  const lastScrollY = useRef(0);
  // The first chapter shown in this visit gets the full arrival choreography.
  const arrivedRef = useRef(null);
  if (arrivedRef.current == null && ch) arrivedRef.current = ch.number;

  const listen = sp.get("listen") === "1";
  const {
    readerRef, narrationGuide, preparedNarration, setNarrationGuide,
  } = useNarrationGuide({ ch, novelId, number, chrome });

  useTitle(ch ? `Ch. ${fmtChapter(number)}` : null, novel ? novel.title : null);
  // Hold chapter transitions until this chapter is on screen; tint with the book.
  useReadySignal(`chapter:${novelId}:${number}`, loadedFor === `${novelId}:${number}`);
  useBookAtmosphere(novel);

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
        setLoadedFor(`${novelId}:${number}`);
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
            // Restoring your place is not "scrolling down": keep the chrome.
            lastScrollY.current = window.scrollY;
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
      .catch(e => { if (!cancel) { setStatus(e.status === 404 ? "notfound" : "error"); setLoadedFor(`${novelId}:${number}`); } });
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

      // Auto-hide on scroll down, reveal on scroll up. Keyboard focus in the
      // chrome holds it; a clicked or tapped control (Play) keeps no hold.
      const y = h.scrollTop;
      const dy = y - lastScrollY.current;
      if (Math.abs(dy) > 12) {
        if (dy > 0 && y > 160 && !showSettings && !showTools && !showToc
          && !document.querySelector(".reader-bar :focus-visible, .audio-dock :focus-visible")) setChrome(false);
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
      if (e.target.closest?.("input, textarea, select, button, a, summary, [contenteditable], [role='dialog']")) return;
      if (e.key === "ArrowLeft" && ch && ch.prev != null) { e.preventDefault(); openReader(ch.prev); }
      if (e.key === "ArrowRight" && ch && ch.next != null) { e.preventDefault(); openReader(ch.next); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ch, openReader, showSettings, showTools, showToc]);

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

  const fontFamily = readerFontFamily(prefs.font);
  const colStyle = { fontFamily, fontSize: prefs.size, lineHeight: prefs.line };
  const widthCls = { narrow: "w-narrow", normal: "w-normal", wide: "w-wide", full: "w-full", ultra: "w-full" }[prefs.width] || "w-normal";

  const tapToggle = (e) => {
    if (e.target.closest("button, a, input, select, textarea, .chapter-illustrations, .reader-settings, .translate-tools, .drawer, .audio-dock, .popover, .reader-capsule")) return;
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
    <OverlayHostProvider hostRef={readerRef}>
    <div ref={readerRef} className={`reader tone-${prefs.tone} reader-tone-${prefs.tone}` + (chrome ? "" : " chrome-hidden")} onClick={tapToggle} onFocusCapture={() => setChrome(true)}>
      <div className="reader-glow" aria-hidden="true" />
      <div className="reader-rail" aria-hidden><div style={{ transform: `scaleX(${readPct})` }} /></div>

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
                      body="The connection or the server stumbled. Your place is saved, so try again in a moment."
                      primaryAction={<Button variant="ghost" icon="refresh" onClick={() => setReloadKey(k => k + 1)}>Retry</Button>} />
        </div>
      )}

      {status === "ok" && ch && (
        <div className={"reader-col " + (arrivedRef.current === ch.number ? "reader-arrive " : "reader-turn ") + widthCls} style={colStyle} key={ch.number}>
          <ChapterOpening ch={ch} minsTotal={ch.word_count ? minutesLeft(ch.word_count, 0) : null}>
            {ch.provenance && <ProvenanceBadges provenance={ch.provenance} className="reader-prov" />}
            {(ch.overlay || ch.overlay_conflict) && (
              <Chip tone={ch.overlay_conflict ? "danger" : "accent"} icon={ch.overlay_conflict ? "alert" : "edit"}
                    className="reader-overlay-chip" style={{ cursor: "pointer" }}
                    onClick={e => { e.stopPropagation(); setShowTools(true); }}>
                {ch.overlay_conflict ? "Update available" : "Your translation"}
              </Chip>
            )}
          </ChapterOpening>
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
          ) : <ChapterIllustrations novelId={novelId} chapter={number} personalVersion={!!(ch.overlay || ch.overlay_conflict)}>
          {scenes => preparedNarration.kind === "rich" ? (
            // Imported chapters ship sanitized rich HTML (server-side nh3).
            <RichContent html={preparedNarration.html} illustrations={scenes} />
          ) : (
            <NarratedProse prepared={preparedNarration}
                           justify={prefs.justify} indent={prefs.indent} illustrations={scenes} />
          )}
          </ChapterIllustrations>}

          {(ch.content || ch.rich_html) && (
            <EndOfChapterCard ch={ch} novelId={novelId}
                              onNext={markDoneAndNext}
                              onPrev={() => ch.prev != null && openReader(ch.prev)} />
          )}
        </div>
      )}

      {/* floating footer: previous / where you are / next */}
      {status === "ok" && ch && (
        <ReaderFooter chrome={chrome} setChrome={setChrome} ch={ch} readPct={readPct} minsLeft={minsLeft}
                      onPrev={() => openReader(ch.prev, { listen })} onNext={markDoneAndNext} />
      )}

      <CoachMark ready={status === "ok"} />

      {/* TOC drawer */}
      {showToc && (
        <Drawer title="Contents" onClose={() => setShowToc(false)}>
          {tocError ? <EmptyState icon="alert" title="Contents couldn't load" body={tocError}
            primaryAction={<Button variant="ghost" onClick={openTocDrawer}>Try again</Button>} /> : toc == null
            ? <Loading label="Loading…" />
            : <VolumeTOC toc={toc} currentNumber={Number(number)}
                         maxRead={novel && novel.progress ? novel.progress.max_chapter_read : null}
                         virtualize={false} locateNonce={1}
                         onOpen={(n) => { setShowToc(false); openReader(n); }}
                         audioCoverage={audioCoverage}
                         voices={(voicesData && voicesData.voices) || []}
                         preferredVoice={readTtsPrefs(user).voice} />}
        </Drawer>
      )}
    </div>
    </OverlayHostProvider>
  );
}
