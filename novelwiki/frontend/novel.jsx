/* ============================================================
   Novel detail — the per-novel hub: continue reading, sources, scraping,
   codex build, and the table of contents.
   ============================================================ */

// Non-chapter sections from file imports get a short tag instead of a number.
const TOC_KIND_LABEL = { frontmatter: "front", interlude: "interlude", backmatter: "extra" };

function ttsVoiceLabel(id, voiceMap) {
  const v = voiceMap && voiceMap.get(id);
  if (!v) return id;
  const name = v.name || id;
  return v.id && v.id !== name ? `${name} (${v.id})` : name;
}

function ttsVoiceMeta(v) {
  return [v && v.language, v && v.gender, v && v.accent].filter(Boolean).join(" · ");
}

// Group the flat chapter list into ordered TOC nodes: consecutive chapters that share a
// `part_label` (e.g. "Volume 1: Clown") fold into one collapsible volume; chapters with no
// label stay as top-level rows. This is what lets a 1,400-chapter / 8-volume import (LOTM,
// ReZero…) open as a tidy list of volumes you expand one at a time.
function groupToc(toc) {
  const nodes = [];
  let cur = null;
  toc.forEach(ch => {
    const pl = ch.part_label || null;
    if (pl) {
      if (!cur || cur.label !== pl) { cur = { type: "vol", label: pl, chapters: [] }; nodes.push(cur); }
      cur.chapters.push(ch);
    } else {
      cur = null;
      nodes.push({ type: "loose", chapter: ch });
    }
  });
  return nodes;
}

// One chapter / section row, shared by the grouped TOC and the reader drawer.
// `audioCoverage` carries all current shared voices for each chapter, so the row can show a
// voice-agnostic headphones marker while the tooltip preserves selected/preferred-voice detail.
function TocRow({ ch, currentNumber, onOpen, audioByChapter, voiceMap, preferredVoice }) {
  const isSection = ch.kind && ch.kind !== "chapter";
  const voices = (audioByChapter && audioByChapter.get(Number(ch.number))) || [];
  const narrated = voices.length > 0;
  const preferredAvailable = preferredVoice && voices.includes(preferredVoice);
  const audioTitle = narrated
    ? preferredAvailable
      ? `Narrated in preferred voice: ${ttsVoiceLabel(preferredVoice, voiceMap)}`
      : `Narrated in: ${voices.map(v => ttsVoiceLabel(v, voiceMap)).join(", ")}`
    : null;
  return React.createElement("button", {
    className: "toc-row" + (currentNumber === ch.number ? " current" : "") + (isSection ? " toc-section" : ""),
    onClick: () => onOpen(ch.number),
  },
    React.createElement("span", { className: "toc-num mono" }, isSection ? "—" : ch.number),
    React.createElement("span", { className: "toc-title" }, ch.title || `Chapter ${ch.number}`),
    isSection ? React.createElement("span", { className: "chip toc-kind", title: "Non-chapter section" }, TOC_KIND_LABEL[ch.kind] || ch.kind) : null,
    (!ch.has_content && ch.translation_status === "pending")
      ? React.createElement("span", { className: "chip", title: "Raw — translates on open" }, "raw") : null,
    narrated ? React.createElement(Icon, { name: "headphones", size: 14, className: "muted toc-audio", title: audioTitle }) : null,
    React.createElement(Icon, { name: "arrowRight", size: 15, className: "muted" })
  );
}

// Collapsible, volume-grouped table of contents. Every volume starts collapsed (the
// compressed overview) except the one holding the chapter you last read.
function VolumeTOC({ toc, currentNumber, onOpen, audioCoverage, voices, preferredVoice }) {
  const nodes = useMemo(() => groupToc(toc), [toc]);
  const audioByChapter = useMemo(() => {
    const m = new Map();
    ((audioCoverage && audioCoverage.chapters) || []).forEach(row => {
      m.set(Number(row.chapter), row.voices || []);
    });
    return m;
  }, [audioCoverage]);
  const voiceMap = useMemo(() => new Map((voices || []).map(v => [v.id, v])), [voices]);
  const currentVol = useMemo(() => {
    if (currentNumber == null) return null;
    const hit = toc.find(c => c.number === currentNumber);
    return hit ? (hit.part_label || null) : null;
  }, [toc, currentNumber]);
  const [open, setOpen] = useState({});
  // Auto-open the volume you're reading (and re-open it if progress moves to a new volume).
  useEffect(() => { if (currentVol) setOpen(o => (o[currentVol] ? o : { ...o, [currentVol]: true })); }, [currentVol]);
  const toggle = (label) => setOpen(o => ({ ...o, [label]: !o[label] }));

  return React.createElement(React.Fragment, null,
    nodes.map((node, i) => {
      if (node.type === "loose") {
        return React.createElement(TocRow, { key: "l" + node.chapter.number, ch: node.chapter, currentNumber, onOpen, audioByChapter, voiceMap, preferredVoice });
      }
      const isOpen = !!open[node.label];
      const chapterCount = node.chapters.filter(c => !c.kind || c.kind === "chapter").length;
      const hasCurrent = node.chapters.some(c => c.number === currentNumber);
      return React.createElement("div", { key: "v" + i, className: "toc-vol" + (isOpen ? " open" : "") },
        React.createElement("button", {
          className: "toc-vol-head" + (hasCurrent ? " has-current" : ""),
          onClick: () => toggle(node.label), "aria-expanded": isOpen,
        },
          React.createElement(Icon, { name: "chevronDown", size: 16, className: "toc-vol-caret" }),
          React.createElement("span", { className: "toc-vol-label" }, node.label),
          hasCurrent ? React.createElement("span", { className: "chip toc-vol-reading", title: "You're reading here" }, "reading") : null,
          React.createElement("span", { className: "toc-vol-count mono" }, chapterCount)
        ),
        isOpen ? React.createElement("div", { className: "toc-vol-body" },
          node.chapters.map(ch => React.createElement(TocRow, { key: ch.number, ch, currentNumber, onOpen, audioByChapter, voiceMap, preferredVoice }))
        ) : null
      );
    })
  );
}

function AddSourceForm({ novelId, adapters, onAdded, onCancel }) {
  const [adapter, setAdapter] = useState(adapters[0] ? adapters[0].name : "fenrirealm");
  const [startUrl, setStartUrl] = useState("");
  const [language, setLanguage] = useState("en");
  const [isRaw, setIsRaw] = useState(false);
  const [continuesFrom, setContinuesFrom] = useState("");
  const [localStart, setLocalStart] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    if (!startUrl.trim() || busy) return;
    setBusy(true);
    // Calculate custom offset: global_number = local_number + offset
    // => offset = global_start - local_start
    let offset = 0;
    if (continuesFrom.trim()) {
      const glob = parseFloat(continuesFrom);
      const loc = localStart.trim() ? parseFloat(localStart) : 1.0;
      offset = glob - loc;
    }

    try {
      await window.API.addSource(novelId, {
        adapter,
        start_url: startUrl.trim(),
        language,
        is_raw: isRaw,
        chapter_offset: offset,
        config: null,
      });
      onAdded();
    } finally {
      setBusy(false);
    }
  }

  return React.createElement("form", { className: "card add-source", onSubmit: submit },
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 0 } }, "Add a source"),
    React.createElement("div", { className: "row", style: { gap: 12, flexWrap: "wrap" } },
      React.createElement("label", { className: "field", style: { flex: "1 1 200px" } },
        React.createElement("span", null, "Technique"),
        React.createElement("select", { value: adapter, onChange: e => setAdapter(e.target.value) },
          adapters.map(a => React.createElement("option", { key: a.name, value: a.name }, a.label)))
      ),
      React.createElement("label", { className: "field", style: { flex: "0 0 110px" } },
        React.createElement("span", null, "Language"),
        React.createElement("input", { value: language, onChange: e => setLanguage(e.target.value) })
      )
    ),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "First chapter URL"),
      React.createElement("input", { value: startUrl, onChange: e => setStartUrl(e.target.value), placeholder: "https://…/1" })
    ),
    React.createElement("div", { className: "row", style: { gap: 16, flexWrap: "wrap" } },
      React.createElement("label", { className: "field", style: { flex: "1 1 180px" } },
        React.createElement("span", null, "Continues from global chapter"),
        React.createElement("input", { value: continuesFrom, onChange: e => setContinuesFrom(e.target.value), placeholder: "e.g. 125", inputMode: "decimal" })
      ),
      continuesFrom.trim() && React.createElement("label", { className: "field", style: { flex: "1 1 180px" } },
        React.createElement("span", null, "Source-local starting chapter"),
        React.createElement("input", { value: localStart, onChange: e => setLocalStart(e.target.value), placeholder: "defaults to 1", inputMode: "decimal" })
      ),
      React.createElement("label", { className: "check" },
        React.createElement("input", { type: "checkbox", checked: isRaw, onChange: e => setIsRaw(e.target.checked) }),
        "Raw (needs translation)"
      )
    ),
    React.createElement("div", { className: "row", style: { gap: 10 } },
      React.createElement("button", { className: "btn btn-primary", type: "submit", disabled: busy }, busy ? "Adding…" : "Add source"),
      React.createElement("button", { className: "btn btn-ghost", type: "button", onClick: onCancel }, "Cancel")
    )
  );
}

function EditSourceForm({ novelId, source, onSaved, onCancel }) {
  const [offset, setOffset] = useState(String(source.chapter_offset || 0));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function save() {
    if (busy) return;
    setBusy(true); setErr(null);
    try {
      const r = await window.API.updateSource(novelId, source.id, { chapter_offset: parseFloat(offset) || 0 });
      onSaved(r);
    } catch (e) {
      setErr(e.message || "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return React.createElement("div", { className: "card", style: { padding: 12, marginTop: 8, background: "var(--bg-2)" } },
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 0 } }, "Edit chapter offset"),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "Chapter offset (added to this source's own numbers)"),
      React.createElement("input", { value: offset, onChange: e => setOffset(e.target.value), placeholder: "e.g. -1", inputMode: "decimal" })
    ),
    React.createElement("p", { className: "muted", style: { fontSize: 12, marginTop: 6 } },
      "Use -1 if this raw source is one chapter ahead of the translation. Existing chapters are renumbered immediately."),
    err && React.createElement("p", { style: { color: "var(--danger, #c0392b)", fontSize: 12.5, marginTop: 4 } }, err),
    React.createElement("div", { className: "row", style: { gap: 10, marginTop: 8 } },
      React.createElement("button", { className: "btn btn-primary", type: "button", onClick: save, disabled: busy }, busy ? "Saving…" : "Save"),
      React.createElement("button", { className: "btn btn-ghost", type: "button", onClick: onCancel }, "Cancel")
    )
  );
}

function NovelEditForm({ novel, onSaved, onCancel, onRequestDelete }) {
  const [title, setTitle] = useState(novel.title || "");
  const [author, setAuthor] = useState(novel.author || "");
  const [description, setDescription] = useState(novel.description || "");
  const [cover, setCover] = useState(novel.cover_url || "");
  const [busy, setBusy] = useState(false);
  const [uploadingCover, setUploadingCover] = useState(false);
  const [coverMsg, setCoverMsg] = useState(null);
  const coverFileRef = useRef(null);

  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || busy || uploadingCover) return;
    setBusy(true);
    try {
      await window.API.updateNovel(novel.id, {
        title: title.trim(), author: author.trim() || null,
        description: description.trim() || null, cover_url: cover.trim() || null,
      });
      onSaved();
    } finally { setBusy(false); }
  }

  async function onPickCover(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setUploadingCover(true);
    setCoverMsg(null);
    try {
      const r = await window.API.uploadNovelCover(novel.id, file);
      setCover(r.cover_url || "");
      setCoverMsg({ ok: true, text: "Cover uploaded. Save to keep it." });
    } catch (err) {
      setCoverMsg({ ok: false, text: err.message || "Cover upload failed." });
    } finally {
      setUploadingCover(false);
      if (coverFileRef.current) coverFileRef.current.value = "";
    }
  }

  return React.createElement("form", { className: "card add-novel", onSubmit: submit, style: { marginBottom: 26 } },
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 0 } }, "Edit novel"),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "Title"),
      React.createElement("input", { value: title, onChange: e => setTitle(e.target.value), autoFocus: true })),
    React.createElement("div", { className: "row", style: { gap: 12, flexWrap: "wrap" } },
      React.createElement("label", { className: "field", style: { flex: "1 1 180px" } },
        React.createElement("span", null, "Author"),
        React.createElement("input", { value: author, onChange: e => setAuthor(e.target.value) })),
      React.createElement("div", { className: "field", style: { flex: "1 1 280px" } },
        React.createElement("span", null, "Cover image"),
        React.createElement("div", { className: "cover-edit" },
          cover
            ? React.createElement("img", { className: "cover-edit-preview", src: cover, alt: "" })
            : React.createElement("div", { className: "cover-edit-preview cover-edit-empty" }, React.createElement(Icon, { name: "book", size: 22 })),
          React.createElement("div", { className: "cover-edit-field" },
            React.createElement("input", { value: cover, onChange: e => { setCover(e.target.value); setCoverMsg(null); }, placeholder: "https://…" }),
            React.createElement("div", { className: "cover-edit-actions" },
              React.createElement("button", {
                className: "btn btn-ghost", type: "button", disabled: uploadingCover,
                onClick: () => coverFileRef.current && coverFileRef.current.click(),
              }, React.createElement(Icon, { name: "upload", size: 15 }), uploadingCover ? "Uploading…" : "Upload cover"),
              React.createElement("input", {
                ref: coverFileRef, type: "file", accept: "image/png,image/jpeg,image/webp,image/gif",
                style: { display: "none" }, onChange: onPickCover,
              }),
              React.createElement("span", { className: "muted", style: { fontSize: 12 } }, "PNG/JPG/WebP/GIF, under 10 MB.")
            ),
            coverMsg && React.createElement("p", {
              style: {
                color: coverMsg.ok ? "var(--muted)" : "var(--danger, #c0392b)",
                fontSize: 12.5, margin: 0,
              },
            }, coverMsg.text)
          )
        ))),
    React.createElement("label", { className: "field" },
      React.createElement("span", null, "Description"),
      React.createElement("textarea", { value: description, onChange: e => setDescription(e.target.value), rows: 3 })),
    React.createElement("div", { className: "row", style: { gap: 10, alignItems: "center" } },
      React.createElement("button", { className: "btn btn-primary", type: "submit", disabled: busy || uploadingCover }, busy ? "Saving…" : "Save"),
      React.createElement("button", { className: "btn btn-ghost", type: "button", onClick: onCancel }, "Cancel"),
      React.createElement("div", { className: "grow" }),
      React.createElement("button", {
        className: "btn btn-ghost is-danger", type: "button", onClick: onRequestDelete,
        title: "Permanently delete this novel",
      }, React.createElement(Icon, { name: "trash", size: 16 }), "Delete novel"))
  );
}

function GlossaryEditor({ novelId, glossary, reload }) {
  const [open, setOpen] = useState(false);   // minimized by default; expand on click
  const [st, setSt] = useState("");
  const [tr, setTr] = useState("");
  const [type, setType] = useState("name");
  const [busy, setBusy] = useState(false);

  async function add(e) {
    e.preventDefault();
    if (!st.trim() || !tr.trim() || busy) return;
    setBusy(true);
    try {
      await window.API.upsertGlossary(novelId, { source_term: st.trim(), translation: tr.trim(), term_type: type, locked: true });
      setSt(""); setTr(""); reload();
    } finally { setBusy(false); }
  }
  const toggleLock = async (g) => {
    await window.API.upsertGlossary(novelId, { source_term: g.source_term, translation: g.translation, term_type: g.term_type, notes: g.notes, locked: !g.locked });
    reload();
  };
  const del = async (g) => { await window.API.delGlossary(novelId, g.id); reload(); };

  return React.createElement(React.Fragment, null,
    React.createElement("button", {
      className: "section-eyebrow collapse-head", style: { marginTop: 28 },
      onClick: () => setOpen(o => !o), "aria-expanded": open,
    },
      `Translation glossary (${glossary.length})`,
      React.createElement(Icon, { name: "chevronDown", size: 15, className: "collapse-caret" + (open ? " open" : "") })
    ),
    open && React.createElement("div", { className: "card", style: { padding: 14 } },
      React.createElement("form", { className: "row", style: { gap: 8, flexWrap: "wrap", marginBottom: glossary.length ? 12 : 0 }, onSubmit: add },
        React.createElement("input", { className: "gl-input", value: st, onChange: e => setSt(e.target.value), placeholder: "Source term (林轩)" }),
        React.createElement("input", { className: "gl-input", value: tr, onChange: e => setTr(e.target.value), placeholder: "English (Lin Xuan)" }),
        React.createElement("select", { className: "gl-input", style: { flex: "0 0 104px" }, value: type, onChange: e => setType(e.target.value) },
          ["name", "place", "skill", "item", "term"].map(o => React.createElement("option", { key: o, value: o }, o))),
        React.createElement("button", { className: "btn btn-primary", type: "submit", disabled: busy }, "Add")
      ),
      glossary.map(g => React.createElement("div", { key: g.id, className: "gl-row" },
        React.createElement("span", { className: "gl-src" }, g.source_term),
        React.createElement(Icon, { name: "arrowRight", size: 13, className: "muted" }),
        React.createElement("span", { className: "gl-tr" }, g.translation),
        g.term_type && React.createElement("span", { className: "chip" }, g.term_type),
        React.createElement("div", { className: "grow" }),
        React.createElement("button", { className: "icon-btn" + (g.locked ? " active" : ""), title: g.locked ? "Locked — won't auto-change" : "Click to lock", onClick: () => toggleLock(g) },
          React.createElement(Icon, { name: g.locked ? "lock" : "unlock", size: 15 })),
        React.createElement("button", { className: "icon-btn", title: "Delete", onClick: () => del(g) }, React.createElement(Icon, { name: "x", size: 15 }))
      ))
    )
  );
}

// Toggle a tag with radio (one-per-group) or checkbox semantics. `group` is a radio
// group ({id,label,tags}) or null for a free checkbox tag.
function toggleTag(tags, t, group) {
  if (tags.includes(t)) return tags.filter(x => x !== t);
  if (group) return [...tags.filter(x => !group.tags.includes(x)), t];
  return [...tags, t];
}

// The shared tag picker: mutually-exclusive radio groups + multi-select genre checkboxes.
function TagEditor({ tags, onToggle, disabled }) {
  const h = React.createElement;
  return h("div", { className: "tag-editor" },
    window.STATUS_TAG_RADIO_GROUPS.map(g => h("div", { key: g.id, className: "tag-group" },
      h("span", { className: "st-label" }, g.label),
      h("div", { className: "st-tags" },
        g.tags.map(t => h("button", {
          key: t, type: "button", disabled,
          className: "tag-toggle radio" + (tags.includes(t) ? " on" : ""),
          onClick: () => onToggle(t, g),
        }, window.STATUS_TAG_LABELS[t])))
    )),
    h("div", { className: "tag-group" },
      h("span", { className: "st-label" }, "Genres"),
      h("div", { className: "st-tags" },
        window.GENRE_TAGS.map(t => h("button", {
          key: t, type: "button", disabled,
          className: "tag-toggle" + (tags.includes(t) ? " on" : ""),
          onClick: () => onToggle(t, null),
        }, window.STATUS_TAG_LABELS[t])))
    )
  );
}

// Reader-facing form to propose a tag set to the owner/admin of a shared novel.
function TagSuggestForm({ novel, current, onClose }) {
  const h = React.createElement;
  const [tags, setTags] = useState(current || []);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  async function submit() {
    setBusy(true);
    try { await window.API.suggestTags(novel.id, tags, note); setDone(true); }
    catch (e) { alert(e.message || "Couldn't send your suggestion."); setBusy(false); }
  }
  if (done) return h("div", { className: "card", style: { padding: 12, marginTop: 8 } },
    h("div", { className: "acct-ok" }, "Tag suggestion sent to the owner for review."),
    h("button", { className: "btn btn-ghost sm", style: { marginTop: 8 }, onClick: onClose }, "Close"));
  return h("div", { className: "card", style: { padding: 12, marginTop: 8 } },
    h("p", { className: "section-eyebrow", style: { marginTop: 0 } }, "Suggest tags"),
    h(TagEditor, { tags, onToggle: (t, g) => setTags(prev => toggleTag(prev, t, g)), disabled: busy }),
    h("textarea", { className: "tt-textarea", rows: 2, style: { marginTop: 8 }, value: note,
      placeholder: "Optional note for the owner…", onChange: e => setNote(e.target.value) }),
    h("div", { className: "row", style: { gap: 8, marginTop: 8 } },
      h("button", { className: "btn btn-primary", disabled: busy, onClick: submit },
        h(Icon, { name: "send", size: 14 }), "Send suggestion"),
      h("button", { className: "btn btn-ghost", disabled: busy, onClick: onClose }, "Cancel"))
  );
}

function ShelfTagsControls({ novel, reloadNovel }) {
  const h = React.createElement;
  const shelf = novel.shelf || "";
  const tags = novel.status_tags || [];
  const tt = novel.translation_type ? window.TRANSLATION_TYPE_LABELS[novel.translation_type] : null;
  const canEdit = !!novel.can_edit;
  const [busy, setBusy] = useState(false);
  const [suggesting, setSuggesting] = useState(false);

  const patch = async (body) => {
    if (busy) return;
    setBusy(true);
    try { await window.API.updateNovel(novel.id, body); reloadNovel(); }
    catch (e) { alert(e.message || "Update failed."); }
    finally { setBusy(false); }   // always release, or every later click is blocked
  };
  const setShelf = (s) => patch({ shelf: shelf === s ? "" : s });   // tap the active shelf to clear it
  const onToggleTag = (t, group) => patch({ status_tags: toggleTag(tags, t, group) });

  return h("div", { className: "shelf-tags" },
    h("div", { className: "st-group" },
      h("span", { className: "st-label" }, "Shelf"),
      h("div", { className: "rs-seg" },
        window.SHELF_ORDER.map(s => h("button", {
          key: s, className: shelf === s ? "active" : "", onClick: () => setShelf(s),
        }, window.SHELF_LABELS[s])))
    ),
    // Owner/admin edit tags inline; everyone else sees them read-only and (on shared
    // novels) can propose a set via "Suggest tags".
    canEdit
      ? h("div", { className: "st-group" },
          h("span", { className: "st-label" }, "Tags"),
          h(TagEditor, { tags, onToggle: onToggleTag, disabled: busy }),
          tt && h("span", { className: "chip tt-chip", title: "Auto-detected from sources" }, tt))
      : h("div", { className: "st-group" },
          h("span", { className: "st-label" }, "Tags"),
          h("div", { className: "st-tags" },
            tags.length === 0 && h("span", { className: "muted", style: { fontSize: 13 } }, "No tags yet"),
            tags.map(t => h("span", { key: t, className: "chip tag-chip" }, window.STATUS_TAG_LABELS[t] || t)),
            tt && h("span", { className: "chip tt-chip", title: "Auto-detected from sources" }, tt)),
          novel.can_suggest_tags && !suggesting && h("button", {
            className: "btn btn-ghost sm", style: { marginTop: 6 }, onClick: () => setSuggesting(true),
          }, h(Icon, { name: "sparkles", size: 14 }), "Suggest tags")),
    suggesting && h(TagSuggestForm, { novel, current: tags, onClose: () => setSuggesting(false) })
  );
}

/* Per-novel visibility control (owner/admin). Only admins get the Global option; a Global
   novel is admin-owned, so non-admin owners never see this for one. */
function VisibilityControl({ novel, reloadNovel, isAdmin }) {
  const [busy, setBusy] = useState(false);
  const opts = isAdmin ? ["private", "public", "global"]
    : (novel.visibility === "global" ? ["global"] : ["private", "public"]);
  async function change(e) {
    const v = e.target.value;
    setBusy(true);
    try { await window.API.setVisibility(novel.id, v); reloadNovel && reloadNovel(); }
    catch (err) { alert(err.message || "Could not change visibility."); }
    finally { setBusy(false); }
  }
  const LABELS = { private: "Private", public: "Public", global: "Global" };
  return React.createElement("label", { className: "row", style: { gap: 6, alignItems: "center" }, title: "Who can see this novel" },
    React.createElement(Icon, { name: "compass", size: 15 }),
    React.createElement("select", { className: "shelf-select", value: novel.visibility || "private", disabled: busy, onChange: change },
      opts.map(v => React.createElement("option", { key: v, value: v }, LABELS[v])))
  );
}

/* Per-novel contribute-back policy (owner/admin): whether reader edit offers auto-merge
   when there's no conflict, or always wait for manual review. */
function ContributionPolicyControl({ novel, reloadNovel }) {
  const [busy, setBusy] = useState(false);
  async function change(e) {
    setBusy(true);
    try { await window.API.updateNovel(novel.id, { contribution_policy: e.target.value }); reloadNovel && reloadNovel(); }
    catch (err) { alert(err.message || "Couldn't change the policy."); }
    finally { setBusy(false); }
  }
  return React.createElement("label", { className: "row", style: { gap: 6, alignItems: "center" }, title: "How reader translation edits are merged back" },
    React.createElement(Icon, { name: "merge", size: 15 }),
    React.createElement("select", { className: "shelf-select", value: novel.contribution_policy || "manual", disabled: busy, onChange: change },
      React.createElement("option", { value: "manual" }, "Review edits"),
      React.createElement("option", { value: "auto" }, "Auto-merge clean edits")
    )
  );
}

/* Owner/admin inbox of contribute-back offers. Hidden when there's nothing pending. */
function ContributionsInbox({ novelId, reloadNovel }) {
  const [items, setItems] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [drafts, setDrafts] = useState({});
  const load = useCallback(() => {
    window.API.contributions(novelId).then(setItems).catch(() => setItems([]));
  }, [novelId]);
  useEffect(() => { load(); }, [load]);

  if (items == null || items.length === 0) return null;

  const act = async (c, accept) => {
    const resolved = (drafts[c.id] || "").trim();
    if (accept && c.is_conflict && !resolved) {
      alert("Resolve this conflict before accepting it.");
      return;
    }
    setBusyId(c.id);
    try {
      if (accept) await window.API.acceptContribution(novelId, c.id, c.is_conflict ? resolved : undefined);
      else await window.API.rejectContribution(novelId, c.id);
      load(); reloadNovel && reloadNovel();
    } catch (e) { alert(e.message || "Action failed."); }
    finally { setBusyId(null); }
  };

  return React.createElement(React.Fragment, null,
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 28 } }, `Contribution requests (${items.length})`),
    React.createElement("div", { className: "card", style: { padding: 12 } },
      items.map(c => {
        const draft = drafts[c.id] || "";
        return React.createElement("div", { key: c.id, className: "contrib-row" },
          React.createElement("div", { className: "row", style: { gap: 8, alignItems: "center", marginBottom: 6 } },
            React.createElement("span", { className: "chip mono" }, `Ch. ${c.chapter}`),
            React.createElement("span", { style: { fontWeight: 600 } }, c.from_display_name),
            React.createElement("span", { className: "muted", style: { fontSize: 12.5 } }, "@" + c.from_username),
            c.is_conflict && React.createElement("span", { className: "chip", style: { background: "var(--danger, #c0392b)", color: "#fff" }, title: "Base changed since this was offered" }, "conflict"),
            React.createElement("div", { className: "grow" })
          ),
          // GitHub-style review: current base on top, proposed edit below with +/- changes.
          React.createElement(window.DiffView, {
            oldText: c.base_content || "", newText: c.content || "",
            oldLabel: "Current base", newLabel: "Proposed edit",
          }),
          c.is_conflict && React.createElement("div", { className: "contrib-merge" },
            React.createElement("div", { className: "row", style: { gap: 8, marginTop: 8, flexWrap: "wrap" } },
              React.createElement("button", { className: "btn btn-ghost sm", onClick: () => setDrafts(d => ({ ...d, [c.id]: c.content || "" })) }, "Use proposed"),
              React.createElement("button", { className: "btn btn-ghost sm", onClick: () => setDrafts(d => ({ ...d, [c.id]: c.base_content || "" })) }, "Use latest base")
            ),
            React.createElement("textarea", {
              className: "tt-textarea contrib-merge-text", rows: 6, value: draft,
              onChange: e => setDrafts(d => ({ ...d, [c.id]: e.target.value })),
              placeholder: "Paste or edit the resolved translation to merge..."
            })
          ),
          React.createElement("div", { className: "row", style: { gap: 8, marginTop: 8 } },
            React.createElement("button", {
              className: "btn btn-primary",
              disabled: busyId === c.id || (c.is_conflict && !draft.trim()),
              onClick: () => act(c, true),
              title: c.is_conflict ? "Merge the resolved text into the shared base" : "Merge into the shared base",
            }, React.createElement(Icon, { name: "check", size: 15 }), c.is_conflict ? "Accept merge" : "Accept"),
            React.createElement("button", { className: "btn btn-ghost", disabled: busyId === c.id, onClick: () => act(c, false) },
              React.createElement(Icon, { name: "x", size: 15 }), "Reject")
          )
        );
      })
    )
  );
}

/* Owner/admin inbox of reader tag suggestions. Hidden when there's nothing pending. */
function TagSuggestionsInbox({ novelId, reloadNovel }) {
  const h = React.createElement;
  const [items, setItems] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const load = useCallback(() => {
    window.API.tagSuggestions(novelId).then(setItems).catch(() => setItems([]));
  }, [novelId]);
  useEffect(() => { load(); }, [load]);

  if (items == null || items.length === 0) return null;

  const act = async (s, accept) => {
    setBusyId(s.id);
    try {
      if (accept) await window.API.acceptTagSuggestion(novelId, s.id);
      else await window.API.rejectTagSuggestion(novelId, s.id);
      load(); reloadNovel && reloadNovel();
    } catch (e) { alert(e.message || "Action failed."); }
    finally { setBusyId(null); }
  };

  return h(React.Fragment, null,
    h("p", { className: "section-eyebrow", style: { marginTop: 28 } }, `Tag suggestions (${items.length})`),
    h("div", { className: "card", style: { padding: 12 } },
      items.map(s => h("div", { key: s.id, className: "contrib-row" },
        h("div", { className: "row", style: { gap: 8, alignItems: "center", marginBottom: 6 } },
          h("span", { style: { fontWeight: 600 } }, s.from_display_name),
          h("span", { className: "muted", style: { fontSize: 12.5 } }, "@" + s.from_username),
          h("div", { className: "grow" })
        ),
        h("div", { className: "st-tags", style: { marginBottom: s.note ? 6 : 0 } },
          s.tags.length === 0
            ? h("span", { className: "muted", style: { fontSize: 13 } }, "(clear all tags)")
            : s.tags.map(t => h("span", { key: t, className: "chip tag-chip" }, window.STATUS_TAG_LABELS[t] || t))
        ),
        s.note && h("div", { className: "muted", style: { fontSize: 13 } }, s.note),
        h("div", { className: "row", style: { gap: 8, marginTop: 8 } },
          h("button", { className: "btn btn-primary", disabled: busyId === s.id, onClick: () => act(s, true) },
            h(Icon, { name: "check", size: 15 }), "Apply"),
          h("button", { className: "btn btn-ghost", disabled: busyId === s.id, onClick: () => act(s, false) },
            h(Icon, { name: "x", size: 15 }), "Reject")
        )
      ))
    )
  );
}

/* Operational surface over the durable scrape/codex/translation jobs for this novel. Shows the
   active + recent jobs (status, stage, live progress) and lets the owner cancel one in flight.
   Polls while anything is active; hidden entirely when there's no job history. */
const JOB_KIND_LABEL = { scrape: "Scrape", codex_build: "Codex build", translate: "Translation", agy_smoke: "AGY smoke" };
const JOB_STATUS_CHIP = { queued: "chip", running: "chip job-run", done: "chip job-ok",
                          waiting_provider: "chip job-warn", failed: "chip job-err", canceled: "chip" };

function jobProgressText(job) {
  const p = job.progress || {};
  if (job.kind === "translate" && p.total != null) {
    let s = `${p.done || 0}/${p.total} translated`;
    if (p.failed) s += `, ${p.failed} failed`;
    if (p.stopped_reason === "quota") s += " — stopped (quota)";
    return s;
  }
  if (job.kind === "codex_build" && p.steps != null) return `step ${p.step || 0}/${p.steps}${p.stage ? ` — ${p.stage}` : ""}`;
  if (job.kind === "scrape" && p.scraped != null) return `${p.scraped} chapters scraped`;
  return job.stage || "";
}

function JobCenter({ novelId }) {
  const h = React.createElement;
  const [jobs, setJobs] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const timerRef = React.useRef(null);

  const load = useCallback(async () => {
    try {
      const r = await window.API.jobs({ novel_id: novelId, limit: 25 });
      setJobs(r.jobs || []);
      return r.jobs || [];
    } catch (e) { setJobs([]); return []; }
  }, [novelId]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const list = await load();
      if (!alive) return;
      const active = list.some(j => j.status === "queued" || j.status === "running" || j.status === "waiting_provider");
      timerRef.current = setTimeout(tick, active ? 3000 : 15000);
    };
    tick();
    return () => { alive = false; if (timerRef.current) clearTimeout(timerRef.current); };
  }, [load]);

  if (jobs == null || jobs.length === 0) return null;

  const cancel = async (job) => {
    setBusyId(job.id);
    try { await window.API.cancelJob(job.id); await load(); }
    catch (e) { alert(e.message || "Cancel failed."); }
    finally { setBusyId(null); }
  };

  return h(React.Fragment, null,
    h("p", { className: "section-eyebrow", style: { marginTop: 28 } }, "Background jobs"),
    h("div", { className: "card", style: { padding: 12 } },
      jobs.map(job => {
        const active = job.status === "queued" || job.status === "running" || job.status === "waiting_provider";
        return h("div", { key: job.id, className: "toc-row", style: { cursor: "default", alignItems: "center" } },
          h("span", { className: "chip", style: { minWidth: 92 } }, JOB_KIND_LABEL[job.kind] || job.kind),
          h("span", { className: job.execution_backend === "agy" ? "chip job-run" : "chip" },
            job.backend_fallback_from ? `${job.backend_fallback_from.toUpperCase()}→${(job.execution_backend || "api").toUpperCase()}` : (job.execution_backend || "api").toUpperCase()),
          h("span", { className: JOB_STATUS_CHIP[job.status] || "chip" }, job.status),
          h("span", { className: "toc-title", style: { flex: 1 } }, jobProgressText(job)),
          job.backend_model ? h("span", { className: "muted", style: { fontSize: 11 }, title: `Plugin ${job.plugin_version || "—"}` }, job.backend_model) : null,
          job.attempts > 1 && job.status !== "done"
            ? h("span", { className: "muted", style: { fontSize: 12 } }, `attempt ${job.attempts}/${job.max_attempts}`) : null,
          job.error && (job.status === "failed")
            ? h("span", { className: "muted", style: { fontSize: 12, color: "var(--danger, #c0392b)" }, title: job.error },
                (job.error || "").slice(0, 60)) : null,
          active
            ? h("button", { className: "icon-btn", title: "Cancel job", disabled: busyId === job.id, onClick: () => cancel(job) },
                h(Icon, { name: "x", size: 15 })) : null
        );
      })
    )
  );
}

/* Whole-book narration (available to any reader). Picks a narrator + how many chapters, queues
   a bounded, cancellable batch through the durable TTS worker, and shows live progress. A long
   book is narrated in successive capped batches; cached chapters are skipped automatically. */
function NarrateBookControl({ novelId, novel, user, audioCoverage, onChange }) {
  const [open, setOpen] = useState(false);
  const [voices, setVoices] = useState(null);   // null=loading | [] offline
  const [voice, setVoice] = useState(null);
  const [defaultVoice, setDefaultVoice] = useState(null);
  const minCh = novel?.min_chapter != null ? String(novel.min_chapter) : "";
  const [startCh, setStartCh] = useState(minCh);
  const [endCh, setEndCh] = useState("");
  const [job, setJob] = useState(null);
  const [msg, setMsg] = useState(null);
  const [est, setEst] = useState(null);   // {estimated_units, remaining, limit, unlimited} for the current range/voice
  const [pendingStart, setPendingStart] = useState(null);
  const pollRef = useRef(null);
  const h = React.createElement;

  useEffect(() => {
    setStartCh(minCh);
  }, [minCh]);

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  useEffect(() => () => stopPoll(), []);

  useEffect(() => {
    window.API.ttsVoices().then(r => {
      const list = (r.voices || []).filter(v => v.ready);
      setVoices(list);
      setDefaultVoice(r.default || null);
      const pref = user && user.prefs && user.prefs.tts && user.prefs.tts.voice;
      const ids = new Set(list.map(v => v.id));
      setVoice((pref && ids.has(pref)) ? pref : ((r.default && ids.has(r.default)) ? r.default : ((list[0] && list[0].id) || null)));
    }).catch(() => setVoices([]));
  }, []);

  function poll(id) {
    stopPoll();
    pollRef.current = setInterval(async () => {
      try {
        const j = await window.API.ttsJob(id);
        setJob(j);
        if (["done", "failed", "canceled"].includes(j.status)) { stopPoll(); onChange && onChange(); }
      } catch (e) { stopPoll(); }
    }, 1800);
  }

  useEffect(() => {
    if (!voice) return;
    let cancel = false;
    window.API.bookAudioStatus(novelId, voice).then(r => {
      if (cancel) return;
      if (r.active && r.job) {
        setMsg(null);
        setJob(r.job);
        setOpen(true);
        poll(r.job.id);
      } else {
        setJob(j => j && ["queued", "generating"].includes(j.status) ? null : j);
      }
    }).catch(() => {});
    return () => { cancel = true; };
  }, [novelId, voice]);

  // Pre-flight estimate for the narration panel: how many chapters this range would generate
  // (skipping cached ones) and the reader's remaining monthly quota. Never charges.
  useEffect(() => {
    if (!open || !voice) { setEst(null); return; }
    let cancel = false;
    window.API.costEstimate(novelId, "audiobook", {
      voice_id: voice,
      from_chapter: startCh.trim() ? parseFloat(startCh) : null,
      to_chapter: endCh.trim() ? parseFloat(endCh) : null,
    }).then(e => { if (!cancel) setEst(e); }).catch(() => { if (!cancel) setEst(null); });
    return () => { cancel = true; };
  }, [open, voice, startCh, endCh, novelId]);

  const narrationParams = () => ({
    voice_id: voice,
    from_chapter: startCh.trim() ? parseFloat(startCh) : null,
    to_chapter: endCh.trim() ? parseFloat(endCh) : null,
  });

  async function start(params) {
    const p = params || narrationParams();
    if (!p.voice_id) return;
    setMsg(null); setJob(null);
    try {
      const r = await window.API.generateBookAudio(
        novelId,
        p.voice_id,
        p.from_chapter,
        p.to_chapter
      );
      if (r.status === "ready") { setMsg(r.message || "Every chapter is already narrated in this voice."); return; }
      setMsg(r.existing
        ? "Already narrating this book in that voice."
        : r.capped
        ? `Queued ${r.total} chapters (max per batch — run again for more).`
        : `Queued ${r.total} chapter${r.total === 1 ? "" : "s"}.`);
      setJob({ id: r.job_id, status: "queued", progress: { total: r.total, done: 0 } });
      poll(r.job_id);
    } catch (e) {
      setMsg(e.status === 429 ? (e.message || "Monthly narration quota reached.") : (e.message || "Couldn't start narration."));
    }
  }

  async function cancel() {
    if (!job) return;
    try { await window.API.cancelTtsJob(job.id); } catch (e) {}
  }

  if (voices == null || voices.length === 0) return null;   // hidden while loading / sidecar offline

  const running = job && ["queued", "generating"].includes(job.status);
  const prog = (job && job.progress) || {};
  const pct = prog.total ? Math.round((100 * (prog.done || 0)) / prog.total) : 0;
  const stopped = prog.stopped_reason;
  const prefVoice = user && user.prefs && user.prefs.tts && user.prefs.tts.voice;
  const selectedVoice = (voices || []).find(v => v.id === voice);
  const coverageByVoice = new Map(((audioCoverage && audioCoverage.voices) || []).map(v => [v.voice_id, v]));
  const selectedCoverage = coverageByVoice.get(voice) || { have: 0, missing: audioCoverage ? audioCoverage.prose_chapters : 0 };
  const voiceOptionText = (v) => {
    const meta = ttsVoiceMeta(v);
    const cov = coverageByVoice.get(v.id);
    const bits = [v.name || v.id, v.id, meta].filter(Boolean);
    if (cov && audioCoverage) bits.push(`${cov.have}/${audioCoverage.prose_chapters} narrated`);
    if (prefVoice === v.id) bits.push("preferred");
    else if (defaultVoice === v.id) bits.push("default");
    return bits.join(" · ");
  };

  return h("div", { className: "narrate-ctl", style: { position: "relative" } },
    h("button", { className: "btn btn-ghost", onClick: () => setOpen(o => !o) },
      h(Icon, { name: "headphones", size: 16 }), "Narrate book"),
    open && h("div", { className: "card narrate-panel", onClick: e => e.stopPropagation() },
      h("div", { className: "row", style: { gap: 8, alignItems: "flex-end", flexWrap: "wrap" } },
        h("label", { className: "field", style: { flex: 1, minWidth: 130 } },
          h("span", null, "Narrator"),
          h("select", { value: voice || "", onChange: e => setVoice(e.target.value) },
            voices.map(v => h("option", { key: v.id, value: v.id }, voiceOptionText(v))))),
        h("label", { className: "field", style: { flex: "0 0 80px" } },
          h("span", null, "From Ch."),
          h("input", { value: startCh, onChange: e => setStartCh(e.target.value), placeholder: minCh || "1", inputMode: "numeric" })),
        h("label", { className: "field", style: { flex: "0 0 80px" } },
          h("span", null, "To Ch."),
          h("input", { value: endCh, onChange: e => setEndCh(e.target.value), placeholder: "end", inputMode: "numeric" }))),
      selectedVoice && h("div", { className: "voice-detail" },
        h("span", { className: "voice-name" }, selectedVoice.name || selectedVoice.id),
        h("span", { className: "mono" }, selectedVoice.id),
        ttsVoiceMeta(selectedVoice) && h("span", null, ttsVoiceMeta(selectedVoice)),
        prefVoice === selectedVoice.id ? h("span", { className: "chip voice-chip" }, "preferred") : null,
        defaultVoice === selectedVoice.id ? h("span", { className: "chip voice-chip" }, "default") : null,
        audioCoverage && h("span", null, `${selectedCoverage.have}/${audioCoverage.prose_chapters} chapters narrated`),
        (selectedVoice.description || selectedVoice.note) && h("span", { className: "voice-note" }, selectedVoice.description || selectedVoice.note)
      ),
      !running && est && h("div", { className: "muted", style: { fontSize: 12.5, marginTop: 10 } },
        est.estimated_units === 0
          ? "Every chapter in this range is already narrated in this voice."
          : `~${est.estimated_units} chapter${est.estimated_units === 1 ? "" : "s"} to narrate` +
            (est.capped ? " (capped this batch)" : "") +
            (est.unlimited ? "" : ` · ${est.remaining}/${est.limit} quota left this month`)),
      h("div", { className: "row", style: { gap: 8, marginTop: 10 } },
        running
          ? h("button", { className: "btn btn-ghost is-danger", onClick: cancel }, h(Icon, { name: "x", size: 14 }), "Cancel")
          : h("button", { className: "btn btn-primary", onClick: () => setPendingStart(narrationParams()), disabled: !voice },
              h(Icon, { name: "play", size: 14 }), "Start narrating")),
      job && h("div", { style: { marginTop: 12 } },
        h("div", { className: "narrate-progress" }, h("div", { className: "narrate-progress-fill", style: { width: pct + "%" } })),
        h("div", { className: "muted", style: { fontSize: 12.5, marginTop: 6 } },
          `${prog.done || 0} / ${prog.total || 0} narrated` +
          (prog.skipped ? ` · ${prog.skipped} skipped` : "") +
          (stopped === "quota" ? " · stopped: monthly quota reached" :
           stopped === "canceled" ? " · canceled" :
           job.status === "done" ? " · done" :
           job.status === "failed" ? " · failed" : ""))),
      job && job.status === "failed" && job.error && h("div", { className: "acct-err", style: { marginTop: 8 } }, job.error),
      msg && !job && h("div", { className: "muted", style: { fontSize: 12.5, marginTop: 8 } }, msg),
      h("p", { className: "muted", style: { fontSize: 12, marginTop: 10, marginBottom: 0 } },
        "Generates audio on the server and caches it for everyone. Capped per batch; re-run to continue a long book.")),
    pendingStart && h(CostConfirm, {
      novelId,
      action: "audiobook",
      params: pendingStart,
      title: "Narrate book",
      actionLabel: "Start narration",
      onCancel: () => setPendingStart(null),
      onConfirm: async () => { await start(pendingStart); setPendingStart(null); },
    })
  );
}

function NovelDetail({ novelId, novel, reloadNovel, openReader, nav, openLibrary, user }) {
  const [toc, setToc] = useState(null);    // null = loading
  const [adapters, setAdapters] = useState([]);
  const [addingSource, setAddingSource] = useState(false);
  const [editSourceId, setEditSourceId] = useState(null);
  const [editing, setEditing] = useState(false);
  const [bookmarks, setBookmarks] = useState([]);
  const [glossary, setGlossary] = useState([]);
  const [maxCh, setMaxCh] = useState("");
  const [msg, setMsg] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [audioCoverage, setAudioCoverage] = useState(null);   // Current shared narration coverage across all voices
  const [ttsVoices, setTtsVoices] = useState([]);
  const [pendingCost, setPendingCost] = useState(null);   // {action, params, title, actionLabel, run}
  const agyCapability = user && user.ai_backends && user.ai_backends.agy;
  const canAgyTranslate = !!(agyCapability && agyCapability.enabled && (agyCapability.workloads || []).includes("translate_batch"));
  const canAgyCodex = !!(agyCapability && agyCapability.enabled && (agyCapability.workloads || []).includes("codex_extract"));
  const [translateBackend, setTranslateBackend] = useState("auto");
  const [codexBackend, setCodexBackend] = useState("auto");
  const [codexFromChapter, setCodexFromChapter] = useState("");
  const [codexToChapter, setCodexToChapter] = useState("");

  useEffect(() => {
    const preferred = agyCapability && agyCapability.default_backend === "agy" ? "agy" : "api";
    setTranslateBackend(canAgyTranslate ? preferred : "auto");
    setCodexBackend(canAgyCodex ? preferred : "auto");
  }, [user && user.id, agyCapability && agyCapability.default_backend,
      canAgyTranslate, canAgyCodex]);

  const loadToc = useCallback(() => {
    if (novelId == null) return;
    window.API.chapters(novelId).then(setToc).catch(() => setToc([]));
  }, [novelId]);
  // Which chapters already have any current shared narration, plus the voices that cover them.
  // Drives voice-agnostic TOC headphones and refreshes when a narration batch finishes.
  const loadAudioCoverage = useCallback(() => {
    if (novelId == null) return;
    window.API.audioCoverage(novelId).then(setAudioCoverage).catch(() => setAudioCoverage(null));
  }, [novelId, user && user.id]);
  const loadBookmarks = useCallback(() => {
    if (novelId == null) return;
    window.API.bookmarks(novelId).then(setBookmarks).catch(() => setBookmarks([]));
  }, [novelId]);
  const loadGlossary = useCallback(() => {
    if (novelId == null) return;
    window.API.glossary(novelId).then(setGlossary).catch(() => setGlossary([]));
  }, [novelId]);

  useEffect(() => { loadToc(); loadBookmarks(); loadGlossary(); loadAudioCoverage(); }, [loadToc, loadBookmarks, loadGlossary, loadAudioCoverage]);
  useEffect(() => { window.API.adapters().then(setAdapters).catch(() => setAdapters([])); }, []);
  useEffect(() => {
    window.API.ttsVoices().then(r => setTtsVoices(r.voices || [])).catch(() => setTtsVoices([]));
  }, []);

  if (!novel) return React.createElement("div", { className: "page" }, React.createElement(Loading, { label: "Loading novel…" }));

  const progress = novel.progress || {};
  const startAt = progress.last_chapter != null ? progress.last_chapter : (novel.min_chapter || 1);
  const hasChapters = (novel.chapter_count || 0) > 0;
  const hasRaw = (novel.sources || []).some(s => s.is_raw);
  const canEdit = !!novel.can_edit;

  async function doScrape() {
    setMsg("Scraping started in the background…");
    try {
      await window.API.scrape(novelId, { max_chapters: maxCh.trim() ? parseInt(maxCh) : null });
    } catch (e) {
      setMsg("Scrape failed: " + (e.message || "error"));
    }
  }

  function codexRangeParams() {
    const fromText = codexFromChapter.trim();
    const toText = codexToChapter.trim();
    const from = fromText ? Number(fromText) : null;
    const to = toText ? Number(toText) : null;
    if ((fromText && !Number.isFinite(from)) || (toText && !Number.isFinite(to))) {
      throw new Error("Codex chapter bounds must be valid numbers.");
    }
    if (from != null && to != null && from > to) {
      throw new Error("The first codex chapter cannot be after the final chapter.");
    }
    return { from_chapter: from, to_chapter: to };
  }

  async function runBuildCodex(params) {
    setMsg("Codex build started in the background (chunk → embed → extract)…");
    try { const r = await window.API.codexBuild(novelId, { ...params, ai_backend: codexBackend });
      setMsg(`Codex build queued on ${(r.execution_backend || "api").toUpperCase()}${r.model ? ` · ${r.model}` : ""}.`); reloadNovel(); }
    catch (e) { setMsg("Codex build failed: " + (e.message || "error")); }
  }

  async function runTranslate() {
    setMsg("Translation started in the background (glossary-consistent)…");
    try { const r = await window.API.translate(novelId, { ai_backend: translateBackend });
      setMsg(`Translation queued on ${(r.execution_backend || "api").toUpperCase()}${r.model ? ` · ${r.model}` : ""}.`); }
    catch (e) { setMsg("Translate failed: " + (e.message || "error")); }
  }

  // Expensive actions confirm their estimated cost (units + quota remaining) first.
  const buildCodex = () => {
    let params;
    try { params = codexRangeParams(); }
    catch (e) { setMsg(e.message); return; }
    setPendingCost({
      action: "codex_build", params,
      title: novel.codex_enabled ? "Extend codex" : "Build codex",
      actionLabel: "Start build", run: () => runBuildCodex(params),
    });
  };
  const doTranslate = () => setPendingCost({
    action: "translate", params: {},
    title: "Translate raw chapters", actionLabel: "Start translation", run: runTranslate,
  });

  async function doSeedGlossary() {
    try { const r = await window.API.seedGlossary(novelId); setMsg(`Seeded ${r.seeded} glossary terms from the codex.`); loadGlossary(); }
    catch (e) { setMsg("Seed failed: " + (e.message || "error")); }
  }

  async function doDelete() {
    if (deleting) return;
    setDeleting(true);
    try {
      await window.API.deleteNovel(novelId);
      setConfirmDelete(false);
      openLibrary();   // novel is gone — leave the detail view
    } catch (e) {
      setMsg("Delete failed: " + (e.message || "error"));
      setDeleting(false);
    }
  }

  return React.createElement("div", { className: "page" },
    // header
    editing
      ? React.createElement(NovelEditForm, { novel, onSaved: () => { setEditing(false); reloadNovel(); }, onCancel: () => setEditing(false), onRequestDelete: () => setConfirmDelete(true) })
      : React.createElement("div", { className: "novel-hero" },
        React.createElement("div", { className: "novel-hero-cover" },
          novel.cover_url ? React.createElement("img", { src: novel.cover_url, alt: "" })
            : React.createElement("div", { className: "novel-cover-ph lg" }, React.createElement(Icon, { name: "book", size: 40 }))
        ),
        React.createElement("div", { className: "novel-hero-body" },
          React.createElement("div", { className: "row", style: { gap: 10, alignItems: "flex-start" } },
            React.createElement("h1", { className: "serif", style: { margin: "0 0 6px", flex: 1 } }, novel.title),
            canEdit && React.createElement("button", { className: "icon-btn", onClick: () => setEditing(true), title: "Edit novel" },
              React.createElement(Icon, { name: "edit", size: 17 }))
          ),
          novel.author && React.createElement("div", { className: "muted" }, novel.author),
          novel.provenance && React.createElement(ProvenanceBadges, { provenance: novel.provenance, className: "hero-prov" }),
          novel.description && React.createElement("p", { style: { color: "var(--ink-2)", lineHeight: 1.6, maxWidth: "60ch" } }, novel.description),
          React.createElement("div", { className: "row", style: { gap: 10, marginTop: 14, flexWrap: "wrap" } },
            hasChapters && React.createElement("button", { className: "btn btn-primary", onClick: () => openReader(startAt) },
              React.createElement(Icon, { name: "book", size: 16 }),
              progress.last_chapter != null ? `Continue · Ch. ${startAt}` : "Start reading"),
            React.createElement("span", { className: "chip mono" }, `${novel.chapter_count} chapters`),
            novel.max_chapter != null && React.createElement("span", { className: "chip mono" }, `ch. ${novel.min_chapter}–${novel.max_chapter}`),
            novel.codex_enabled && React.createElement("button", { className: "btn btn-ghost", onClick: () => nav("browse") },
              React.createElement(Icon, { name: "compass", size: 16 }), "Open codex"),
            hasChapters && React.createElement(NarrateBookControl, { novelId, novel, user, audioCoverage, onChange: loadAudioCoverage }),
            canEdit && React.createElement(VisibilityControl, {
              novel, reloadNovel, isAdmin: !!(user && user.role === "admin"),
            }),
            canEdit && React.createElement(ContributionPolicyControl, { novel, reloadNovel })
          ),
          React.createElement(ShelfTagsControls, { novel, reloadNovel })
        )
      ),

    msg && React.createElement("div", { className: "card", style: { padding: "10px 16px", marginBottom: 16, fontSize: 13.5 } }, msg),

    // sources + scrape
    React.createElement("div", { className: "novel-cols" },
      React.createElement("div", null,
        React.createElement("p", { className: "section-eyebrow" }, "Sources"),
        React.createElement("div", { className: "card", style: { padding: 12 } },
          (novel.sources || []).map(s => React.createElement("div", { key: s.id },
            React.createElement("div", { className: "source-row" },
              React.createElement("div", { className: "grow" },
                React.createElement("div", { style: { fontWeight: 600 } }, s.label || s.adapter, s.is_raw && React.createElement("span", { className: "chip", style: { marginLeft: 8 } }, "raw · " + s.language)),
                React.createElement("div", { className: "muted", style: { fontSize: 12.5, wordBreak: "break-all" } }, s.start_url)
              ),
              s.chapter_offset ? React.createElement("span", { className: "chip mono" }, `${s.chapter_offset > 0 ? "+" : ""}${s.chapter_offset}`) : null,
              canEdit && React.createElement("button", { className: "icon-btn", title: "Edit offset", onClick: () => setEditSourceId(editSourceId === s.id ? null : s.id) },
                React.createElement(Icon, { name: "edit", size: 15 }))
            ),
            canEdit && editSourceId === s.id && React.createElement(EditSourceForm, {
              novelId, source: s,
              onCancel: () => setEditSourceId(null),
              onSaved: (r) => {
                setEditSourceId(null);
                setMsg(r && r.renumbered ? `Renumbered ${r.renumbered} chapters to the new offset.` : "Source updated.");
                reloadNovel(); loadToc();
              },
            })
          )),
          (novel.sources || []).length === 0 && React.createElement("div", { className: "muted", style: { padding: 8 } }, "No sources yet."),
          canEdit && !addingSource && React.createElement("button", { className: "btn btn-ghost", style: { marginTop: 8 }, onClick: () => setAddingSource(true) },
            React.createElement(Icon, { name: "sparkles", size: 15 }), "Add source")
        ),
        canEdit && addingSource && React.createElement(AddSourceForm, {
          novelId, adapters, onCancel: () => setAddingSource(false),
          onAdded: () => { setAddingSource(false); reloadNovel(); },
        })
      ),
      canEdit && React.createElement("div", null,
        React.createElement("p", { className: "section-eyebrow" }, "Pipeline"),
        React.createElement("div", { className: "card", style: { padding: 16 } },
          React.createElement("div", { className: "row", style: { gap: 10, alignItems: "flex-end", flexWrap: "wrap" } },
            React.createElement("label", { className: "field", style: { flex: "0 0 130px" } },
              React.createElement("span", null, "Max chapters"),
              React.createElement("input", { value: maxCh, onChange: e => setMaxCh(e.target.value), placeholder: "(all)", inputMode: "numeric" })
            ),
            React.createElement("button", { className: "btn btn-primary", onClick: doScrape },
              React.createElement(Icon, { name: "refresh", size: 15 }), "Scrape"),
            React.createElement("button", { className: "btn btn-ghost", onClick: loadToc },
              React.createElement(Icon, { name: "refresh", size: 15 }), "Refresh TOC")
          ),
          hasRaw && React.createElement("div", { style: { marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 } },
            canAgyTranslate && React.createElement("label", { className: "field", style: { maxWidth: 300, marginBottom: 10 } },
              React.createElement("span", null, "AI backend"),
              React.createElement("select", { value: translateBackend, onChange: e => setTranslateBackend(e.target.value) },
                React.createElement("option", { value: "agy" }, "Antigravity — local subscription queue"),
                React.createElement("option", { value: "api" }, "API — provider usage"))),
            React.createElement("div", { className: "row", style: { gap: 10, flexWrap: "wrap" } },
              React.createElement("button", { className: "btn btn-ghost", onClick: doTranslate },
                React.createElement(Icon, { name: "refresh", size: 15 }), "Translate raw chapters"),
              novel.codex_enabled && React.createElement("button", { className: "btn btn-ghost", onClick: doSeedGlossary },
                React.createElement(Icon, { name: "merge", size: 15 }), "Seed glossary from codex")),
            React.createElement("p", { className: "muted", style: { fontSize: 12.5, marginTop: 8, marginBottom: 0 } },
              "Reading already translates on demand; this pre-translates the whole raw source.")
          ),
          React.createElement("div", { style: { marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 14 } },
            React.createElement("div", { className: "row", style: { gap: 10, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 10 } },
              canAgyCodex && React.createElement("label", { className: "field", style: { flex: "1 1 250px", maxWidth: 300 } },
                React.createElement("span", null, "AI backend"),
                React.createElement("select", { value: codexBackend, onChange: e => setCodexBackend(e.target.value) },
                  React.createElement("option", { value: "agy" }, "Antigravity — local subscription queue"),
                  React.createElement("option", { value: "api" }, "API — provider usage"))),
              React.createElement("label", { className: "field", style: { flex: "0 0 105px" } },
                React.createElement("span", null, "From chapter"),
                React.createElement("input", { type: "number", step: "any", value: codexFromChapter,
                  onChange: e => setCodexFromChapter(e.target.value), placeholder: novel.min_chapter != null ? String(novel.min_chapter) : "first" })),
              React.createElement("label", { className: "field", style: { flex: "0 0 115px" } },
                React.createElement("span", null, "Through chapter"),
                React.createElement("input", { type: "number", step: "any", value: codexToChapter,
                  onChange: e => setCodexToChapter(e.target.value), placeholder: "latest" })),
              React.createElement("button", { className: "btn btn-ghost", onClick: buildCodex },
                React.createElement(Icon, { name: "brain", size: 15 }), novel.codex_enabled ? "Extend codex" : "Build codex")),
            React.createElement("p", { className: "muted", style: { fontSize: 12.5, marginTop: 8, marginBottom: 0 } },
              "Builds the spoiler-safe knowledge base from scraped chapters. Leave both bounds blank for every available chapter; completed chapters are skipped.")
          )
        )
      )
    ),

    // durable background jobs (scrape / codex / translation) for this novel
    canEdit && React.createElement(JobCenter, { novelId }),

    // pipeline health panel (owner/admin operational surface)
    canEdit && React.createElement(NovelHealthPanel, { novelId, ttsVoices }),

    // translation glossary (raw novels)
    canEdit && (hasRaw || glossary.length > 0) && React.createElement(GlossaryEditor, { novelId, glossary, reload: loadGlossary }),

    // contribute-back inbox (owner/admin)
    canEdit && React.createElement(ContributionsInbox, { novelId, reloadNovel }),

    // reader tag-suggestion inbox (owner/admin)
    canEdit && React.createElement(TagSuggestionsInbox, { novelId, reloadNovel }),

    // bookmarks
    bookmarks.length > 0 && React.createElement(React.Fragment, null,
      React.createElement("p", { className: "section-eyebrow", style: { marginTop: 28 } }, "Bookmarks"),
      React.createElement("div", { className: "card toc" },
        bookmarks.map(b => React.createElement("div", { key: b.id, className: "toc-row", style: { cursor: "default" } },
          React.createElement("button", { className: "bm-jump", onClick: () => openReader(b.chapter) },
            React.createElement(Icon, { name: "book", size: 14, className: "muted" }),
            React.createElement("span", { className: "toc-num mono" }, `Ch. ${b.chapter}`),
            React.createElement("span", { className: "toc-title" }, b.note || "Bookmarked")
          ),
          React.createElement("button", {
            className: "icon-btn", title: "Remove bookmark",
            onClick: async () => { await window.API.delBookmark(novelId, b.id); loadBookmarks(); },
          }, React.createElement(Icon, { name: "x", size: 15 }))
        ))
      )
    ),

    // TOC
    React.createElement("p", { className: "section-eyebrow", style: { marginTop: 28 } }, "Contents"),
    toc == null
      ? React.createElement(Loading, { label: "Loading chapters…" })
      : toc.length === 0
        ? React.createElement(EmptyState, { icon: "book", title: "No chapters yet", body: "Use Scrape above to fetch chapters from the source." })
        : React.createElement("div", { className: "card toc" },
            React.createElement(VolumeTOC, {
              toc, currentNumber: progress.last_chapter, onOpen: openReader,
              audioCoverage, voices: ttsVoices,
              preferredVoice: user && user.prefs && user.prefs.tts && user.prefs.tts.voice,
            })),

    confirmDelete && React.createElement(ConfirmDialog, {
      title: `Delete “${novel.title}”?`,
      requireText: novel.title,
      confirmLabel: "Delete permanently",
      busy: deleting,
      onCancel: () => setConfirmDelete(false),
      onConfirm: doDelete,
      body: React.createElement("div", null,
        React.createElement("p", { className: "muted", style: { fontSize: 13.8, lineHeight: 1.55, margin: "0 0 8px" } },
          "This permanently removes the novel and everything tied to it — there's no undo."),
        React.createElement("ul", { className: "muted", style: { fontSize: 13.2, lineHeight: 1.6, margin: 0, paddingLeft: 18 } },
          React.createElement("li", null, `${novel.chapter_count || 0} chapters (text + translations)`),
          React.createElement("li", null, "the codex, bookmarks, glossary and reading progress"),
          React.createElement("li", null, "imported files, covers and illustrations on disk"))
      ),
    }),

    pendingCost && React.createElement(CostConfirm, {
      novelId, action: pendingCost.action, params: pendingCost.params,
      title: pendingCost.title, actionLabel: pendingCost.actionLabel,
      onCancel: () => setPendingCost(null),
      onConfirm: async () => { await pendingCost.run(); setPendingCost(null); },
    })
  );
}

window.NovelDetail = NovelDetail;
