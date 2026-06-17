/* ============================================================
   Reader — the reading surface. Typeset chapter text, prev/next, a TOC drawer,
   bookmark toggle, and reader display settings (font/size/line-height/width/tone)
   persisted to localStorage. Reading progress (last chapter + scroll) is saved to
   the server so the library can resume and the codex ceiling can follow along.
   ============================================================ */
const READER_DEFAULTS = { font: "serif", size: 19, line: 1.7, width: "normal", tone: "default", autoScroll: false, autoSpeed: 3 };
const WIDTHS = { narrow: 620, normal: 760, wide: 960, ultra: 1200 };
// Auto-scroll: speed 1..10 maps to px/second (gentle reading pace ≈ 28–280 px/s).
const AUTOSCROLL_PX_PER_SEC = (speed) => Math.max(1, speed) * 28;

function loadReaderPrefs() {
  try { return { ...READER_DEFAULTS, ...JSON.parse(localStorage.getItem("nw-reader") || "{}") }; }
  catch (e) { return { ...READER_DEFAULTS }; }
}

function ReaderSettings({ prefs, setPrefs, onClose }) {
  const set = (k, v) => setPrefs(p => ({ ...p, [k]: v }));
  const Row = (label, children) => React.createElement("div", { className: "rs-row" },
    React.createElement("span", { className: "rs-label" }, label), children);
  const seg = (k, opts) => React.createElement("div", { className: "rs-seg" },
    opts.map(o => React.createElement("button", {
      key: o.v, className: prefs[k] === o.v ? "active" : "", onClick: () => set(k, o.v),
    }, o.t)));

  return React.createElement("div", { className: "reader-settings card", onClick: e => e.stopPropagation() },
    Row("Font", seg("font", [{ v: "serif", t: "Serif" }, { v: "sans", t: "Sans" }])),
    Row("Size", React.createElement("div", { className: "rs-seg" },
      React.createElement("button", { onClick: () => set("size", Math.max(14, prefs.size - 1)) }, "A−"),
      React.createElement("span", { className: "rs-val" }, prefs.size),
      React.createElement("button", { onClick: () => set("size", Math.min(28, prefs.size + 1)) }, "A+"))),
    Row("Line height", React.createElement("div", { className: "rs-seg" },
      React.createElement("button", { onClick: () => set("line", Math.max(1.3, Math.round((prefs.line - 0.1) * 10) / 10)) }, "−"),
      React.createElement("span", { className: "rs-val" }, prefs.line.toFixed(1)),
      React.createElement("button", { onClick: () => set("line", Math.min(2.2, Math.round((prefs.line + 0.1) * 10) / 10)) }, "+"))),
    Row("Width", seg("width", [{ v: "narrow", t: "Narrow" }, { v: "normal", t: "Normal" }, { v: "wide", t: "Wide" }, { v: "ultra", t: "Ultra" }])),
    Row("Tone", seg("tone", [{ v: "default", t: "Default" }, { v: "sepia", t: "Sepia" }])),
    Row("Auto-scroll", seg("autoScroll", [{ v: false, t: "Off" }, { v: true, t: "On" }])),
    Row("Scroll speed", React.createElement("div", { className: "rs-seg" },
      React.createElement("button", { onClick: () => set("autoSpeed", Math.max(1, prefs.autoSpeed - 1)) }, "−"),
      React.createElement("span", { className: "rs-val" }, prefs.autoSpeed),
      React.createElement("button", { onClick: () => set("autoSpeed", Math.min(10, prefs.autoSpeed + 1)) }, "+"))),
    React.createElement("button", { className: "btn btn-ghost", style: { width: "100%", marginTop: 8 }, onClick: onClose }, "Done")
  );
}

function Reader({ novelId, number, openReader, backToNovel, onRead }) {
  const [ch, setCh] = useState(null);     // null = loading
  const [status, setStatus] = useState("loading");
  const [prefs, setPrefs] = useState(loadReaderPrefs);
  const [showSettings, setShowSettings] = useState(false);
  const [toc, setToc] = useState(null);
  const [showToc, setShowToc] = useState(false);
  const [bookmarks, setBookmarks] = useState([]);
  const [chrome, setChrome] = useState(true);   // toolbar + floating nav visibility (tap to toggle)
  const [reloadKey, setReloadKey] = useState(0);
  const scrollSaved = useRef(0);

  useEffect(() => { localStorage.setItem("nw-reader", JSON.stringify(prefs)); }, [prefs]);

  // Load the chapter + record progress. If we're reopening the exact chapter the
  // server says we last left off in, restore the saved scroll fraction so reading
  // resumes seamlessly across devices (the position lives server-side, not locally).
  useEffect(() => {
    let cancel = false;
    setStatus("loading"); setCh(null);
    window.scrollTo({ top: 0 });
    Promise.all([
      window.API.chapter(novelId, number),
      window.API.getProgress(novelId).catch(() => null),
    ])
      .then(([c, prog]) => {
        if (cancel) return;
        setCh(c);
        setStatus("ok");
        const resume = prog && Number(prog.last_chapter) === Number(number) ? (prog.scroll_pct || 0) : 0;
        // Keep the resume fraction rather than zeroing it, so the position survives a reopen.
        window.API.setProgress(novelId, { last_chapter: Number(number), scroll_pct: resume }).catch(() => {});
        scrollSaved.current = Date.now();   // don't immediately re-save right after restoring
        onRead && onRead(Number(number));
        if (resume > 0.002) {
          // Restore after the text lays out. Double rAF: first commits the DOM, second measures it.
          const applyScroll = () => {
            const h = document.documentElement;
            window.scrollTo({ top: resume * (h.scrollHeight - h.clientHeight) });
          };
          requestAnimationFrame(() => requestAnimationFrame(() => { if (!cancel) applyScroll(); }));
          // Imported rich chapters carry images that shift layout as they decode (even with
          // reserved width/height, lazy ones load late) — re-apply the saved fraction once
          // they finish so the restore doesn't land short.
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
  }, [novelId, number, reloadKey]);

  // Bookmarks for this novel (to toggle the current chapter).
  const loadBookmarks = useCallback(() => {
    window.API.bookmarks(novelId).then(setBookmarks).catch(() => setBookmarks([]));
  }, [novelId]);
  useEffect(() => { loadBookmarks(); }, [loadBookmarks]);

  // Throttled scroll-position save.
  useEffect(() => {
    const onScroll = () => {
      const h = document.documentElement;
      const pct = h.scrollHeight > h.clientHeight ? h.scrollTop / (h.scrollHeight - h.clientHeight) : 0;
      const now = Date.now();
      if (now - scrollSaved.current > 2000) {
        scrollSaved.current = now;
        window.API.setProgress(novelId, { last_chapter: number, scroll_pct: pct }).catch(() => {});
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [novelId, number]);

  // Auto-scroll engine: rAF nudges the page down at the chosen speed. At the bottom it
  // rolls into the next chapter so a hands-free read flows continuously. Sub-pixel
  // accumulation keeps slow speeds smooth instead of stuttering one pixel at a time.
  useEffect(() => {
    if (!prefs.autoScroll || status !== "ok" || !ch || (!ch.content && !ch.rich_html)) return;
    let raf, last = performance.now(), acc = 0;
    const step = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      const h = document.documentElement;
      const maxTop = h.scrollHeight - h.clientHeight;
      if (maxTop > 4) {
        acc += AUTOSCROLL_PX_PER_SEC(prefs.autoSpeed) * dt;
        if (h.scrollTop >= maxTop - 1) {
          if (ch.next != null) { openReader(ch.next); return; }   // seamless next chapter
          return;                                                  // end of novel → stop
        }
        if (acc >= 1) { const dy = Math.floor(acc); acc -= dy; window.scrollBy(0, dy); }
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [prefs.autoScroll, prefs.autoSpeed, status, ch, openReader]);

  // Keyboard prev/next.
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (e.key === "ArrowLeft" && ch && ch.prev != null) openReader(ch.prev);
      if (e.key === "ArrowRight" && ch && ch.next != null) openReader(ch.next);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ch]);

  function openTocDrawer() {
    if (toc == null) window.API.chapters(novelId).then(setToc).catch(() => setToc([]));
    setShowToc(true);
  }

  const bookmark = bookmarks.find(b => b.chapter === Number(number));
  async function toggleBookmark() {
    if (bookmark) { await window.API.delBookmark(novelId, bookmark.id); }
    else { await window.API.addBookmark(novelId, { chapter: Number(number) }); }
    loadBookmarks();
  }

  const fontFamily = prefs.font === "serif" ? 'var(--serif, "Newsreader", Georgia, serif)' : 'var(--sans, "Hanken Grotesk", system-ui, sans-serif)';
  const colStyle = {
    maxWidth: WIDTHS[prefs.width] || 720,
    fontFamily, fontSize: prefs.size, lineHeight: prefs.line,
  };

  // Tap the page (not a control) to toggle the toolbar + floating nav.
  const tapToggle = (e) => {
    if (e.target.closest("button, a, input, select, textarea, .reader-settings, .drawer")) return;
    if (showSettings) { setShowSettings(false); return; }
    setChrome(c => !c);
  };

  return React.createElement("div", { className: "reader tone-" + prefs.tone + (chrome ? "" : " chrome-hidden"), onClick: tapToggle },
    // toolbar
    React.createElement("div", { className: "reader-bar" + (chrome ? "" : " hidden") },
      React.createElement("button", { className: "icon-btn", onClick: backToNovel, title: "Contents" },
        React.createElement(Icon, { name: "arrowLeft", size: 18 })),
      React.createElement("button", { className: "icon-btn", onClick: openTocDrawer, title: "Table of contents" },
        React.createElement(Icon, { name: "layers", size: 18 })),
      React.createElement("div", { className: "grow reader-bar-title" }, ch ? (ch.title || `Chapter ${ch.number}`) : "…"),
      React.createElement("button", {
        className: "icon-btn" + (prefs.autoScroll ? " active" : ""),
        onClick: e => { e.stopPropagation(); setPrefs(p => ({ ...p, autoScroll: !p.autoScroll })); },
        title: prefs.autoScroll ? "Stop auto-scroll" : "Auto-scroll",
      }, React.createElement(Icon, { name: prefs.autoScroll ? "pause" : "play", size: 17 })),
      React.createElement("button", { className: "icon-btn" + (bookmark ? " active" : ""), onClick: toggleBookmark, title: bookmark ? "Remove bookmark" : "Bookmark" },
        React.createElement(Icon, { name: bookmark ? "check" : "book", size: 18 })),
      React.createElement("div", { style: { position: "relative" } },
        React.createElement("button", { className: "icon-btn", onClick: e => { e.stopPropagation(); setShowSettings(s => !s); }, title: "Reading settings" },
          React.createElement("span", { style: { fontWeight: 700, fontSize: 15 } }, "Aa")),
        showSettings && React.createElement(ReaderSettings, { prefs, setPrefs, onClose: () => setShowSettings(false) })
      )
    ),

    // body
    status === "loading" && React.createElement("div", { className: "reader-col", style: colStyle }, React.createElement(Loading, { label: "Loading chapter…" })),

    status === "notfound" && React.createElement("div", { className: "reader-col", style: colStyle },
      React.createElement(EmptyState, { icon: "x", title: "Chapter not found", body: "It may not have been scraped yet." })),

    status === "error" && React.createElement("div", { className: "reader-col", style: colStyle },
      React.createElement(EmptyState, { icon: "x", title: "Couldn't load this chapter" })),

    status === "ok" && ch && React.createElement("div", { className: "reader-col", style: colStyle },
      React.createElement("h1", { className: "reader-title" }, ch.title || `Chapter ${ch.number}`),
      React.createElement("div", { className: "reader-chapnum mono" }, `Chapter ${ch.number}`),
      (!ch.content && !ch.rich_html)
        ? React.createElement("div", { className: "reader-raw-note card" },
            React.createElement(Icon, { name: "x", size: 18, className: "muted" }),
            React.createElement("div", { className: "grow" },
              React.createElement("b", null, ch.translation_status === "failed" ? "Translation failed" : "No text available"),
              React.createElement("p", { className: "muted", style: { margin: "4px 0 10px", fontSize: 14 } },
                ch.translation_status === "failed"
                  ? `Couldn't translate this raw chapter (${ch.language || "foreign"}). Try again.`
                  : "This chapter has no readable text yet."),
              React.createElement("button", { className: "btn btn-ghost", onClick: () => setReloadKey(k => k + 1) },
                React.createElement(Icon, { name: "refresh", size: 15 }), "Retry")))
        : ch.rich_html
          // Imported chapters ship sanitized rich HTML (server-side nh3) — render it directly.
          ? React.createElement("div", { className: "reader-text reader-rich", dangerouslySetInnerHTML: { __html: ch.rich_html } })
          : React.createElement("div", { className: "reader-text" },
              (ch.content || "").split(/\n{2,}/).map((para, i) =>
                React.createElement("p", { key: i }, para)))
    ),

    // floating nav (tap the page to show/hide)
    status === "ok" && ch && React.createElement("div", { className: "reader-float" + (chrome ? "" : " hidden") },
      React.createElement("button", { className: "rf-btn", disabled: ch.prev == null, onClick: () => ch.prev != null && openReader(ch.prev), title: "Previous chapter" },
        React.createElement(Icon, { name: "arrowLeft", size: 18 })),
      React.createElement("button", { className: "rf-btn rf-mid", onClick: backToNovel, title: "Contents" },
        React.createElement(Icon, { name: "layers", size: 17 }), "Contents"),
      React.createElement("button", { className: "rf-btn", disabled: ch.next == null, onClick: () => ch.next != null && openReader(ch.next), title: "Next chapter" },
        React.createElement(Icon, { name: "arrowRight", size: 18 }))
    ),

    // TOC drawer
    showToc && React.createElement("div", { className: "drawer-scrim", onClick: () => setShowToc(false) },
      React.createElement("div", { className: "drawer", onClick: e => e.stopPropagation() },
        React.createElement("div", { className: "drawer-head" },
          React.createElement("b", null, "Contents"),
          React.createElement("button", { className: "icon-btn", onClick: () => setShowToc(false) }, React.createElement(Icon, { name: "x", size: 16 }))),
        toc == null
          ? React.createElement(Loading, { label: "Loading…" })
          : React.createElement("div", { className: "drawer-toc" },
              toc.map(c => React.createElement("button", {
                key: c.number, className: "drawer-toc-row" + (c.number === Number(number) ? " current" : ""),
                onClick: () => { setShowToc(false); openReader(c.number); },
              },
                React.createElement("span", { className: "toc-num mono" }, c.number),
                React.createElement("span", { className: "toc-title" }, c.title || `Chapter ${c.number}`)
              )))
      )
    )
  );
}

window.Reader = Reader;
