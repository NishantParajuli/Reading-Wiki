/* ============================================================
   admin.jsx — admin dashboard (Phase 4). Three tabs behind require_admin:
     • Users      — search, suspend/ban, promote, adjust per-user quotas, delete.
     • Usage      — platform-wide monthly spend totals + top spenders.
     • Moderation — every novel with owner + visibility; promote Public→Global / take down.
   Wraps /api/admin/* (+ the shared visibility endpoint for moderation actions).
   ============================================================ */

const ADMIN_TABS = [
  { id: "users", label: "Users", icon: "users" },
  { id: "usage", label: "Usage & cost", icon: "database" },
  { id: "moderation", label: "Moderation", icon: "shield" },
];

function blankToNull(v) {
  const s = String(v).trim();
  if (s === "") return null;
  const n = Number(s);
  return Number.isNaN(n) ? null : Math.max(0, Math.round(n));
}

/* ── Users ── */
function UserRow({ u, me, onChanged }) {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState({
    translated_chapters: u.quota_overrides.translated_chapters ?? "",
    ocr_pages: u.quota_overrides.ocr_pages ?? "",
    codex_builds: u.quota_overrides.codex_builds ?? "",
  });
  const [confirmDel, setConfirmDel] = useState(false);
  const isSelf = me && u.id === me.id;

  const patch = async (body) => {
    setBusy(true);
    try { await window.API.admin.updateUser(u.id, body); onChanged(); }
    catch (e) { alert(e.message || "Update failed."); setBusy(false); }
  };
  const saveQuotas = () => patch({
    quota_translated_chapters: blankToNull(q.translated_chapters),
    quota_ocr_pages: blankToNull(q.ocr_pages),
    quota_codex_builds: blankToNull(q.codex_builds),
  });
  const del = async () => {
    setBusy(true);
    try { await window.API.admin.deleteUser(u.id); setConfirmDel(false); onChanged(); }
    catch (e) { alert(e.message || "Delete failed."); setBusy(false); }
  };

  const statusClass = u.status === "active" ? "ok" : u.status === "suspended" ? "warn" : "err";

  return (
    <React.Fragment>
      <div className="admin-user-row">
        <div className="admin-user-id">
          <div className="usermenu-avatar sm">{(u.display_name || u.username || "?").charAt(0).toUpperCase()}</div>
          <div className="grow" style={{ minWidth: 0 }}>
            <div className="admin-user-name">{u.display_name || u.username} {u.role === "admin" && <span className="chip">admin</span>}</div>
            <div className="muted admin-user-email">@{u.username} · {u.email}{u.email_verified ? "" : " · unverified"}</div>
          </div>
        </div>
        <div className="admin-user-usage muted mono">
          {u.usage.translated_chapters}/{u.limits.translated_chapters} ch · {u.usage.ocr_pages}/{u.limits.ocr_pages} ocr · {u.usage.codex_builds}/{u.limits.codex_builds} cdx
        </div>
        <span className={`admin-status ${statusClass}`}>{u.status}</span>
        <div className="admin-user-actions">
          <select className="shelf-select" value={u.status} disabled={busy || isSelf}
                  onChange={e => patch({ status: e.target.value })} title="Account status">
            {["active", "suspended", "banned"].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <button className="btn btn-ghost sm" disabled={busy || (isSelf && u.role === "admin")}
                  onClick={() => patch({ role: u.role === "admin" ? "user" : "admin" })}>
            {u.role === "admin" ? "Demote" : "Make admin"}
          </button>
          <button className="icon-btn" title="Quotas" onClick={() => setOpen(o => !o)}><Icon name="sliders" size={16} /></button>
          <button className="icon-btn" title="Delete user" disabled={isSelf} onClick={() => setConfirmDel(true)}><Icon name="trash" size={16} /></button>
        </div>
      </div>
      {open && (
        <div className="admin-quota-edit card">
          <span className="muted" style={{ fontSize: 12.5 }}>Per-user monthly limits (blank = default):</span>
          {[["translated_chapters", "Chapters"], ["ocr_pages", "OCR pages"], ["codex_builds", "Codex builds"]].map(([k, lbl]) => (
            <label key={k} className="field" style={{ flex: "0 0 120px" }}>
              <span>{lbl}</span>
              <input value={q[k]} inputMode="numeric" placeholder="default"
                     onChange={e => setQ(s => ({ ...s, [k]: e.target.value }))} />
            </label>
          ))}
          <button className="btn btn-primary sm" disabled={busy} onClick={saveQuotas}>Save limits</button>
        </div>
      )}
      {confirmDel && (
        <ConfirmDialog
          title={`Delete @${u.username}?`} requireText={u.username} confirmLabel="Delete user" busy={busy}
          onCancel={() => setConfirmDel(false)} onConfirm={del}
          body={`This removes their account, library, progress, bookmarks and overlays. Novels they own become unowned. There's no undo.`}
        />
      )}
    </React.Fragment>
  );
}

function UsersTab({ me }) {
  const [users, setUsers] = useState(null);
  const [q, setQ] = useState("");
  const load = useCallback((query) => {
    setUsers(null);
    window.API.admin.users(query || "").then(setUsers).catch(() => setUsers([]));
  }, []);
  useEffect(() => { load(""); }, [load]);

  return (
    <div>
      <form className="row" style={{ gap: 8, marginBottom: 14 }} onSubmit={e => { e.preventDefault(); load(q); }}>
        <input className="auth-input" style={{ maxWidth: 320 }} value={q} placeholder="Search email, username, name…"
               onChange={e => setQ(e.target.value)} />
        <button className="btn btn-ghost" type="submit"><Icon name="search" size={15} /> Search</button>
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
  useEffect(() => { window.API.admin.usage().then(setData).catch(() => setData(false)); }, []);
  if (data == null) return <Loading label="Loading usage…" />;
  if (data === false) return <EmptyState icon="database" title="Couldn't load usage" />;
  const t = data.totals;
  return (
    <div>
      <div className="admin-metric-grid">
        <div className="card admin-metric"><div className="admin-metric-num">{t.translated_chapters}</div><div className="muted">chapters translated</div></div>
        <div className="card admin-metric"><div className="admin-metric-num">{t.ocr_pages}</div><div className="muted">OCR pages</div></div>
        <div className="card admin-metric"><div className="admin-metric-num">{t.codex_builds}</div><div className="muted">codex builds</div></div>
        <div className="card admin-metric"><div className="admin-metric-num">{t.active_users}</div><div className="muted">active this month</div></div>
        <div className="card admin-metric"><div className="admin-metric-num">{data.user_count}</div><div className="muted">total users</div></div>
        <div className="card admin-metric"><div className="admin-metric-num">{data.novel_count}</div><div className="muted">novels</div></div>
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
  const [novels, setNovels] = useState(null);
  const [vis, setVis] = useState("");
  const [q, setQ] = useState("");
  const load = useCallback((opts) => {
    setNovels(null);
    window.API.admin.novels(opts).then(setNovels).catch(() => setNovels([]));
  }, []);
  useEffect(() => { load({}); }, [load]);

  const changeVis = async (n, v) => {
    try { await window.API.setVisibility(n.id, v); load({ visibility: vis || undefined, q: q || undefined }); }
    catch (e) { alert(e.message || "Couldn't change visibility."); }
  };

  return (
    <div>
      <form className="row" style={{ gap: 8, marginBottom: 14, flexWrap: "wrap" }}
            onSubmit={e => { e.preventDefault(); load({ visibility: vis || undefined, q: q || undefined }); }}>
        <input className="auth-input" style={{ maxWidth: 280 }} value={q} placeholder="Search title…" onChange={e => setQ(e.target.value)} />
        <select className="shelf-select" value={vis} onChange={e => { setVis(e.target.value); load({ visibility: e.target.value || undefined, q: q || undefined }); }}>
          <option value="">All visibility</option>
          {Object.keys(MOD_VIS).map(v => <option key={v} value={v}>{MOD_VIS[v]}</option>)}
        </select>
        <button className="btn btn-ghost" type="submit"><Icon name="search" size={15} /> Search</button>
      </form>
      {novels == null ? <Loading label="Loading novels…" />
        : novels.length === 0 ? <EmptyState icon="book" title="No novels" />
          : (
            <div className="admin-user-list">
              {novels.map(n => (
                <div key={n.id} className="admin-novel-row">
                  <button className="admin-novel-title grow" onClick={() => openNovel(n.id)} title="Open novel">
                    {n.title} <span className="muted mono" style={{ fontSize: 12 }}>{n.chapter_count} ch.</span>
                  </button>
                  <span className="muted" style={{ fontSize: 12.5 }}>{n.owner_username ? "@" + n.owner_username : "unowned"}</span>
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

function Admin({ openLibrary, openNovel, currentUser }) {
  const [tab, setTab] = useState("users");
  if (!currentUser || currentUser.role !== "admin") {
    return (
      <div className="page">
        <button className="btn btn-ghost" style={{ padding: "8px 14px" }} onClick={openLibrary}>
          <Icon name="arrowLeft" size={16} /> Library
        </button>
        <div style={{ marginTop: 20 }}><EmptyState icon="shield" title="Admins only" body="You don't have access to this page." /></div>
      </div>
    );
  }
  return (
    <div className="page">
      <button className="btn btn-ghost" style={{ padding: "8px 14px" }} onClick={openLibrary}>
        <Icon name="arrowLeft" size={16} /> Library
      </button>
      <h1 className="lib-title" style={{ marginTop: 16 }}>Admin</h1>
      <div className="lib-tabs">
        {ADMIN_TABS.map(tb => (
          <button key={tb.id} className={"lib-tab" + (tab === tb.id ? " active" : "")} onClick={() => setTab(tb.id)}>
            <Icon name={tb.icon} size={15} /> {tb.label}
          </button>
        ))}
      </div>
      <div style={{ marginTop: 18 }}>
        {tab === "users" && <UsersTab me={currentUser} />}
        {tab === "usage" && <UsageTab />}
        {tab === "moderation" && <ModerationTab openNovel={openNovel} />}
      </div>
    </div>
  );
}

window.Admin = Admin;
