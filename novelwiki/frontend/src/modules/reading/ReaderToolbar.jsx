import React from "react";
import { Icon } from "../../components/Icon.jsx";
import { fmtChapter } from "../../lib/utils.js";
import { ReaderSettings, TranslationTools } from "./ReaderParts.jsx";

export function ReaderToolbar({ chrome, setChrome, novel, novelId, number, total,
  ch, status, bookmark, bookmarkBusy, toggleBookmark, prefs, setPrefs,
  showSettings, setShowSettings, showTools, setShowTools, onBack, onOpenContents, onReload }) {
  return (
    <div className={"reader-bar" + (chrome ? "" : " hidden")} onFocusCapture={() => setChrome(true)}>
      <button className="icon-btn plain" aria-label="Back to novel" title="Back to novel"
              onClick={() => onBack()}>
        <Icon name="arrowLeft" size={18} />
      </button>
      <button className="icon-btn plain" aria-label="Table of contents" title="Contents" onClick={onOpenContents}>
        <Icon name="list" size={18} />
      </button>
      <div className="reader-bar-title">
        <span className="rt-novel">{novel ? novel.title : ""}</span>
        <span className="rt-chapter">{ch ? (ch.title || `Chapter ${fmtChapter(ch.number)}`) : "…"}</span>
      </div>
      <span className="reader-bar-pos">{fmtChapter(number)}{total ? ` / ${total}` : ""}</span>
      <button className={"icon-btn plain" + (bookmark ? " active" : "")} onClick={toggleBookmark}
              disabled={bookmarkBusy || status !== "ok"} aria-pressed={!!bookmark}
              aria-label={bookmark ? "Remove bookmark" : "Bookmark"} title={bookmark ? "Remove bookmark" : "Bookmark"}>
        <Icon name="bookmark" size={17} />
      </button>
      <div style={{ position: "relative" }}>
        <button className="icon-btn plain" onClick={e => { e.stopPropagation(); setShowSettings(s => !s); setShowTools(false); }}
                aria-label="Reading settings" aria-expanded={showSettings} title="Reading settings">
          <span style={{ fontWeight: 700, fontSize: 15 }}>Aa</span>
        </button>
        {showSettings && <ReaderSettings prefs={prefs} setPrefs={setPrefs} onClose={() => setShowSettings(false)} />}
      </div>
      {status === "ok" && ch && (ch.content != null || ch.has_original) && (
        <div style={{ position: "relative" }}>
          <button className={"icon-btn plain" + (ch.overlay ? " active" : "")}
                  style={ch.overlay_conflict ? { color: "var(--danger)" } : undefined}
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
  );
}
