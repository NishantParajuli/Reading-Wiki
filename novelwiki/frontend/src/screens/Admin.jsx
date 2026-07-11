/* ============================================================
   Admin (§6.12) — Users / Usage & cost / Moderation / Global jobs / AGY.
   Consistency pass over the old dashboard: same logic, v2 components,
   toasts instead of alert(), URL-synced tabs.
   ============================================================ */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { API } from "../lib/api.js";
import { useAuth } from "../App.jsx";
import { Icon } from "../components/Icon.jsx";
import { Button, Chip, EmptyState, Loading, PageHeader, StatTile, Tabs, UserAvatar } from "../components/ui.jsx";
import { ConfirmDialog } from "../components/overlay.jsx";
import { useToast } from "../components/toast.jsx";
import { useTitle } from "../lib/hooks.js";

const ADMIN_TABS = [
  { id: "users", label: "Users", icon: "users" },
  { id: "usage", label: "Usage & cost", icon: "database" },
  { id: "moderation", label: "Moderation", icon: "shield" },
  { id: "jobs", label: "Global jobs", icon: "spider" },
  { id: "agy", label: "Antigravity", icon: "sparkles" },
];

function blankToNull(v) {
  const s = String(v).trim();
  if (s === "") return null;
  const n = Number(s);
  return Number.isNaN(n) ? null : Math.max(0, Math.round(n));
}

/* ── Users ── */
function UserRow({ u, me, onChanged }) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState({
    translated_chapters: u.quota_overrides.translated_chapters ?? "",
    ocr_pages: u.quota_overrides.ocr_pages ?? "",
    codex_builds: u.quota_overrides.codex_builds ?? "",
    tts_chapters: u.quota_overrides.tts_chapters ?? "",
  });
  const [confirmDel, setConfirmDel] = useState(false);
  const initialPolicy = u.ai_backend_policy || {};
  const [ai, setAi] = useState({
    agy_enabled: !!initialPolicy.agy_enabled,
    default_backend: initialPolicy.default_backend || "api",
    agy_workloads: initialPolicy.agy_workloads || [],
    fallback_to_api: !!initialPolicy.fallback_to_api,
    max_concurrent_agy_jobs: initialPolicy.max_concurrent_agy_jobs || 1,
    notes: initialPolicy.notes || "",
  });
  const isSelf = me && u.id === me.id;

  const patch = async (body) => {
    setBusy(true);
    try { await API.admin.updateUser(u.id, body); onChanged(); }
    catch (e) { toast(e.message || "Update failed.", { tone: "danger" }); setBusy(false); }
  };
  const saveQuotas = () => patch({
    quota_translated_chapters: blankToNull(q.translated_chapters),
    quota_ocr_pages: blankToNull(q.ocr_pages),
    quota_codex_builds: blankToNull(q.codex_builds),
    quota_tts_chapters: blankToNull(q.tts_chapters),
  });
  const del = async () => {
    setBusy(true);
    try { await API.admin.deleteUser(u.id); setConfirmDel(false); onChanged(); }
    catch (e) { toast(e.message || "Delete failed.", { tone: "danger" }); setBusy(false); }
  };
  const saveAi = async () => {
    setBusy(true);
    try { await API.admin.saveAiPolicy(u.id, ai); onChanged(); }
    catch (e) { toast(e.message || "AI backend update failed.", { tone: "danger" }); setBusy(false); }
  };
  const revokeAi = async () => {
    setBusy(true);
    try { await API.admin.revokeAiPolicy(u.id); onChanged(); }
    catch (e) { toast(e.message || "AI backend revoke failed.", { tone: "danger" }); setBusy(false); }
  };
  const toggleWorkload = key => setAi(s => ({
    ...s,
    agy_workloads: s.agy_workloads.includes(key)
      ? s.agy_workloads.filter(x => x !== key) : [...s.agy_workloads, key],
  }));

  const statusTone = u.status === "active" ? "ok" : u.status === "suspended" ? "warn" : "danger";

  return (
    <>
      <div className="admin-user-row">
        <div className="admin-user-id">
          <UserAvatar url={u.avatar_url} name={u.display_name || u.username} size={30} />
          <div className="grow" style={{ minWidth: 0 }}>
            <div className="admin-user-name">
              {u.display_name || u.username}
              {u.role === "admin" && <Chip style={{ marginLeft: 6 }}>admin</Chip>}
              {initialPolicy.agy_enabled && <Chip tone="accent" style={{ marginLeft: 6 }}>AGY</Chip>}
            </div>
            <div className="muted admin-user-email">@{u.username} · {u.email}{u.email_verified ? "" : " · unverified"}</div>
          </div>
        </div>
        <div className="admin-user-usage muted mono">
          {u.usage.translated_chapters}/{u.limits.translated_chapters} ch · {u.usage.ocr_pages}/{u.limits.ocr_pages} ocr · {u.usage.codex_builds}/{u.limits.codex_builds} cdx · {u.usage.tts_chapters}/{u.limits.tts_chapters} tts
        </div>
        <Chip tone={statusTone}>{u.status}</Chip>
        <div className="admin-user-actions">
          <select className="shelf-select" value={u.status} disabled={busy || isSelf}
                  onChange={e => patch({ status: e.target.value })} title="Account status">
            {["active", "suspended", "banned"].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <Button variant="ghost" size="sm" disabled={busy || (isSelf && u.role === "admin")}
                  onClick={() => patch({ role: u.role === "admin" ? "user" : "admin" })}>
            {u.role === "admin" ? "Demote" : "Make admin"}
          </Button>
          <button className="icon-btn plain" title="Quotas & AI access" aria-label="Quotas & AI access" onClick={() => setOpen(o => !o)}>
            <Icon name="sliders" size={16} />
          </button>
          <button className="icon-btn plain" title="Delete user" aria-label="Delete user" disabled={isSelf} onClick={() => setConfirmDel(true)}>
            <Icon name="trash" size={16} />
          </button>
        </div>
      </div>
      {open && (
        <div className="admin-quota-edit card">
          <span className="muted" style={{ fontSize: "var(--text-xs)", flexBasis: "100%" }}>Per-user monthly limits (blank = default):</span>
          {[["translated_chapters", "Chapters"], ["ocr_pages", "OCR pages"], ["codex_builds", "Codex builds"], ["tts_chapters", "Narration"]].map(([k, lbl]) => (
            <label key={k} className="field" style={{ flex: "0 0 110px" }}>
              <span>{lbl}</span>
              <input value={q[k]} inputMode="numeric" placeholder="default"
                     onChange={e => setQ(s => ({ ...s, [k]: e.target.value }))} />
            </label>
          ))}
          <Button variant="primary" size="sm" disabled={busy} onClick={saveQuotas}>Save limits</Button>
          <div style={{ flexBasis: "100%", borderTop: "1px solid var(--border)", marginTop: 8, paddingTop: 12 }}>
            <div className="row wrap" style={{ gap: 12 }}>
              <label className="check">
                <input type="checkbox" checked={ai.agy_enabled}
                       onChange={e => setAi(s => ({ ...s, agy_enabled: e.target.checked, default_backend: e.target.checked ? s.default_backend : "api" }))} />
                AGY access
              </label>
              <label className="field">
                <span>Default backend</span>
                <select value={ai.default_backend} disabled={!ai.agy_enabled}
                        onChange={e => setAi(s => ({ ...s, default_backend: e.target.value }))}>
                  <option value="api">API</option><option value="agy">Antigravity</option>
                </select>
              </label>
              <label className="field">
                <span>Concurrent jobs</span>
                <input type="number" min="1" max="4" value={ai.max_concurrent_agy_jobs}
                       onChange={e => setAi(s => ({ ...s, max_concurrent_agy_jobs: Number(e.target.value) }))} />
              </label>
              <label className="check">
                <input type="checkbox" checked={ai.fallback_to_api}
                       onChange={e => setAi(s => ({ ...s, fallback_to_api: e.target.checked }))} />
                Allow paid API fallback
              </label>
            </div>
            <div className="row wrap" style={{ gap: 12, marginTop: 8 }}>
              {[["translate_batch", "Batch translation"], ["codex_extract", "Codex extraction"]].map(([key, label]) => (
                <label key={key} className="check">
                  <input type="checkbox" disabled={!ai.agy_enabled}
                         checked={ai.agy_workloads.includes(key)} onChange={() => toggleWorkload(key)} />
                  {label}
                </label>
              ))}
            </div>
            <label className="field" style={{ marginTop: 8 }}>
              <span>Admin notes</span>
              <input value={ai.notes} onChange={e => setAi(s => ({ ...s, notes: e.target.value }))} placeholder="owner pilot" />
            </label>
            <div className="row wrap" style={{ gap: 8, marginTop: 8 }}>
              <Button variant="primary" size="sm" disabled={busy} onClick={saveAi}>Save AI access</Button>
              {initialPolicy.policy_version && <Button variant="ghost" size="sm" disabled={busy} onClick={revokeAi}>Revoke AGY</Button>}
              <span className="muted" style={{ fontSize: "var(--text-xs)" }}>
                {initialPolicy.active_jobs || 0} active · policy v{initialPolicy.policy_version || "—"}
              </span>
            </div>
          </div>
        </div>
      )}
      {confirmDel && (
        <ConfirmDialog
          title={`Delete @${u.username}?`} requireText={u.username} confirmLabel="Delete user" busy={busy}
          onCancel={() => setConfirmDel(false)} onConfirm={del}
          body="This removes their account, library, progress, bookmarks and overlays. Novels they own become unowned. There's no undo." />
      )}
    </>
  );
}

function UsersTab({ me }) {
  const [users, setUsers] = useState(null);
  const [q, setQ] = useState("");
  const load = useCallback((query) => {
    setUsers(null);
    API.admin.users(query || "").then(setUsers).catch(() => setUsers([]));
  }, []);
  useEffect(() => { load(""); }, [load]);

  return (
    <div>
      <form className="row" style={{ gap: 8, marginBottom: 14 }} onSubmit={e => { e.preventDefault(); load(q); }}>
        <div className="search-box" style={{ maxWidth: 340, flex: 1 }}>
          <Icon name="search" size={15} className="muted" />
          <input value={q} placeholder="Search email, username, name…" onChange={e => setQ(e.target.value)} aria-label="Search users" />
        </div>
        <Button variant="ghost" type="submit" icon="search">Search</Button>
      </form>
      {users == null ? <Loading label="Loading users…" />
        : users.length === 0 ? <EmptyState icon="users" title="No users found" />
          : <div className="admin-user-list">{users.map(u => <UserRow key={u.id} u={u} me={me} onChanged={() => load(q)} />)}</div>}
    </div>
  );
}

/* ── Usage & cost ── */
function UsageTab() {
  const [data, setData] = useState(null);
  useEffect(() => { API.admin.usage().then(setData).catch(() => setData(false)); }, []);
  if (data == null) return <Loading label="Loading usage…" />;
  if (data === false) return <EmptyState icon="database" title="Couldn't load usage" />;
  const t = data.totals;
  return (
    <div>
      <div className="admin-metric-grid">
        <StatTile value={t.translated_chapters} label="chapters translated" />
        <StatTile value={t.ocr_pages} label="OCR pages" />
        <StatTile value={t.codex_builds} label="codex builds" />
        <StatTile value={t.active_users} label="active this month" />
        <StatTile value={data.user_count} label="total users" />
        <StatTile value={data.novel_count} label="novels" />
      </div>

      <p className="section-eyebrow" style={{ marginTop: 24 }}>Top spenders this month</p>
      <div className="card" style={{ padding: 4 }}>
        {data.top_spenders.length === 0
          ? <div className="muted" style={{ padding: 12 }}>No spend recorded this month.</div>
          : data.top_spenders.map(u => (
            <div key={u.id} className="admin-spender-row">
              <span className="grow">{u.display_name || u.username} <span className="muted">@{u.username}</span></span>
              <span className="muted mono">{u.translated_chapters} ch · {u.ocr_pages} ocr · {u.codex_builds} cdx</span>
            </div>
          ))}
      </div>

      <p className="section-eyebrow" style={{ marginTop: 24 }}>Last 6 months</p>
      <div className="card" style={{ padding: 4 }}>
        {data.months.length === 0
          ? <div className="muted" style={{ padding: 12 }}>No history yet.</div>
          : data.months.map(m => (
            <div key={m.period} className="admin-spender-row">
              <span className="grow mono">{m.period.slice(0, 7)}</span>
              <span className="muted mono">{m.translated_chapters} ch · {m.ocr_pages} ocr · {m.codex_builds} cdx</span>
            </div>
          ))}
      </div>
    </div>
  );
}

/* ── Moderation ── */
const MOD_VIS = { private: "Private", public: "Public", global: "Global" };

function ModerationTab({ openNovel }) {
  const { toast } = useToast();
  const [novels, setNovels] = useState(null);
  const [vis, setVis] = useState("");
  const [q, setQ] = useState("");
  const load = useCallback((opts) => {
    setNovels(null);
    API.admin.novels(opts).then(setNovels).catch(() => setNovels([]));
  }, []);
  useEffect(() => { load({}); }, [load]);

  const changeVis = async (n, v) => {
    try { await API.setVisibility(n.id, v); load({ visibility: vis || undefined, q: q || undefined }); }
    catch (e) { toast(e.message || "Couldn't change visibility.", { tone: "danger" }); }
  };

  return (
    <div>
      <form className="row wrap" style={{ gap: 8, marginBottom: 14 }}
            onSubmit={e => { e.preventDefault(); load({ visibility: vis || undefined, q: q || undefined }); }}>
        <div className="search-box" style={{ maxWidth: 280, flex: 1 }}>
          <Icon name="search" size={15} className="muted" />
          <input value={q} placeholder="Search title…" onChange={e => setQ(e.target.value)} aria-label="Search novels" />
        </div>
        <div className="row" style={{ gap: 6 }}>
          {["", ...Object.keys(MOD_VIS)].map(v => (
            <button key={v || "all"} type="button" className={"filter-chip" + (vis === v ? " on" : "")}
                    onClick={() => { setVis(v); load({ visibility: v || undefined, q: q || undefined }); }}>
              {v ? MOD_VIS[v] : "All"}
            </button>
          ))}
        </div>
        <Button variant="ghost" type="submit" icon="search">Search</Button>
      </form>
      {novels == null ? <Loading label="Loading novels…" />
        : novels.length === 0 ? <EmptyState icon="book" title="No novels" />
          : (
            <div className="admin-user-list">
              {novels.map(n => (
                <div key={n.id} className="admin-novel-row">
                  <button className="admin-novel-title grow" onClick={() => openNovel(n.id)} title="Open novel">
                    {n.title} <span className="muted mono" style={{ fontSize: "var(--text-xs)" }}>{n.chapter_count} ch.</span>
                  </button>
                  <span className="muted" style={{ fontSize: "var(--text-xs)" }}>{n.owner_username ? "@" + n.owner_username : "unowned"}</span>
                  <select className="shelf-select" value={n.visibility} onChange={e => changeVis(n, e.target.value)} title="Visibility">
                    {Object.keys(MOD_VIS).map(v => <option key={v} value={v}>{MOD_VIS[v]}</option>)}
                  </select>
                </div>
              ))}
            </div>
          )}
    </div>
  );
}

/* ── Global jobs ── */
function GlobalJobsTab({ openNovel }) {
  const [novels, setNovels] = useState(null);
  const [msg, setMsg] = useState({});
  const [busy, setBusy] = useState({});

  const load = useCallback(() => {
    setNovels(null);
    API.admin.globalNovels().then(setNovels).catch(() => setNovels([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  const run = async (n, label, fn) => {
    setBusy(b => ({ ...b, [n.id]: true }));
    setMsg(m => ({ ...m, [n.id]: { kind: "pending", text: label + "…" } }));
    try {
      const r = await fn();
      setMsg(m => ({ ...m, [n.id]: { kind: "ok", text: (r && r.message) || (label + " scheduled.") } }));
    } catch (e) {
      setMsg(m => ({ ...m, [n.id]: { kind: "err", text: e.message || "Failed." } }));
    } finally {
      setBusy(b => ({ ...b, [n.id]: false }));
    }
  };

  const fmtDate = (s) => s ? new Date(s).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "never";

  return (
    <div>
      <div className="row" style={{ marginBottom: 14 }}>
        <p className="grow muted" style={{ margin: 0 }}>Scrape, pre-translate, and build the codex for the shared Global library. Jobs run in the background.</p>
        <Button variant="ghost" icon="refresh" onClick={load}>Refresh</Button>
      </div>
      {novels == null ? <Loading label="Loading Global library…" />
        : novels.length === 0 ? <EmptyState icon="book" title="No global novels" body="Promote a public novel to Global from the Moderation tab." />
          : (
            <div className="admin-user-list">
              {novels.map(n => {
                const m = msg[n.id]; const b = !!busy[n.id];
                const mClass = m && (m.kind === "ok" ? "acct-ok" : m.kind === "err" ? "acct-err" : "muted");
                return (
                  <div key={n.id} className="admin-job-row">
                    <div className="row wrap" style={{ gap: 10, alignItems: "baseline" }}>
                      <button className="admin-novel-title" onClick={() => openNovel(n.id)} title="Open novel">{n.title}</button>
                      <span className="muted mono" style={{ fontSize: "var(--text-xs)" }}>
                        {n.chapter_count} ch · {n.source_count} src · scraped {fmtDate(n.last_scraped_at)}
                        {n.has_raw ? ` · ${n.untranslated} untranslated` : ""}
                        {n.codex_enabled ? " · codex" : ""}
                      </span>
                    </div>
                    <div className="row wrap" style={{ gap: 8, marginTop: 8 }}>
                      <Button variant="ghost" size="sm" icon="spider" disabled={b}
                              onClick={() => run(n, "Scrape", () => API.scrape(n.id, {}))}>Scrape</Button>
                      {n.has_raw && (
                        <Button variant="ghost" size="sm" icon="globe" disabled={b || n.untranslated === 0}
                                onClick={() => run(n, "Translate", () => API.translate(n.id, {}))}>Translate raws</Button>
                      )}
                      <Button variant="ghost" size="sm" icon="brain" disabled={b}
                              onClick={() => run(n, "Codex build", () => API.codexBuild(n.id, {}))}>
                        {n.codex_enabled ? "Rebuild codex" : "Build codex"}
                      </Button>
                      {m && <span className={mClass} style={{ fontSize: "var(--text-xs)", alignSelf: "center" }}>{m.text}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
    </div>
  );
}

/* ── AGY health ── */
function AgyHealthTab() {
  const { toast } = useToast();
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => API.admin.agyHealth().then(setHealth).catch(() => setHealth(false)), []);
  useEffect(() => { load(); const timer = setInterval(load, 10000); return () => clearInterval(timer); }, [load]);
  if (health == null) return <Loading label="Checking Antigravity worker…" />;
  if (health === false) return <EmptyState icon="sparkles" title="Couldn't load AGY health" />;
  const q = health.queue || {};
  const act = async fn => {
    setBusy(true);
    try { await fn(); await load(); }
    catch (e) { toast(e.message || "AGY action failed.", { tone: "danger" }); }
    finally { setBusy(false); }
  };
  return (
    <div>
      <div className="admin-metric-grid">
        <StatTile value={health.available ? "Ready" : "Offline"} label="worker availability" tone={health.available ? "ok" : "danger"} />
        <StatTile value={q.queued || 0} label="queued" />
        <StatTile value={q.running || 0} label="running" />
        <StatTile value={q.waiting_provider || 0} label="waiting provider" tone={q.waiting_provider > 0 ? "warn" : undefined} />
      </div>
      <div className="card pad-lg" style={{ marginTop: 14 }}>
        <div><b>Global switch:</b> {health.enabled ? "enabled" : "disabled"}</div>
        <div><b>Worker:</b> {health.worker ? `${health.worker.status} · ${health.worker.version || "unknown version"} · plugin ${health.worker.plugin_version || "—"}` : "no heartbeat"}</div>
        <div className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 4 }}>
          Last success: {health.last_success_at || "none"} · oldest queued: {q.oldest_at || "none"}
        </div>
        <div className="row wrap" style={{ gap: 8, marginTop: 14 }}>
          <Button variant="ghost" disabled={busy || !health.enabled} onClick={() => act(API.admin.agySmoke)}>Run consuming smoke test</Button>
          <Button variant="ghost" disabled={busy || !(q.waiting_provider > 0)} onClick={() => act(API.admin.retryWaitingAgy)}>Retry waiting jobs</Button>
        </div>
        {health.recent_failures && health.recent_failures.length > 0 && (
          <div className="muted" style={{ marginTop: 12, fontSize: "var(--text-xs)" }}>
            Recent failures: {health.recent_failures.map(x => `${x.code} (${x.count})`).join(", ")}
          </div>
        )}
      </div>
    </div>
  );
}

export function Admin() {
  const { user } = useAuth();
  const { tab: tabParam } = useParams();
  const navigate = useNavigate();
  const tab = ADMIN_TABS.some(t => t.id === tabParam) ? tabParam : "users";
  useTitle("Admin");

  if (!user || user.role !== "admin") {
    return (
      <div className="page page-enter">
        <EmptyState icon="shield" title="Admins only" body="You don't have access to this page." />
      </div>
    );
  }

  const openNovel = (id) => navigate(`/n/${id}`);

  return (
    <div className="page page-enter">
      <PageHeader title="Admin" subtitle="Users, platform usage, moderation and the shared Global library." />
      <Tabs tabs={ADMIN_TABS} value={tab}
            onChange={(id) => navigate(id === "users" ? "/admin" : `/admin/${id}`)} />
      <div style={{ marginTop: 18 }}>
        {tab === "users" && <UsersTab me={user} />}
        {tab === "usage" && <UsageTab />}
        {tab === "moderation" && <ModerationTab openNovel={openNovel} />}
        {tab === "jobs" && <GlobalJobsTab openNovel={openNovel} />}
        {tab === "agy" && <AgyHealthTab />}
      </div>
    </div>
  );
}
