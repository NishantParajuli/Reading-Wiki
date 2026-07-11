/* Tag vocabulary editing: radio groups + genre checkboxes, the reader
   "suggest tags" flow, and the shelf segmented control. */
import React, { useState } from "react";
import { API } from "../lib/api.js";
import { Icon } from "../components/Icon.jsx";
import { Button, Chip, SegmentedControl } from "../components/ui.jsx";
import { useToast } from "../components/toast.jsx";
import { SHELF_LABELS, SHELF_ORDER, STATUS_TAG_LABELS, STATUS_TAG_RADIO_GROUPS, GENRE_TAGS } from "../lib/constants.js";

/* Toggle a tag with radio (one-per-group) or checkbox semantics. */
export function toggleTag(tags, t, group) {
  if (tags.includes(t)) return tags.filter(x => x !== t);
  if (group) return [...tags.filter(x => !group.tags.includes(x)), t];
  return [...tags, t];
}

export function TagEditor({ tags, onToggle, disabled }) {
  return (
    <div className="tag-editor">
      {STATUS_TAG_RADIO_GROUPS.map(g => (
        <div key={g.id} className="tag-group">
          <span className="st-label">{g.label}</span>
          <div className="st-tags">
            {g.tags.map(t => (
              <button key={t} type="button" disabled={disabled}
                      className={"tag-toggle radio" + (tags.includes(t) ? " on" : "")}
                      onClick={() => onToggle(t, g)}>
                {STATUS_TAG_LABELS[t]}
              </button>
            ))}
          </div>
        </div>
      ))}
      <div className="tag-group">
        <span className="st-label">Genres</span>
        <div className="st-tags">
          {GENRE_TAGS.map(t => (
            <button key={t} type="button" disabled={disabled}
                    className={"tag-toggle" + (tags.includes(t) ? " on" : "")}
                    onClick={() => onToggle(t, null)}>
              {STATUS_TAG_LABELS[t]}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* Reader-facing: propose a tag set to the owner/admin of a shared novel. */
export function TagSuggestForm({ novel, current, onClose }) {
  const [tags, setTags] = useState(current || []);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();

  async function submit() {
    setBusy(true);
    try {
      await API.suggestTags(novel.id, tags, note);
      toast("Tag suggestion sent to the owner for review.", { tone: "ok" });
      onClose();
    } catch (e) {
      toast(e.message || "Couldn't send your suggestion.", { tone: "danger" });
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ padding: 14, marginTop: 10 }}>
      <p className="section-eyebrow" style={{ marginTop: 0 }}>Suggest tags</p>
      <TagEditor tags={tags} onToggle={(t, g) => setTags(prev => toggleTag(prev, t, g))} disabled={busy} />
      <textarea className="tt-textarea" rows={2} style={{ marginTop: 10 }} value={note}
                placeholder="Optional note for the owner…" onChange={e => setNote(e.target.value)} />
      <div className="row" style={{ gap: 8, marginTop: 10 }}>
        <Button variant="primary" icon="send" disabled={busy} loading={busy} onClick={submit}>Send suggestion</Button>
        <Button variant="ghost" disabled={busy} onClick={onClose}>Cancel</Button>
      </div>
    </div>
  );
}

/* Shelf segmented control (any reader). Tap the active shelf to clear it. */
export function ShelfControl({ novel, reloadNovel }) {
  const [busy, setBusy] = useState(false);
  const { toast } = useToast();
  const shelf = novel.shelf || "";

  const setShelf = async (s) => {
    if (busy) return;
    const next = shelf === s ? "" : s;
    setBusy(true);
    try { await API.updateNovel(novel.id, { shelf: next }); reloadNovel(); }
    catch (e) { toast(e.message || "Couldn't change the shelf.", { tone: "danger" }); }
    finally { setBusy(false); }
  };

  return (
    <SegmentedControl fit ariaLabel="Shelf" value={shelf}
      onChange={setShelf}
      options={SHELF_ORDER.map(s => ({ value: s, label: SHELF_LABELS[s] }))} />
  );
}

export function TagChips({ novel }) {
  const tags = novel.status_tags || [];
  if (tags.length === 0) return null;
  return (
    <>
      {tags.map(t => <Chip key={t}>{STATUS_TAG_LABELS[t] || t}</Chip>)}
    </>
  );
}
