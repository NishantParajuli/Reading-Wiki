/* ============================================================
   Account (§6.11) — left-nav settings: Profile / Appearance / Reading /
   Audio / Security / Linked accounts / Usage. Appearance hosts the theme +
   accent-hue picker (the surviving Tweaks feature, now a real setting).
   ============================================================ */
import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { API } from "../lib/api.js";
import { useAuth, useTheme } from "../App.jsx";
import { Icon } from "../components/Icon.jsx";
import { Button, Loading, PageHeader, ProgressBar, SegmentedControl, UserAvatar, Chip } from "../components/ui.jsx";
import { VoicePicker } from "../features/narrate.jsx";
import { useToast } from "../components/toast.jsx";
import { useVoicesQuery } from "../lib/queries.js";
import { useTitle } from "../lib/hooks.js";

const SECTIONS = [
  { id: "profile", label: "Profile", icon: "user" },
  { id: "appearance", label: "Appearance", icon: "sun" },
  { id: "reading", label: "Reading", icon: "book" },
  { id: "audio", label: "Audio", icon: "headphones" },
  { id: "security", label: "Security", icon: "shield" },
  { id: "linked", label: "Linked accounts", icon: "link" },
  { id: "usage", label: "Usage", icon: "database" },
];

const ACCENTS = [
  { hue: 64, name: "Honey" },
  { hue: 42, name: "Amber" },
  { hue: 28, name: "Clay" },
  { hue: 12, name: "Rose" },
  { hue: 152, name: "Sage" },
  { hue: 250, name: "Dusk" },
];

function ProfileSection() {
  const { user, onUserUpdate } = useAuth();
  const { toast } = useToast();
  const [displayName, setDisplayName] = useState(user.display_name || "");
  const [username, setUsername] = useState(user.username || "");
  const [bio, setBio] = useState(user.bio || "");
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url || null);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef(null);

  async function saveProfile(e) {
    e.preventDefault();
    setSaving(true);
    try {
      const body = { display_name: displayName.trim(), bio: bio.trim() };
      if (username.trim() && username.trim() !== user.username) body.username = username.trim();
      const updated = await API.updateMe(body);
      onUserUpdate && onUserUpdate(updated);
      setUsername(updated.username);
      toast("Profile saved.", { tone: "ok" });
    } catch (err) {
      toast(err.message || "Couldn't save.", { tone: "danger" });
    } finally { setSaving(false); }
  }

  async function onPickAvatar(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    try {
      const r = await API.uploadAvatar(file);
      setAvatarUrl(r.avatar_url);
      onUserUpdate && onUserUpdate({ ...user, avatar_path: r.avatar_path, avatar_url: r.avatar_url });
      toast("Avatar updated.", { tone: "ok" });
    } catch (err) {
      toast(err.message || "Avatar upload failed.", { tone: "danger" });
    } finally { if (fileRef.current) fileRef.current.value = ""; }
  }

  return (
    <form className="card acct-card" onSubmit={saveProfile}>
      <p className="section-eyebrow" style={{ marginTop: 0 }}>Profile</p>
      <div className="row" style={{ gap: 14, marginBottom: 8 }}>
        <UserAvatar url={avatarUrl} name={displayName || username} size={64} />
        <div>
          <Button variant="ghost" size="sm" icon="edit" onClick={() => fileRef.current && fileRef.current.click()}>
            Change avatar
          </Button>
          <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={onPickAvatar} />
          <div className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 4 }}>PNG/JPG/WebP, under 5 MB.</div>
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
      <div className="row">
        <Button type="submit" variant="primary" loading={saving}>Save profile</Button>
      </div>
    </form>
  );
}

function AppearanceSection() {
  const { theme, setTheme, accentHue, setAccentHue } = useTheme();
  const { user, onUserUpdate } = useAuth();

  // Accent hue also syncs to the account so it follows the user across devices.
  function pickAccent(hue) {
    setAccentHue(hue);
    if (user) {
      API.updateMe({ prefs: { appearance: { accent_h: hue } } })
        .then(u => onUserUpdate && onUserUpdate(u)).catch(() => {});
    }
  }

  return (
    <div className="card acct-card">
      <p className="section-eyebrow" style={{ marginTop: 0 }}>Appearance</p>
      <div className="field">
        <span>Theme</span>
        <SegmentedControl fit value={theme} onChange={setTheme} ariaLabel="Theme"
          options={[{ value: "light", label: "Light", icon: "sun" }, { value: "dark", label: "Dark", icon: "moon" }]} />
      </div>
      <div className="field">
        <span>Accent colour</span>
        <div className="accent-swatches">
          {ACCENTS.map(a => (
            <button key={a.hue} type="button" title={a.name}
                    aria-label={`Accent: ${a.name}`}
                    className={"accent-swatch" + (accentHue === a.hue ? " on" : "")}
                    style={{ background: `oklch(0.74 0.13 ${a.hue})` }}
                    onClick={() => pickAccent(a.hue)} />
          ))}
        </div>
      </div>
      <p className="muted" style={{ fontSize: "var(--text-xs)", margin: 0 }}>
        The reader's sepia and night tones live in the reader's Aa menu.
      </p>
    </div>
  );
}

function ReadingSection() {
  const { user, onUserUpdate } = useAuth();
  const { toast } = useToast();
  const synced = (user && user.prefs && user.prefs.reader) || {};
  const [font, setFont] = useState(synced.font || "serif");
  const [size, setSize] = useState(synced.size || 19);
  const [line, setLine] = useState(synced.line || 1.7);
  const [width, setWidth] = useState(synced.width || "normal");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const prefs = { ...synced, font, size, line, width };
      const u = await API.updateMe({ prefs: { reader: prefs } });
      try { localStorage.setItem("nw-reader", JSON.stringify({ ...JSON.parse(localStorage.getItem("nw-reader") || "{}"), font, size, line, width })); } catch (e) { /* ignore */ }
      onUserUpdate && onUserUpdate(u);
      toast("Reading defaults saved.", { tone: "ok" });
    } catch (e) {
      toast(e.message || "Couldn't save.", { tone: "danger" });
    } finally { setSaving(false); }
  }

  return (
    <div className="card acct-card">
      <p className="section-eyebrow" style={{ marginTop: 0 }}>Reading defaults</p>
      <div className="field">
        <span>Font</span>
        <SegmentedControl fit value={font} onChange={setFont} ariaLabel="Font"
          options={[{ value: "serif", label: "Serif" }, { value: "sans", label: "Sans" }]} />
      </div>
      <div className="field">
        <span>Size — {size}px</span>
        <input type="range" className="slider" min={14} max={28} step={1} value={size} onChange={e => setSize(Number(e.target.value))} />
      </div>
      <div className="field">
        <span>Line height — {Number(line).toFixed(1)}</span>
        <input type="range" className="slider" min={1.3} max={2.2} step={0.1} value={line} onChange={e => setLine(Math.round(Number(e.target.value) * 10) / 10)} />
      </div>
      <div className="field">
        <span>Column width</span>
        <SegmentedControl value={width} onChange={setWidth} ariaLabel="Column width"
          options={[{ value: "narrow", label: "Narrow" }, { value: "normal", label: "Normal" }, { value: "wide", label: "Wide" }, { value: "full", label: "Full" }]} />
      </div>
      <div className="row">
        <Button variant="primary" loading={saving} onClick={save}>Save defaults</Button>
      </div>
      <p className="muted" style={{ fontSize: "var(--text-xs)", margin: 0 }}>
        These sync across devices; the reader's Aa menu changes them too.
      </p>
    </div>
  );
}

function AudioSection() {
  const { user, onUserUpdate } = useAuth();
  const { toast } = useToast();
  const { data: voicesData } = useVoicesQuery();
  const tts = (user && user.prefs && user.prefs.tts) || {};
  const [voice, setVoice] = useState(tts.voice || null);
  const [speed, setSpeed] = useState(Number(tts.speed) || 1);
  const [autoplay, setAutoplay] = useState(tts.autoplay !== false);
  const [saving, setSaving] = useState(false);

  const voices = ((voicesData && voicesData.voices) || []).filter(v => v.ready);

  async function save() {
    setSaving(true);
    try {
      const u = await API.updateMe({ prefs: { tts: { voice, speed, autoplay } } });
      onUserUpdate && onUserUpdate(u);
      toast("Audio preferences saved.", { tone: "ok" });
    } catch (e) {
      toast(e.message || "Couldn't save.", { tone: "danger" });
    } finally { setSaving(false); }
  }

  return (
    <div className="card acct-card">
      <p className="section-eyebrow" style={{ marginTop: 0 }}>Audio</p>
      {voices.length === 0 ? (
        <p className="muted" style={{ margin: 0, fontSize: "var(--text-sm)" }}>
          Narration voices are offline right now — preferences appear here when the narrator is available.
        </p>
      ) : (
        <>
          <div className="field">
            <span>Preferred narrator</span>
            <VoicePicker voices={voices} value={voice} onChange={setVoice}
                         defaultVoice={voicesData && voicesData.default} preferredVoice={voice} />
          </div>
          <div className="field">
            <span>Playback speed — {speed}×</span>
            <SegmentedControl value={speed} onChange={setSpeed} ariaLabel="Playback speed"
              options={[0.75, 1, 1.25, 1.5, 1.75, 2].map(s => ({ value: s, label: `${s}×` }))} />
          </div>
          <label className="check">
            <input type="checkbox" checked={autoplay} onChange={e => setAutoplay(e.target.checked)} />
            Auto-advance to the next chapter when narration ends
          </label>
          <div className="row">
            <Button variant="primary" loading={saving} onClick={save}>Save audio preferences</Button>
          </div>
        </>
      )}
    </div>
  );
}

function SecuritySection({ links, reloadLinks }) {
  const { toast } = useToast();
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [busy, setBusy] = useState(false);

  async function changePassword(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await API.auth.changePassword(curPw || null, newPw);
      setCurPw(""); setNewPw("");
      toast("Password updated. Other devices were signed out.", { tone: "ok" });
      reloadLinks();
    } catch (err) {
      toast(err.message || "Couldn't change the password.", { tone: "danger" });
    } finally { setBusy(false); }
  }

  return (
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
      <div className="row">
        <Button type="submit" variant="primary" loading={busy} disabled={newPw.length < 8}>
          {links && !links.has_password ? "Set password" : "Change password"}
        </Button>
      </div>
    </form>
  );
}

function LinkedSection({ links }) {
  const { user } = useAuth();
  const PROVIDER_NAMES = { google: "Google", discord: "Discord" };
  return (
    <div className="card acct-card">
      <p className="section-eyebrow" style={{ marginTop: 0 }}>Linked accounts</p>
      <div className="muted" style={{ fontSize: "var(--text-sm)" }}>{user.email}</div>
      <div className="row wrap" style={{ gap: 8 }}>
        {links && links.linked.length > 0
          ? links.linked.map(p => <Chip key={p} tone="accent">{PROVIDER_NAMES[p] || p}</Chip>)
          : <span className="muted" style={{ fontSize: "var(--text-sm)" }}>No external logins linked.</span>}
      </div>
    </div>
  );
}

function UsageSection() {
  const { user } = useAuth();
  const [usage, setUsage] = useState(null);
  useEffect(() => {
    API.usage().then(setUsage).catch(() => setUsage({ unlimited: true }));
  }, []);

  const meter = (label, used, limit, help) => (
    <div>
      <div className="acct-quota-top"><span>{label}</span><span className="muted mono">{used} / {limit}</span></div>
      <ProgressBar size="sm" value={limit > 0 ? Math.min(100, (used / limit) * 100) : 0} label={label} />
      {help && <div className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 3 }}>{help}</div>}
    </div>
  );

  return (
    <div className="card acct-card">
      <p className="section-eyebrow" style={{ marginTop: 0 }}>This month's usage</p>
      {!usage ? <Loading /> : usage.unlimited ? (
        <Chip tone="accent">Unlimited (admin)</Chip>
      ) : (
        <>
          {meter("Chapters translated", usage.usage.translated_chapters, usage.limits.translated_chapters, "On-demand reads and batch pre-translation both count.")}
          {meter("OCR pages", usage.usage.ocr_pages, usage.limits.ocr_pages, "Pages read from scanned PDF imports.")}
          {meter("Codex builds", usage.usage.codex_builds, usage.limits.codex_builds, "Each build or extension of a novel's codex.")}
          {usage.limits.tts_chapters != null && meter("Chapters narrated", usage.usage.tts_chapters, usage.limits.tts_chapters, "Chapters synthesized to audio (cached ones are free).")}
          {!user.email_verified && <div className="acct-err">Verify your email to use translation, OCR & imports.</div>}
          <p className="muted" style={{ fontSize: "var(--text-xs)", margin: 0 }}>Quotas reset at the start of each month.</p>
        </>
      )}
    </div>
  );
}

export function Account() {
  const { section: sectionParam } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const section = SECTIONS.some(s => s.id === sectionParam) ? sectionParam : "profile";
  const [links, setLinks] = useState(null);
  useTitle("Account");

  const reloadLinks = () => API.auth.links().then(setLinks).catch(() => setLinks({ linked: [], has_password: true }));
  useEffect(() => { reloadLinks(); }, []);

  return (
    <div className="page page-enter">
      <PageHeader title="Account" subtitle="Your identity, appearance, reading defaults and quota."
        actions={<Button variant="ghost" icon="user" onClick={() => navigate(`/u/${encodeURIComponent(user.username)}`)}>View public profile</Button>} />

      <div className="acct-layout">
        <nav className="acct-nav" aria-label="Settings sections">
          {SECTIONS.map(s => (
            <button key={s.id} className={"acct-nav-item" + (section === s.id ? " active" : "")}
                    onClick={() => navigate(s.id === "profile" ? "/account" : `/account/${s.id}`)}>
              <Icon name={s.icon} size={16} /> {s.label}
            </button>
          ))}
        </nav>
        <div>
          {section === "profile" && <ProfileSection />}
          {section === "appearance" && <AppearanceSection />}
          {section === "reading" && <ReadingSection />}
          {section === "audio" && <AudioSection />}
          {section === "security" && <SecuritySection links={links} reloadLinks={reloadLinks} />}
          {section === "linked" && <LinkedSection links={links} />}
          {section === "usage" && <UsageSection />}
        </div>
      </div>
    </div>
  );
}
