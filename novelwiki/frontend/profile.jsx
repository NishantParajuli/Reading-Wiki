/* ============================================================
   profile.jsx — public profile (/u/:username) + the private Account & Quota panel.

   Profile shows identity, reading stats, and recent activity (currently reading /
   recently finished / published). AccountPanel lets the signed-in user edit their
   profile + avatar, change password, see linked OAuth, and watch their quota usage.
   ============================================================ */

function ProfileAvatar({ url, name, size = 84 }) {
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  if (url) {
    return <img className="profile-avatar" src={url} alt="" style={{ width: size, height: size }} />;
  }
  return <div className="profile-avatar profile-avatar-ph" style={{ width: size, height: size, fontSize: size * 0.42 }}>{initial}</div>;
}

function StatBlock({ value, label }) {
  return (
    <div className="profile-stat">
      <div className="profile-stat-num">{value}</div>
      <div className="profile-stat-label muted">{label}</div>
    </div>
  );
}

function MiniNovel({ n, openNovel }) {
  const pct = (n.max_chapter && n.last_chapter != null)
    ? Math.round(Math.min(100, (n.last_chapter / n.max_chapter) * 100)) : null;
  return (
    <button className="mini-novel" onClick={() => openNovel(n.id)} title={n.title}>
      <div className="mini-novel-cover">
        {n.cover_url
          ? <img src={n.cover_url} alt="" loading="lazy" />
          : <div className="novel-cover-ph"><Icon name="book" size={22} /></div>}
      </div>
      <div className="mini-novel-body">
        <div className="mini-novel-title">{n.title}</div>
        {n.last_chapter != null && <div className="muted" style={{ fontSize: 12 }}>{`Ch. ${n.last_chapter}`}</div>}
        {n.chapter_count != null && <div className="muted" style={{ fontSize: 12 }}>{`${n.chapter_count} ch.`}</div>}
        {pct != null && (
          <div className="progress-track" style={{ marginTop: 6 }}>
            <div className="progress-fill" style={{ width: pct + "%" }} />
          </div>
        )}
      </div>
    </button>
  );
}

function ProfileActivityRow({ title, items, openNovel }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ marginTop: 22 }}>
      <p className="section-eyebrow">{title}</p>
      <div className="mini-novel-grid">
        {items.map(n => <MiniNovel key={n.id} n={n} openNovel={openNovel} />)}
      </div>
    </div>
  );
}

function Profile({ username, currentUser, openNovel, openLibrary, openAccount }) {
  const [data, setData] = useState(null);   // null = loading
  const [err, setErr] = useState(null);

  useEffect(() => {
    setData(null); setErr(null);
    window.API.profile(username).then(setData).catch(e => setErr(e.message || "Couldn't load this profile."));
  }, [username]);

  if (err) {
    return (
      <div className="page">
        <button className="btn btn-ghost" style={{ padding: "8px 14px" }} onClick={openLibrary}>
          <Icon name="arrowLeft" size={16} /> Library
        </button>
        <div style={{ marginTop: 20 }}><EmptyState icon="user" title="Profile unavailable" body={err} /></div>
      </div>
    );
  }
  if (data == null) return <div className="page"><Loading label="Loading profile…" /></div>;

  const joined = data.created_at ? new Date(data.created_at).toLocaleDateString(undefined, { year: "numeric", month: "long" }) : null;
  const s = data.stats || {};
  const empty = (data.currently_reading || []).length === 0
    && (data.recently_finished || []).length === 0
    && (data.published || []).length === 0;

  return (
    <div className="page">
      <button className="btn btn-ghost" style={{ padding: "8px 14px" }} onClick={openLibrary}>
        <Icon name="arrowLeft" size={16} /> Library
      </button>

      <div className="profile-head card">
        <ProfileAvatar url={data.avatar_url} name={data.display_name} />
        <div className="profile-head-body">
          <div className="row" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <h1 className="serif" style={{ margin: 0 }}>{data.display_name}</h1>
            {data.role === "admin" && <span className="chip" style={{ background: "var(--accent)", color: "var(--on-accent)" }}>Admin</span>}
          </div>
          <div className="muted">@{data.username}{joined ? ` · joined ${joined}` : ""}</div>
          {data.bio && <p style={{ color: "var(--ink-2)", lineHeight: 1.55, maxWidth: "60ch", marginTop: 8 }}>{data.bio}</p>}
          {data.is_self && (
            <div className="row" style={{ gap: 8, marginTop: 10 }}>
              <button className="btn btn-ghost" onClick={openAccount}>
                <Icon name="sliders" size={15} /> Account & settings
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="profile-stats card">
        <StatBlock value={s.library_count || 0} label="in library" />
        <StatBlock value={s.reading_count || 0} label="reading" />
        <StatBlock value={s.completed_count || 0} label="completed" />
        <StatBlock value={s.chapters_read || 0} label="chapters read" />
      </div>

      {empty
        ? <div style={{ marginTop: 22 }}><EmptyState icon="book" title="No public activity yet" body="Reading activity on shared novels shows up here." /></div>
        : (
          <React.Fragment>
            <ProfileActivityRow title="Currently reading" items={data.currently_reading} openNovel={openNovel} />
            <ProfileActivityRow title="Recently finished" items={data.recently_finished} openNovel={openNovel} />
            <ProfileActivityRow title={data.is_self ? "Published by you" : "Published"} items={data.published} openNovel={openNovel} />
          </React.Fragment>
        )}
    </div>
  );
}

/* ── Account & Quota panel (private, self only) ── */
function QuotaBar({ label, used, limit }) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div className="acct-quota">
      <div className="acct-quota-top">
        <span>{label}</span>
        <span className="muted">{used} / {limit}</span>
      </div>
      <div className="progress-track"><div className="progress-fill" style={{ width: pct + "%" }} /></div>
    </div>
  );
}

function AccountPanel({ user, onUserUpdate, openLibrary, openProfile }) {
  const [displayName, setDisplayName] = useState(user.display_name || "");
  const [username, setUsername] = useState(user.username || "");
  const [bio, setBio] = useState(user.bio || "");
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url || null);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMsg, setProfileMsg] = useState(null);

  const [usage, setUsage] = useState(null);
  const [links, setLinks] = useState(null);

  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwMsg, setPwMsg] = useState(null);
  const [pwBusy, setPwBusy] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    window.API.usage().then(setUsage).catch(() => setUsage({ unlimited: true }));
    window.API.auth.links().then(setLinks).catch(() => setLinks({ linked: [], has_password: true }));
  }, []);

  async function saveProfile(e) {
    e.preventDefault();
    setSavingProfile(true); setProfileMsg(null);
    try {
      const body = { display_name: displayName.trim(), bio: bio.trim() };
      if (username.trim() && username.trim() !== user.username) body.username = username.trim();
      const updated = await window.API.updateMe(body);
      onUserUpdate && onUserUpdate(updated);
      setUsername(updated.username);
      setProfileMsg({ ok: true, text: "Profile saved." });
    } catch (err) {
      setProfileMsg({ ok: false, text: err.message || "Couldn't save." });
    } finally { setSavingProfile(false); }
  }

  async function onPickAvatar(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    try {
      const r = await window.API.uploadAvatar(file);
      setAvatarUrl(r.avatar_url);
      onUserUpdate && onUserUpdate({ ...user, avatar_path: r.avatar_path, avatar_url: r.avatar_url });
      setProfileMsg({ ok: true, text: "Avatar updated." });
    } catch (err) {
      setProfileMsg({ ok: false, text: err.message || "Avatar upload failed." });
    } finally { if (fileRef.current) fileRef.current.value = ""; }
  }

  async function changePassword(e) {
    e.preventDefault();
    setPwBusy(true); setPwMsg(null);
    try {
      await window.API.auth.changePassword(curPw || null, newPw);
      setCurPw(""); setNewPw("");
      setPwMsg({ ok: true, text: "Password updated. Other devices were signed out." });
      window.API.auth.links().then(setLinks).catch(() => {});
    } catch (err) {
      setPwMsg({ ok: false, text: err.message || "Couldn't change the password." });
    } finally { setPwBusy(false); }
  }

  const PROVIDER_NAMES = { google: "Google", discord: "Discord" };

  return (
    <div className="page">
      <div className="row" style={{ gap: 8, alignItems: "center" }}>
        <button className="btn btn-ghost" style={{ padding: "8px 14px" }} onClick={openLibrary}>
          <Icon name="arrowLeft" size={16} /> Library
        </button>
        <div className="grow" />
        <button className="btn btn-ghost" onClick={() => openProfile(user.username)}>
          <Icon name="user" size={15} /> View public profile
        </button>
      </div>

      <h1 className="lib-title" style={{ marginTop: 16 }}>Account</h1>

      <div className="acct-grid">
        {/* Profile */}
        <form className="card acct-card" onSubmit={saveProfile}>
          <p className="section-eyebrow" style={{ marginTop: 0 }}>Profile</p>
          <div className="row" style={{ gap: 14, alignItems: "center", marginBottom: 14 }}>
            <ProfileAvatar url={avatarUrl} name={displayName || username} size={64} />
            <div>
              <button type="button" className="btn btn-ghost" onClick={() => fileRef.current && fileRef.current.click()}>
                <Icon name="edit" size={15} /> Change avatar
              </button>
              <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={onPickAvatar} />
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>PNG/JPG/WebP, under 5 MB.</div>
            </div>
          </div>
          <label className="field">
            <span>Display name</span>
            <input value={displayName} onChange={e => setDisplayName(e.target.value)} maxLength={80} />
          </label>
          <label className="field">
            <span>Username</span>
            <input value={username} onChange={e => setUsername(e.target.value)} placeholder="a–z, 0–9, underscore" />
          </label>
          <label className="field">
            <span>Bio</span>
            <textarea value={bio} onChange={e => setBio(e.target.value)} rows={3} maxLength={600} />
          </label>
          {profileMsg && <div className={profileMsg.ok ? "acct-ok" : "acct-err"}>{profileMsg.text}</div>}
          <button className="btn btn-primary" type="submit" disabled={savingProfile} style={{ marginTop: 4 }}>
            {savingProfile ? "Saving…" : "Save profile"}
          </button>
        </form>

        {/* Right column: usage, password, linked accounts */}
        <div className="col" style={{ gap: 18 }}>
          <div className="card acct-card">
            <p className="section-eyebrow" style={{ marginTop: 0 }}>This month's usage</p>
            {!usage ? <Loading /> : usage.unlimited
              ? <div className="chip" style={{ background: "var(--accent)", color: "var(--on-accent)" }}>Unlimited (admin)</div>
              : (
                <React.Fragment>
                  <QuotaBar label="Chapters translated" used={usage.usage.translated_chapters} limit={usage.limits.translated_chapters} />
                  <QuotaBar label="OCR pages" used={usage.usage.ocr_pages} limit={usage.limits.ocr_pages} />
                  <QuotaBar label="Codex builds" used={usage.usage.codex_builds} limit={usage.limits.codex_builds} />
                  {!user.email_verified && <div className="acct-err" style={{ marginTop: 10 }}>Verify your email to use translation, OCR & imports.</div>}
                </React.Fragment>
              )}
          </div>

          <form className="card acct-card" onSubmit={changePassword}>
            <p className="section-eyebrow" style={{ marginTop: 0 }}>{links && !links.has_password ? "Set a password" : "Change password"}</p>
            {links && links.has_password && (
              <label className="field">
                <span>Current password</span>
                <input type="password" value={curPw} onChange={e => setCurPw(e.target.value)} autoComplete="current-password" />
              </label>
            )}
            <label className="field">
              <span>New password</span>
              <input type="password" value={newPw} onChange={e => setNewPw(e.target.value)} placeholder="at least 8 characters" autoComplete="new-password" />
            </label>
            {pwMsg && <div className={pwMsg.ok ? "acct-ok" : "acct-err"}>{pwMsg.text}</div>}
            <button className="btn btn-primary" type="submit" disabled={pwBusy || newPw.length < 8} style={{ marginTop: 4 }}>
              {pwBusy ? "Saving…" : (links && !links.has_password ? "Set password" : "Change password")}
            </button>
          </form>

          <div className="card acct-card">
            <p className="section-eyebrow" style={{ marginTop: 0 }}>Linked accounts</p>
            <div className="muted" style={{ fontSize: 13.5 }}>{user.email}</div>
            <div className="row" style={{ gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              {links && links.linked.length > 0
                ? links.linked.map(p => <span key={p} className="chip">{PROVIDER_NAMES[p] || p}</span>)
                : <span className="muted" style={{ fontSize: 13 }}>No external logins linked.</span>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

window.Profile = Profile;
window.AccountPanel = AccountPanel;
