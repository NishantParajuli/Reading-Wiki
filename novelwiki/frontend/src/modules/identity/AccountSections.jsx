/* ============================================================
   Account sections: Profile (live calling card + avatar upload),
   Security (password change/set), Linked accounts and Source accounts.
   Appearance lives in AccountAppearance.jsx, Reading/Audio in
   AccountReading.jsx, Usage in AccountUsage.jsx.
   ============================================================ */
import React, { useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { authApi, identityApi } from "./api.js";
import { Group, SectionHead } from "./AccountParts.jsx";
import { useAuth } from "../../App.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, Skeleton, UserAvatar } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";
import { NovelpiaCookies } from "../acquisition/index.js";

export { SECTIONS } from "./AccountNav.jsx";

const BIO_MAX = 600;

export function ProfileSection() {
  const { user, onUserUpdate } = useAuth();
  const { toast } = useToast();
  const [displayName, setDisplayName] = useState(user.display_name || "");
  const [username, setUsername] = useState(user.username || "");
  const [bio, setBio] = useState(user.bio || "");
  const [avatarUrl, setAvatarUrl] = useState(user.avatar_url || null);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);
  const uid = useId();
  const dirty = displayName !== (user.display_name || "") || username !== (user.username || "") || bio !== (user.bio || "");

  async function saveProfile(e) {
    e.preventDefault();
    setSaving(true);
    try {
      const body = { display_name: displayName.trim(), bio: bio.trim() };
      if (username.trim() && username.trim() !== user.username) body.username = username.trim();
      const updated = await identityApi.updateMe(body);
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
    setUploading(true);
    try {
      const r = await identityApi.uploadAvatar(file);
      setAvatarUrl(r.avatar_url);
      onUserUpdate && onUserUpdate({ ...user, avatar_path: r.avatar_path, avatar_url: r.avatar_url });
      toast("Avatar updated.", { tone: "ok" });
    } catch (err) {
      toast(err.message || "Avatar upload failed.", { tone: "danger" });
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const pick = () => fileRef.current && fileRef.current.click();
  const shownName = displayName.trim() || username || "Your name";
  return (
    <section className="acct-section" aria-labelledby="acct-h-profile">
      <SectionHead id="acct-h-profile" icon="user" title="Profile"
                   lead="How you appear to other readers on your public page." />
      <Group as="form" i={1} className="acct-identity" onSubmit={saveProfile}>
        <div className="acct-calling">
          <button type="button" className={"acct-avatar" + (uploading ? " is-busy" : "")} onClick={pick}
                  tabIndex={-1} aria-hidden="true">
            <UserAvatar url={avatarUrl} name={shownName} size={96} />
            <span className="acct-avatar-edit"><Icon name="upload" size={16} /></span>
          </button>
          <div className="acct-calling-text">
            <p className="acct-calling-name">{shownName}</p>
            <p className="acct-calling-handle">@{username || "username"}</p>
            <div className="acct-calling-actions">
              <Button variant="ghost" size="sm" icon="edit" loading={uploading} onClick={pick}>Change avatar</Button>
              <span className="acct-hint">PNG, JPG or WebP, under 5 MB.</span>
            </div>
          </div>
          <input ref={fileRef} type="file" accept="image/*" hidden onChange={onPickAvatar} />
        </div>

        <div className="acct-fields">
          <label className="field">
            <span>Display name</span>
            <input value={displayName} onChange={e => setDisplayName(e.target.value)} maxLength={80} autoComplete="nickname" />
          </label>
          <div className="field">
            <label htmlFor={`${uid}-username`}>Username</label>
            <span className="acct-affix">
              <span className="acct-affix-mark" aria-hidden="true">@</span>
              <input id={`${uid}-username`} value={username} onChange={e => setUsername(e.target.value)} placeholder="a–z, 0–9, underscore"
                     autoComplete="username" spellCheck={false} />
            </span>
          </div>
          <div className="field acct-span-all">
            <label htmlFor={`${uid}-bio`}>Bio</label>
            <textarea id={`${uid}-bio`} value={bio} onChange={e => setBio(e.target.value)} rows={3} maxLength={BIO_MAX}
                      placeholder="A line or two about what you love to read." aria-describedby={`${uid}-bio-count`} />
            <span id={`${uid}-bio-count`} className={"field-help acct-count" + (bio.length > BIO_MAX - 40 ? " is-near" : "")}>
              {bio.length} / {BIO_MAX} characters
            </span>
          </div>
        </div>

        <div className="acct-actions">
          <Button type="submit" variant="primary" loading={saving}>Save profile</Button>
          {dirty
            ? <span className="acct-hint acct-dirty"><span className="acct-dirty-dot" aria-hidden="true" />Unsaved changes</span>
            : <span className="acct-hint">Public at <Link className="linkish" to={`/u/${encodeURIComponent(user.username)}`}>/u/{user.username}</Link></span>}
        </div>
      </Group>
    </section>
  );
}

export function SecuritySection({ links, reloadLinks }) {
  const { toast } = useToast();
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState(false);
  const uid = useId();
  const setting = links && !links.has_password;
  const long = newPw.length >= 8;

  async function changePassword(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await authApi.changePassword(curPw || null, newPw);
      setCurPw(""); setNewPw("");
      toast("Password updated. Other devices were signed out.", { tone: "ok" });
      reloadLinks();
    } catch (err) {
      toast(err.message || "Couldn't change the password.", { tone: "danger" });
    } finally { setBusy(false); }
  }

  const status = links == null
    ? <Skeleton width={120} height={24} style={{ borderRadius: 999 }} />
    : <Chip tone={links.has_password ? "ok" : "neutral"} icon={links.has_password ? "lock" : "unlock"}>
        {links.has_password ? "Password sign-in on" : "No password yet"}
      </Chip>;

  return (
    <section className="acct-section" aria-labelledby="acct-h-security">
      <SectionHead id="acct-h-security" icon="shield" title="Security"
                   lead="Your password, and what happens to your other sessions when it changes." />
      <Group as="form" i={1} onSubmit={changePassword} aside={status}
             title={setting ? "Set a password" : "Change password"}
             hint={setting
               ? "You sign in with a linked account today. A password lets you sign in with your email too."
               : "A passphrase of a few unrelated words is long, and easy to remember."}>
        <div className="acct-fields">
          {links && links.has_password && (
            <label className="field">
              <span>Current password</span>
              <input type={reveal ? "text" : "password"} value={curPw} onChange={e => setCurPw(e.target.value)} autoComplete="current-password" />
            </label>
          )}
          <div className="field">
            <label htmlFor={`${uid}-new`}>New password</label>
            <span className="acct-affix">
              <input id={`${uid}-new`} type={reveal ? "text" : "password"} value={newPw} onChange={e => setNewPw(e.target.value)}
                     autoComplete="new-password" aria-describedby={`${uid}-req`} />
              <button type="button" className="icon-btn plain acct-reveal" onClick={() => setReveal(r => !r)}
                      aria-label={reveal ? "Hide passwords" : "Show passwords"} aria-pressed={reveal}>
                <Icon name={reveal ? "eyeOff" : "eye"} size={16} />
              </button>
            </span>
            <span id={`${uid}-req`} className={"acct-req" + (long ? " is-met" : "")}>
              <Icon name={long ? "circleCheck" : "clock"} size={14} /> At least 8 characters
            </span>
          </div>
        </div>
        <div className="acct-actions">
          <Button type="submit" variant="primary" loading={busy} disabled={!long}>
            {setting ? "Set password" : "Change password"}
          </Button>
          <span className="acct-hint">Saving signs out your other devices.</span>
        </div>
      </Group>
    </section>
  );
}

const PROVIDER_NAMES = { google: "Google", discord: "Discord" };

export function LinkedSection({ links }) {
  const { user } = useAuth();
  const linked = (links && links.linked) || [];
  return (
    <section className="acct-section" aria-labelledby="acct-h-linked">
      <SectionHead id="acct-h-linked" icon="link" title="Linked accounts"
                   lead="The ways you can sign in to Tideglass." />
      <Group i={1} title="Sign-in methods">
        <ul className="acct-list">
          <li className="acct-list-row">
            <span className="acct-list-mark" aria-hidden="true"><Icon name="user" size={16} /></span>
            <span className="acct-list-text">
              <b>Email</b>
              <span className="muted">{user.email || "No email on file"}</span>
            </span>
            {user.email && <Chip tone={user.email_verified ? "ok" : "warn"} icon={user.email_verified ? "check" : "alert"}>
              {user.email_verified ? "Verified" : "Unverified"}
            </Chip>}
          </li>
          <li className="acct-list-row">
            <span className="acct-list-mark" aria-hidden="true"><Icon name="lock" size={16} /></span>
            <span className="acct-list-text">
              <b>Password</b>
              <span className="muted">{links == null ? "Checking…" : links.has_password ? "Set — manage it under Security" : "Not set"}</span>
            </span>
            {links && <Chip tone={links.has_password ? "ok" : "neutral"}>{links.has_password ? "On" : "Off"}</Chip>}
          </li>
          {linked.map(p => (
            <li key={p} className="acct-list-row">
              <span className="acct-list-mark is-brand" aria-hidden="true">{(PROVIDER_NAMES[p] || p).charAt(0)}</span>
              <span className="acct-list-text">
                <b>{PROVIDER_NAMES[p] || p}</b>
                <span className="muted">Sign in with your {PROVIDER_NAMES[p] || p} account</span>
              </span>
              <Chip tone="accent" icon="link">Linked</Chip>
            </li>
          ))}
        </ul>
        {links && linked.length === 0 && (
          <p className="acct-hint acct-list-empty">No external logins linked.</p>
        )}
      </Group>
    </section>
  );
}

export function SourcesSection() {
  return (
    <section className="acct-section acct-sources" aria-labelledby="acct-h-sources">
      <SectionHead id="acct-h-sources" icon="globe" title="Source accounts"
                   lead="Sign-ins Tideglass uses on your behalf to import chapters from sites that need an account." />
      <div className="rise" style={{ "--i": 1 }}>
        <NovelpiaCookies />
      </div>
    </section>
  );
}
