/* Tag vocabulary editing: radio groups + genre checkboxes, the reader
   "suggest tags" flow, and the shelf segmented control. Toggles are real
   pressed-state buttons; the check springs in when a tag lights up. */
import React, { useState } from "react";
import { catalogApi } from "./api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, SegmentedControl } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { SHELF_LABELS, SHELF_ORDER, STATUS_TAG_LABELS, STATUS_TAG_RADIO_GROUPS, GENRE_TAGS } from "../../lib/constants.js";

/* Toggle a tag with radio (one-per-group) or checkbox semantics. */
export function toggleTag(tags, t, group) {
  if (tags.includes(t)) return tags.filter(x => x !== t);
  if (group) return [...tags.filter(x => !group.tags.includes(x)), t];
  return [...tags, t];
}

function TagToggle({ on, radio, disabled, onClick, children }) {
  return (
    <button type="button" disabled={disabled} aria-pressed={on}
            className={"tag-toggle" + (radio ? " radio" : "") + (on ? " on" : "")}
            onClick={onClick}>
      <span className="tt-check" aria-hidden="true"><Icon name="check" size={11} sw={2.6} /></span>
      <span className="tt-label">{children}</span>
    </button>
  );
}

export function TagEditor({ tags, onToggle, disabled }) {
  return (
    <div className="tag-editor">
      {STATUS_TAG_RADIO_GROUPS.map(g => (
        <div key={g.id} className="tag-group" role="group" aria-label={g.label}>
          <span className="tag-group-label" aria-hidden="true">{g.label}</span>
          <div className="st-tags">
            {g.tags.map(t => (
              <TagToggle key={t} radio on={tags.includes(t)} disabled={disabled} onClick={() => onToggle(t, g)}>
                {STATUS_TAG_LABELS[t]}
              </TagToggle>
            ))}
          </div>
        </div>
      ))}
      <div className="tag-group" role="group" aria-label="Genres">
        <span className="tag-group-label" aria-hidden="true">Genres</span>
        <div className="st-tags">
          {GENRE_TAGS.map(t => (
            <TagToggle key={t} on={tags.includes(t)} disabled={disabled} onClick={() => onToggle(t, null)}>
              {STATUS_TAG_LABELS[t]}
            </TagToggle>
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
      await catalogApi.suggestTags(novel.id, tags, note);
      toast("Tag suggestion sent to the owner for review.", { tone: "ok" });
      onClose();
    } catch (e) {
      toast(e.message || "Couldn't send your suggestion.", { tone: "danger" });
      setBusy(false);
    }
  }

  return (
    <div className="tag-suggest">
      <div className="tag-suggest-head">
        <span className="tag-suggest-icon" aria-hidden="true"><Icon name="sparkles" size={15} /></span>
        <div>
          <p className="tag-suggest-title">Suggest tags</p>
          <p className="tag-suggest-sub">The owner reviews your suggestion before anything changes.</p>
        </div>
      </div>
      <TagEditor tags={tags} onToggle={(t, g) => setTags(prev => toggleTag(prev, t, g))} disabled={busy} />
      <label className="field tag-suggest-note">
        <span>Note for the owner <em>(optional)</em></span>
        <textarea rows={2} value={note} placeholder="Why these tags fit…" onChange={e => setNote(e.target.value)} disabled={busy} />
      </label>
      <div className="row" style={{ gap: 8 }}>
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
    try { await catalogApi.updateNovel(novel.id, { shelf: next }); reloadNovel(); }
    catch (e) { toast(e.message || "Couldn't change the shelf.", { tone: "danger" }); }
    finally { setBusy(false); }
  };

  return (
    <SegmentedControl fit ariaLabel="Shelf" value={shelf} className={"shelf-seg" + (busy ? " is-busy" : "")}
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
