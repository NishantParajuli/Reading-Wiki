/* Reader chrome: a floating glass capsule at the top (navigation, title,
   bookmark, reading settings, translation tools) and one at the bottom
   (previous/next and where you are). Both recede while you read and
   return on scroll-up, tap or keyboard focus. Named for view transitions
   so they hold still while a new chapter washes in beneath them. */
import React from "react";
import { Icon } from "../../components/Icon.jsx";
import { ProgressRing } from "../../components/ui.jsx";
import { fmtChapter } from "../../lib/utils.js";
import { ReaderSettings, TranslationTools } from "./ReaderParts.jsx";

export function ReaderToolbar({ chrome, setChrome, novel, novelId, number, total,
  ch, status, bookmark, bookmarkBusy, toggleBookmark, prefs, setPrefs,
  showSettings, setShowSettings, showTools, setShowTools, onBack, onOpenContents, onReload }) {
  return (
    <div className={"reader-bar" + (chrome ? "" : " hidden")} onFocusCapture={() => setChrome(true)}>
      <div className="reader-capsule">
        <button className="rc-btn" aria-label="Back to novel" title="Back to novel" onClick={() => onBack()}>
          <Icon name="arrowLeft" size={18} />
        </button>
        <button className="rc-btn" aria-label="Table of contents" title="Contents" onClick={onOpenContents}>
          <Icon name="list" size={18} />
        </button>
        <div className="reader-bar-title">
          <span className="rt-novel">{novel ? novel.title : ""}</span>
          <span className="rt-chapter">{ch ? (ch.title || `Chapter ${fmtChapter(ch.number)}`) : "…"}</span>
        </div>
        <span className="reader-bar-pos">{fmtChapter(number)}{total ? <span className="rbp-total"> / {total}</span> : ""}</span>
        <button className={"rc-btn rc-bookmark" + (bookmark ? " active" : "")} onClick={toggleBookmark}
                disabled={bookmarkBusy || status !== "ok"} aria-pressed={!!bookmark}
                aria-label={bookmark ? "Remove bookmark" : "Bookmark"} title={bookmark ? "Remove bookmark" : "Bookmark"}>
          <Icon name="bookmark" size={17} />
        </button>
        <div className="rc-anchor">
          <button className={"rc-btn rc-aa" + (showSettings ? " active" : "")} onClick={e => { e.stopPropagation(); setShowSettings(s => !s); setShowTools(false); }}
                  aria-label="Reading settings" aria-expanded={showSettings} title="Reading settings">
            <span aria-hidden="true">Aa</span>
          </button>
          {showSettings && <ReaderSettings prefs={prefs} setPrefs={setPrefs} onClose={() => setShowSettings(false)} />}
        </div>
        {status === "ok" && ch && (ch.content != null || ch.has_original) && (
          <div className="rc-anchor">
            <button className={"rc-btn" + (ch.overlay ? " active" : "") + (ch.overlay_conflict ? " is-conflict" : "")}
                    onClick={e => { e.stopPropagation(); setShowTools(s => !s); setShowSettings(false); }}
                    aria-label={ch.overlay_conflict ? "Translation update available" : (ch.overlay ? "Your translation edit" : "Edit translation")}
                    title={ch.overlay_conflict ? "Translation update available" : (ch.overlay ? "Your translation edit" : "Edit translation")}>
              <Icon name="edit" size={16} />
              {ch.overlay_conflict && <span className="ib-badge">1</span>}
            </button>
            {showTools && (
              <TranslationTools novelId={novelId} ch={ch}
                onClose={() => setShowTools(false)}
                onChanged={() => { setShowTools(false); onReload(); }} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function ReaderFooter({ chrome, setChrome, ch, readPct, minsLeft, onPrev, onNext }) {
  const pct = Math.round(readPct * 100);
  return (
    <div className={"reader-foot" + (chrome ? "" : " hidden")} onFocusCapture={() => setChrome(true)}>
      <div className="reader-capsule reader-capsule-foot">
        <button className="reader-chapter-nav" disabled={ch.prev == null} onClick={onPrev} aria-label="Previous chapter">
          <Icon name="arrowLeft" size={16} /><span>Previous</span>
        </button>
        <div className="reader-position">
          <ProgressRing value={pct} size={30} stroke={2.5} label="Chapter progress" />
          <span className="rp-text">
            <span className="rp-pct">{pct}% read</span>
            {minsLeft != null && <span className="rp-left">About {minsLeft} min left</span>}
          </span>
        </div>
        <button className="reader-chapter-nav is-next" disabled={ch.next == null} onClick={onNext} aria-label="Next chapter">
          <span>Next chapter</span><Icon name="arrowRight" size={16} />
        </button>
      </div>
    </div>
  );
}

/* The chapter's opening: a quiet title card. */
export function ChapterOpening({ ch, minsTotal, children }) {
  const title = ch.title || `Chapter ${fmtChapter(ch.number)}`;
  return (
    <header className="chapter-opening">
      <div className="co-numeral" aria-hidden="true">{fmtChapter(ch.number)}</div>
      <h1 className="reader-title">{title}</h1>
      <svg className="co-ornament" viewBox="0 0 220 16" aria-hidden="true">
        <path d="M2 8 C 22 1, 42 1, 62 8 S 102 15, 110 8" />
        <path d="M218 8 C 198 1, 178 1, 158 8 S 118 15, 110 8" />
        <circle cx="110" cy="8" r="2.6" />
      </svg>
      <div className="reader-chapnum">
        Chapter {fmtChapter(ch.number)}
        {minsTotal ? <><span aria-hidden="true"> · </span>{minsTotal} min read</> : null}
      </div>
      {children}
    </header>
  );
}
