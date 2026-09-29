/* ============================================================
   Admin → Users. Rich rows (orb, identity, role/status chips, quota
   meters) with the quota + AI-access editor unfolding in place.
   Self-guards: you can't change your own status, demote yourself or
   delete your own account (the server also guards the last admin).
   ============================================================ */
import React, { useCallback, useEffect, useState } from "react";

import { adminApi } from "./api.js";
import { MiniMeter } from "./AdminParts.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, Skeleton, UserAvatar } from "../../components/ui.jsx";
import { ConfirmDialog } from "../../components/overlay.jsx";
import { useToast } from "../../components/toast.jsx";
import { AnimatePresence, motion, springs } from "../../motion/index.js";

const QUOTAS = [
  ["translated_chapters", "Chapters"],
  ["ocr_pages", "OCR pages"],
  ["codex_builds", "Codex builds"],
  ["tts_chapters", "Narration"],
];
const METER_LABELS = { translated_chapters: "Chapters", ocr_pages: "OCR", codex_builds: "Codex", tts_chapters: "Audio" };
const STATUS_TONE = { active: "ok", suspended: "warn", banned: "danger" };

function blankToNull(v) {
  const s = String(v).trim();
  if (s === "") return null;
  const n = Number(s);
  return Number.isNaN(n) ? null : Math.max(0, Math.round(n));
}

/* The in-place editor: monthly limits beside the AI backend policy. */
function AccessEditor({ u, busy, q, setQ, ai, setAi, onSaveQuotas, onSaveAi, onRevokeAi }) {
  const policy = u.ai_backend_policy || {};
  const toggleWorkload = (key, field) => setAi(s => ({
    ...s,
    [field]: s[field].includes(key) ? s[field].filter(x => x !== key) : [...s[field], key],
  }));
  return (
    <div className="adm-edit" id={`adm-edit-${u.id}`}>
      <section className="adm-edit-panel" aria-labelledby={`adm-q-${u.id}`}>
        <header className="adm-edit-head">
          <span className="adm-edit-ico" aria-hidden="true"><Icon name="sliders" size={15} /></span>
          <div>
            <h3 id={`adm-q-${u.id}`}>Monthly limits</h3>
            <p>Per-user overrides. Leave a field blank to use the default.</p>
          </div>
        </header>
        <div className="adm-quota-grid">
          {QUOTAS.map(([k, lbl]) => (
            <label key={k} className="field adm-quota">
              <span>{lbl}</span>
              <input value={q[k]} inputMode="numeric" placeholder="default"
                     onChange={e => setQ(s => ({ ...s, [k]: e.target.value }))} />
              <small className="field-help">Now {Number(u.limits && u.limits[k] || 0).toLocaleString()}</small>
            </label>
          ))}
        </div>
        <div className="adm-edit-actions">
          <Button variant="primary" size="sm" disabled={busy} onClick={onSaveQuotas}>Save limits</Button>
        </div>
      </section>

      <section className="adm-edit-panel" aria-labelledby={`adm-ai-${u.id}`}>
        <header className="adm-edit-head">
          <span className="adm-edit-ico" aria-hidden="true"><Icon name="sparkles" size={15} /></span>
          <div>
            <h3 id={`adm-ai-${u.id}`}>AI access</h3>
            <p>Subscription backends this account may run work on.</p>
          </div>
        </header>
        <div className="adm-switches">
          <label className="adm-switch">
            <input type="checkbox" role="switch" checked={ai.agy_enabled}
                   onChange={e => setAi(s => ({ ...s, agy_enabled: e.target.checked, default_backend: (!e.target.checked && s.default_backend === "agy") ? "api" : s.default_backend }))} />
            <span className="adm-switch-track" aria-hidden="true"><span /></span>
            AGY access
          </label>
          <label className="adm-switch">
            <input type="checkbox" role="switch" checked={ai.openai_codex_enabled}
                   onChange={e => setAi(s => ({ ...s, openai_codex_enabled: e.target.checked, default_backend: (!e.target.checked && s.default_backend === "openai_codex") ? "api" : s.default_backend }))} />
            <span className="adm-switch-track" aria-hidden="true"><span /></span>
            OpenAI Codex access
          </label>
          <label className="adm-switch">
            <input type="checkbox" role="switch" checked={ai.fallback_to_api}
                   onChange={e => setAi(s => ({ ...s, fallback_to_api: e.target.checked }))} />
            <span className="adm-switch-track" aria-hidden="true"><span /></span>
            Allow paid API fallback
          </label>
        </div>
        <div className="adm-ai-grid">
          <label className="field">
            <span>Default backend</span>
            <select value={ai.default_backend} disabled={!ai.agy_enabled && !ai.openai_codex_enabled}
                    onChange={e => setAi(s => ({ ...s, default_backend: e.target.value }))}>
              <option value="api">API</option>
              {ai.agy_enabled && <option value="agy">Antigravity</option>}
              {ai.openai_codex_enabled && <option value="openai_codex">OpenAI Codex</option>}
            </select>
          </label>
          <label className="field">
            <span>AGY concurrent</span>
            <input type="number" min="1" max="4" value={ai.max_concurrent_agy_jobs}
                   onChange={e => setAi(s => ({ ...s, max_concurrent_agy_jobs: Number(e.target.value) }))} />
          </label>
          <label className="field">
            <span>Codex concurrent</span>
            <input type="number" min="1" max="4" value={ai.max_concurrent_openai_codex_jobs}
                   onChange={e => setAi(s => ({ ...s, max_concurrent_openai_codex_jobs: Number(e.target.value) }))} />
          </label>
        </div>
        <div className="adm-workloads">
          <fieldset disabled={!ai.agy_enabled}>
            <legend>Antigravity workloads</legend>
            {[["translate_batch", "Batch translation"], ["codex_extract", "Codex extraction"]].map(([key, label]) => (
              <label key={key} className="check">
                <input type="checkbox" checked={ai.agy_workloads.includes(key)} onChange={() => toggleWorkload(key, "agy_workloads")} />
                {label}
              </label>
            ))}
          </fieldset>
          <fieldset disabled={!ai.openai_codex_enabled}>
            <legend>OpenAI Codex workloads</legend>
            {[["translate_batch", "Codex batch translation"], ["codex_extract", "Codex extraction"]].map(([key, label]) => (
              <label key={`openai-${key}`} className="check">
                <input type="checkbox" checked={ai.openai_codex_workloads.includes(key)} onChange={() => toggleWorkload(key, "openai_codex_workloads")} />
                {label}
              </label>
            ))}
          </fieldset>
        </div>
        <label className="field">
          <span>Admin notes</span>
          <input value={ai.notes} onChange={e => setAi(s => ({ ...s, notes: e.target.value }))} placeholder="owner pilot" />
        </label>
        <div className="adm-edit-actions">
          <Button variant="primary" size="sm" disabled={busy} onClick={onSaveAi}>Save AI access</Button>
          {policy.policy_version && <Button variant="ghost" size="sm" className="is-danger" disabled={busy} onClick={onRevokeAi}>Revoke AI access</Button>}
          <span className="adm-policy-meta">
            <span><b>{policy.active_jobs || 0}</b> AGY active</span>
            <span><b>{policy.openai_codex_active_jobs || 0}</b> Codex active</span>
            <span>policy v{policy.policy_version || "—"}</span>
          </span>
        </div>
      </section>
    </div>
  );
}

function UserRow({ u, me, onChanged, i }) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const overrides = u.quota_overrides || {};
  const [q, setQ] = useState({
    translated_chapters: overrides.translated_chapters ?? "",
    ocr_pages: overrides.ocr_pages ?? "",
    codex_builds: overrides.codex_builds ?? "",
    tts_chapters: overrides.tts_chapters ?? "",
  });
  const [confirmDel, setConfirmDel] = useState(false);
  const initialPolicy = u.ai_backend_policy || {};
  const [ai, setAi] = useState({
    agy_enabled: !!initialPolicy.agy_enabled,
    openai_codex_enabled: !!initialPolicy.openai_codex_enabled,
    default_backend: initialPolicy.default_backend || "api",
    agy_workloads: initialPolicy.agy_workloads || [],
    openai_codex_workloads: initialPolicy.openai_codex_workloads || [],
    fallback_to_api: !!initialPolicy.fallback_to_api,
    max_concurrent_agy_jobs: initialPolicy.max_concurrent_agy_jobs || 1,
    max_concurrent_openai_codex_jobs: initialPolicy.max_concurrent_openai_codex_jobs || 1,
    notes: initialPolicy.notes || "",
  });
  const isSelf = me && u.id === me.id;

  // Rows stay mounted through the quiet refresh, so busy always clears.
  const patch = async (body) => {
    setBusy(true);
    try { await adminApi.updateUser(u.id, body); await onChanged(); }
    catch (e) { toast(e.message || "Update failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  };
  const saveQuotas = () => patch({
    quota_translated_chapters: blankToNull(q.translated_chapters),
    quota_ocr_pages: blankToNull(q.ocr_pages),
    quota_codex_builds: blankToNull(q.codex_builds),
    quota_tts_chapters: blankToNull(q.tts_chapters),
  });
  const del = async () => {
    setBusy(true);
    try { await adminApi.deleteUser(u.id); setConfirmDel(false); await onChanged(); }
    catch (e) { toast(e.message || "Delete failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  };
  const saveAi = async () => {
    setBusy(true);
    try { await adminApi.saveAiPolicy(u.id, ai); await onChanged(); }
    catch (e) { toast(e.message || "AI backend update failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  };
  const revokeAi = async () => {
    setBusy(true);
    try { await adminApi.revokeAiPolicy(u.id); await onChanged(); }
    catch (e) { toast(e.message || "AI backend revoke failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  };

  const name = u.display_name || u.username;
  const joined = u.created_at ? new Date(u.created_at).toLocaleDateString(undefined, { year: "numeric", month: "short" }) : null;
  const statusTone = STATUS_TONE[u.status] || "danger";
  const usage = u.usage || {};
  const limits = u.limits || {};
  return (
    <article className={"adm-user rise" + (open ? " is-open" : "") + (busy ? " is-busy" : "")} style={{ "--i": Math.min(i, 10) }}
             aria-label={`${name} (@${u.username})`} data-spotlight="">
      <div className="adm-user-main">
        <UserAvatar url={u.avatar_url} name={name} size={46} className="adm-user-orb" />
        <div className="adm-user-id">
          <div className="adm-user-name">
            <span className="adm-user-display">{name}</span>
            {isSelf && <Chip className="adm-chip-you">you</Chip>}
            {u.role === "admin" && <Chip tone="accent" icon="shield">admin</Chip>}
            {initialPolicy.agy_enabled && <Chip tone="info" icon="sparkles">AGY</Chip>}
            {initialPolicy.openai_codex_enabled && <Chip tone="info" icon="cpu">Codex</Chip>}
          </div>
          <div className="adm-user-sub">
            <span>@{u.username}</span>
            {u.email && <span className="adm-user-email">{u.email}</span>}
            {!u.email_verified && <span className="adm-unverified">unverified</span>}
          </div>
          {(joined || u.novels_owned != null) && (
            <div className="adm-user-sub adm-user-facts">
              {joined && <span>Joined {joined}</span>}
              {u.novels_owned != null && <span>{u.novels_owned} {u.novels_owned === 1 ? "novel" : "novels"}</span>}
            </div>
          )}
        </div>
        <div className="adm-user-usage" aria-label="This month's usage">
          {Object.keys(METER_LABELS).map(k => (
            <MiniMeter key={k} label={METER_LABELS[k]} used={usage[k]} limit={limits[k]} owner={`@${u.username}`} />
          ))}
        </div>
        <div className="adm-user-ctl">
          <span className={`adm-status tone-${statusTone}`}>
            <span className="adm-status-dot" aria-hidden="true" />
            <select value={u.status} disabled={busy || isSelf} onChange={e => patch({ status: e.target.value })}
                    title="Account status" aria-label={`Account status for @${u.username}`}>
              {["active", "suspended", "banned"].map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <Icon name="chevronDown" size={13} className="adm-status-chev" />
          </span>
          <Button variant="ghost" size="sm" className="adm-role" disabled={busy || (isSelf && u.role === "admin")}
                  title={isSelf && u.role === "admin" ? "You can't demote yourself" : undefined}
                  onClick={() => patch({ role: u.role === "admin" ? "user" : "admin" })}>
            {u.role === "admin" ? "Demote" : "Make admin"}
          </Button>
          <button type="button" className={"icon-btn adm-expand" + (open ? " active" : "")} title="Quotas & AI access"
                  aria-label={`Quotas & AI access for @${u.username}`} aria-expanded={open} aria-controls={`adm-edit-${u.id}`}
                  onClick={() => setOpen(o => !o)}>
            <Icon name="sliders" size={16} />
          </button>
          <button type="button" className="icon-btn plain adm-delete" title={isSelf ? "You can't delete your own account" : "Delete user"}
                  aria-label={`Delete @${u.username}`} disabled={isSelf} onClick={() => setConfirmDel(true)}>
            <Icon name="trash" size={16} />
          </button>
        </div>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div key="editor" className="adm-edit-wrap"
                      initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0, transition: { duration: 0.24, ease: [0.55, 0, 1, 0.45] } }}
                      transition={springs.smooth}>
            <AccessEditor u={u} busy={busy} q={q} setQ={setQ} ai={ai} setAi={setAi}
                          onSaveQuotas={saveQuotas} onSaveAi={saveAi} onRevokeAi={revokeAi} />
          </motion.div>
        )}
      </AnimatePresence>
      {confirmDel && (
        <ConfirmDialog
          title={`Delete @${u.username}?`} requireText={u.username} confirmLabel="Delete user" busy={busy}
          onCancel={() => setConfirmDel(false)} onConfirm={del}
          body="This removes their account, library, progress, bookmarks and overlays. Novels they own become unowned. There's no undo." />
      )}
    </article>
  );
}

function RosterSummary({ users }) {
  const count = (fn) => users.filter(fn).length;
  const parts = [
    `${users.length} ${users.length === 1 ? "person" : "people"}`,
    `${count(x => x.role === "admin")} admin`,
    count(x => x.status === "suspended") ? `${count(x => x.status === "suspended")} suspended` : null,
    count(x => x.status === "banned") ? `${count(x => x.status === "banned")} banned` : null,
    count(x => !x.email_verified) ? `${count(x => !x.email_verified)} unverified` : null,
  ].filter(Boolean);
  return <p className="adm-roster" role="status">{parts.join(" · ")}</p>;
}

export function UsersTab({ me }) {
  const [users, setUsers] = useState(null);
  const [q, setQ] = useState("");
  const [shown, setShown] = useState("");
  // A quiet reload (after an edit) keeps the rows on screen while it refreshes.
  const load = useCallback((query, quiet) => {
    if (!quiet) setUsers(null);
    setShown(query || "");
    return adminApi.users(query || "").then(setUsers).catch(() => setUsers(false));
  }, []);
  useEffect(() => { load(""); }, [load]);

  return (
    <div className="adm-users">
      <div className="adm-toolbar">
        <form className="adm-search" onSubmit={e => { e.preventDefault(); load(q); }} role="search">
          <div className="search-box">
            <Icon name="search" size={16} />
            <input value={q} placeholder="Search email, username, name…" onChange={e => setQ(e.target.value)} aria-label="Search users" />
          </div>
          <Button variant="ghost" type="submit" icon="search">Search</Button>
        </form>
        {users && users.length > 0 && <RosterSummary users={users} />}
      </div>
      {users == null ? (
        <div className="adm-user-list" aria-busy="true">
          <span className="sr-only" role="status">Loading users…</span>
          {[0, 1, 2].map(k => <Skeleton key={k} height={84} style={{ borderRadius: 22 }} />)}
        </div>
      ) : users === false ? (
        <EmptyState icon="alert" title="Couldn't load users" body="The account list didn't arrive. Nothing was changed."
          primaryAction={<Button variant="ghost" icon="refresh" onClick={() => load(shown)}>Try again</Button>} />
      ) : users.length === 0 ? (
        <EmptyState icon="users" title="No users found"
          body={shown ? `Nobody matches “${shown}”.` : "No accounts yet."}
          primaryAction={shown ? <Button variant="ghost" icon="x" onClick={() => { setQ(""); load(""); }}>Clear search</Button> : null} />
      ) : (
        <div className="adm-user-list">
          {users.map((u, i) => <UserRow key={u.id} u={u} me={me} i={i} onChanged={() => load(shown, true)} />)}
        </div>
      )}
    </div>
  );
}
