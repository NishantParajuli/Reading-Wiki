/* ============================================================
   Shell — desktop sidebar + contextual topbar + mobile bottom tabs.
   Also hosts the global command palette (Cmd/Ctrl+K), the offline banner,
   and job-completion toasts driven by the shared activity poller.
   ============================================================ */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { codexApi } from "../modules/codex/api.js";
import { experienceApi } from "../modules/experience/api.js";
import { identityApi } from "../modules/identity/api.js";
import { useAuth, useTheme } from "../App.jsx";
import { Icon } from "../components/Icon.jsx";
import { Cover, ProgressBar, UserAvatar } from "../components/ui.jsx";
import { MenuItem, Popover } from "../components/overlay.jsx";
import { useToast } from "../components/toast.jsx";
import { useNovelQuery, useNovelsQuery } from "../modules/catalog/queries.js";
import { isActiveJob, useActivityQuery } from "../modules/experience/queries.js";
import { useDebounce, useLocalStorage, useOnline } from "../lib/hooks.js";
import { ACT_KIND_LABEL } from "../lib/constants.js";

const NAV = [
  { to: "/", icon: "home", label: "Home", end: true },
  { to: "/library", icon: "library", label: "Library" },
  { to: "/discover", icon: "compass", label: "Discover" },
  { to: "/import", icon: "upload", label: "Import" },
  { to: "/jobs", icon: "layers", label: "Jobs" },
];

const MOBILE_NAV = [
  { to: "/", icon: "home", label: "Home", end: true },
  { to: "/library", icon: "library", label: "Library" },
  { to: "/discover", icon: "compass", label: "Discover" },
  { to: "/jobs", icon: "layers", label: "Jobs" },
  { to: "/account", icon: "user", label: "You" },
];

/* Toast when a job started this session finishes (done or failed). */
function useJobCompletionToasts(jobs) {
  const { toast } = useToast();
  const prev = useRef(null);
  useEffect(() => {
    if (!jobs) return;
    const map = new Map(jobs.map(j => [`${j.source}:${j.id}`, j]));
    if (prev.current) {
      for (const [key, j] of map) {
        const before = prev.current.get(key);
        if (!before || before.status === j.status) continue;
        const label = ACT_KIND_LABEL[j.kind] || j.kind;
        if (j.status === "done" || j.status === "committed") {
          toast(`${label} finished.`, { tone: "ok" });
        } else if (j.status === "failed") {
          toast(`${label} failed${j.error ? `: ${String(j.error).slice(0, 80)}` : "."}`, { tone: "danger", duration: 8000 });
        }
      }
    }
    prev.current = map;
  }, [jobs, toast]);
}

function UserMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [usage, setUsage] = useState(null);

  useEffect(() => {
    if (open && usage == null) {
      identityApi.usage().then(setUsage).catch(() => setUsage({ unlimited: true }));
    }
  }, [open, usage]);

  const name = user.display_name || user.username;
  const go = (path) => { setOpen(false); navigate(path); };

  return (
    <Popover open={open} onClose={() => setOpen(false)} className="usermenu-pop" trigger={
      <button style={{ border: "none", background: "none", padding: 0, display: "block", borderRadius: "50%" }}
              aria-label="Account menu" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <UserAvatar url={user.avatar_url} name={name} size={34} />
      </button>
    }>
      <div className="usermenu-head">
        <div className="usermenu-name">{name}</div>
        <div className="usermenu-email muted">{user.email}</div>
      </div>
      {!user.email_verified && (
        <div className="usermenu-warn">Email not verified — check your inbox to unlock translation & uploads.</div>
      )}
      {usage && !usage.unlimited && (
        <div className="usermenu-usage">
          <div>
            <div className="usermenu-quota-top"><span>Chapters translated</span><span className="muted">{usage.usage.translated_chapters} / {usage.limits.translated_chapters}</span></div>
            <ProgressBar size="xs" value={usage.limits.translated_chapters > 0 ? (usage.usage.translated_chapters / usage.limits.translated_chapters) * 100 : 0} />
          </div>
          <div>
            <div className="usermenu-quota-top"><span>OCR pages</span><span className="muted">{usage.usage.ocr_pages} / {usage.limits.ocr_pages}</span></div>
            <ProgressBar size="xs" value={usage.limits.ocr_pages > 0 ? (usage.usage.ocr_pages / usage.limits.ocr_pages) * 100 : 0} />
          </div>
        </div>
      )}
      <div className="menu-sep" />
      <MenuItem icon="user" onClick={() => go(`/u/${encodeURIComponent(user.username)}`)}>Profile</MenuItem>
      <MenuItem icon="gear" onClick={() => go("/account")}>Account & settings</MenuItem>
      {user.role === "admin" && <MenuItem icon="shield" onClick={() => go("/admin")}>Admin</MenuItem>}
      <div className="menu-sep" />
      <MenuItem icon="arrowLeft" onClick={() => { setOpen(false); logout(); }}>Sign out</MenuItem>
    </Popover>
  );
}

/* Cmd/Ctrl+K palette: your library instantly, the shared library remotely,
   and (inside a novel) codex entities. */
function CommandPalette({ onClose, novelId, ceiling }) {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [focus, setFocus] = useState(0);
  const debQ = useDebounce(q, 200);
  const { data: novels } = useNovelsQuery();
  const [remote, setRemote] = useState([]);
  const [entities, setEntities] = useState([]);
  const inputRef = useRef(null);

  useEffect(() => { inputRef.current && inputRef.current.focus(); }, []);

  useEffect(() => {
    if (!debQ.trim()) { setRemote([]); setEntities([]); return; }
    let cancel = false;
    experienceApi.discover({ q: debQ.trim(), limit: 6 })
      .then(r => { if (!cancel) setRemote(Array.isArray(r) ? r : (r.items || [])); })
      .catch(() => {});
    if (novelId != null && ceiling != null) {
      codexApi.listEntities(novelId, ceiling, { q: debQ.trim() })
        .then(rows => { if (!cancel) setEntities(rows.slice(0, 6)); })
        .catch(() => {});
    }
    return () => { cancel = true; };
  }, [debQ, novelId, ceiling]);

  const lib = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return (novels || []).slice(0, 6);
    return (novels || []).filter(n =>
      n.title.toLowerCase().includes(needle) || (n.author || "").toLowerCase().includes(needle)
    ).slice(0, 6);
  }, [novels, q]);

  const items = useMemo(() => {
    const out = [];
    lib.forEach(n => out.push({ group: "Your library", label: n.title, meta: n.author, run: () => navigate(`/n/${n.id}`) }));
    entities.forEach(e => out.push({ group: "Codex", label: e.name, meta: e.type, run: () => navigate(`/n/${novelId}/codex/e/${e.id}`) }));
    remote.forEach(n => out.push({ group: "Shared library", label: n.title, meta: n.owner_username ? "@" + n.owner_username : n.author, run: () => navigate(`/n/${n.id}`) }));
    return out;
  }, [lib, remote, entities, navigate, novelId]);

  useEffect(() => { setFocus(0); }, [items.length, q]);

  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setFocus(f => Math.min(items.length - 1, f + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setFocus(f => Math.max(0, f - 1)); }
    else if (e.key === "Enter" && items[focus]) { items[focus].run(); onClose(); }
    else if (e.key === "Escape") onClose();
  };

  let lastGroup = null;
  return (
    <div className="palette-scrim" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search">
        <div className="palette-input">
          <Icon name="search" size={17} className="muted" />
          <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={onKey}
                 placeholder="Search your library, the shared library…" />
          <kbd style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--muted)" }}>esc</kbd>
        </div>
        <div className="palette-list">
          {items.length === 0 && <div className="palette-empty">{q.trim() ? "No matches." : "Type to search."}</div>}
          {items.map((it, i) => {
            const showGroup = it.group !== lastGroup;
            lastGroup = it.group;
            return (
              <React.Fragment key={i}>
                {showGroup && <div className="palette-group">{it.group}</div>}
                <button className={"palette-item" + (i === focus ? " focused" : "")}
                        onMouseEnter={() => setFocus(i)}
                        onClick={() => { it.run(); onClose(); }}>
                  <Icon name={it.group === "Codex" ? "spark" : "book"} size={15} className="muted" />
                  <span className="truncate">{it.label}</span>
                  {it.meta && <span className="pi-meta">{it.meta}</span>}
                </button>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function Shell() {
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();
  const location = useLocation();
  const online = useOnline();
  const [sbOpen, setSbOpen] = useLocalStorage("nw-sidebar-open", true);
  const [palette, setPalette] = useState(false);
  const qc = useQueryClient();

  const novelMatch = useMatch("/n/:novelId/*");
  const novelId = novelMatch ? Number(novelMatch.params.novelId) : null;
  const { data: novel } = useNovelQuery(novelId, { enabled: novelId != null });

  const { data: jobs } = useActivityQuery();
  const activeCount = (jobs || []).filter(isActiveJob).length;
  useJobCompletionToasts(jobs);

  // Cmd/Ctrl+K opens the palette anywhere in the shell.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette(p => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Breadcrumbs from the route.
  const crumbs = useMemo(() => {
    const p = location.pathname;
    const out = [];
    if (p === "/") out.push({ label: "Home" });
    else if (p.startsWith("/library")) out.push({ label: "Library" });
    else if (p.startsWith("/discover")) out.push({ label: "Discover" });
    else if (p.startsWith("/import")) out.push({ label: "Import" });
    else if (p.startsWith("/jobs")) out.push({ label: "Jobs" });
    else if (p.startsWith("/account")) out.push({ label: "Account" });
    else if (p.startsWith("/admin")) out.push({ label: "Admin" });
    else if (p.startsWith("/u/")) out.push({ label: "Profile" });
    else if (novelId != null) {
      out.push({ label: "Library", to: "/library" });
      out.push({ label: novel ? novel.title : "…", to: `/n/${novelId}` });
      if (p.includes("/codex/e/")) out.push({ label: "Entity" });
      else if (p.endsWith("/codex")) out.push({ label: "Codex" });
      else if (p.endsWith("/ask")) out.push({ label: "Ask" });
      else if (p.endsWith("/chapters")) out.push({ label: "Chapters" });
      else if (p.endsWith("/manage")) out.push({ label: "Manage" });
    }
    return out;
  }, [location.pathname, novelId, novel]);

  const novelNav = novelId != null && [
    { to: `/n/${novelId}`, icon: "book", label: "Overview", end: true },
    { to: `/n/${novelId}/chapters`, icon: "list", label: "Chapters" },
    ...(novel && novel.codex_enabled ? [
      { to: `/n/${novelId}/codex`, icon: "compass", label: "Codex" },
      { to: `/n/${novelId}/ask`, icon: "sparkles", label: "Ask" },
    ] : []),
    ...(novel && novel.can_edit ? [{ to: `/n/${novelId}/manage`, icon: "sliders", label: "Manage" }] : []),
  ];

  return (
    <div className="shell">
      <nav className={"sidebar" + (sbOpen ? " open" : "")} aria-label="Primary">
        <Link className="sb-brand" to="/" aria-label="Tideglass home">
          <span className="brand-mark">T</span>
          <span className="sb-brand-name">Tideglass</span>
        </Link>
        {NAV.map(item => (
          <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => "sb-item" + (isActive ? " active" : "")}>
            <span className="sb-ic">
              <Icon name={item.icon} size={19} />
              {item.label === "Jobs" && activeCount > 0 && <span className="sb-badge">{activeCount}</span>}
            </span>
            <span className="sb-label">{item.label}</span>
          </NavLink>
        ))}
        {novelId != null && novel && (
          <>
            <div className="sb-sep" />
            <div className="sb-novel">
              <Link className="sb-novel-head" to={`/n/${novelId}`}>
                <span className="sb-novel-cover">
                  {novel.cover_url ? <img src={novel.cover_url} alt="" /> : null}
                </span>
                <span className="sb-novel-title">{novel.title}</span>
              </Link>
              {novelNav && novelNav.map(item => (
                <NavLink key={item.to} to={item.to} end={item.end}
                         className={({ isActive }) => "sb-item" + (isActive ? " active" : "")}>
                  <span className="sb-ic"><Icon name={item.icon} size={17} /></span>
                  <span className="sb-label">{item.label}</span>
                </NavLink>
              ))}
            </div>
          </>
        )}
        <div className="sb-spacer" />
        <button className="sb-item" onClick={() => setTheme(theme === "light" ? "dark" : "light")}
                aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}>
          <span className="sb-ic"><Icon name={theme === "light" ? "moon" : "sun"} size={18} /></span>
          <span className="sb-label">{theme === "light" ? "Dark mode" : "Light mode"}</span>
        </button>
        <button className="sb-item sb-collapse" onClick={() => setSbOpen(o => !o)}
                aria-label={sbOpen ? "Collapse sidebar" : "Expand sidebar"}>
          <span className="sb-ic"><Icon name={sbOpen ? "chevronLeft" : "chevronRight"} size={18} /></span>
          <span className="sb-label">Collapse</span>
        </button>
      </nav>

      <div className="shell-main">
        {!online && <div className="offline-banner"><Icon name="alert" size={14} /> You're offline — changes won't save.</div>}
        <header className="topbar">
          <div className="topbar-crumbs grow">
            {crumbs.map((c, i) => (
              <React.Fragment key={i}>
                {i > 0 && <Icon name="chevronRight" size={13} />}
                {c.to ? <Link to={c.to}>{c.label}</Link> : <span className="crumb-here">{c.label}</span>}
              </React.Fragment>
            ))}
          </div>
          <div className="topbar-right">
            <button className="topbar-search" onClick={() => setPalette(true)} aria-label="Search (Ctrl+K)">
              <Icon name="search" size={14} />
              Search
              <kbd>⌘K</kbd>
            </button>
            <UserMenu />
          </div>
        </header>

        {novelId != null && novelNav && (
          <div className="novel-pills">
            {novelNav.map(item => (
              <NavLink key={item.to} to={item.to} end={item.end}
                       className={({ isActive }) => "tab" + (isActive ? " active" : "")}>
                <Icon name={item.icon} size={14} /> {item.label}
              </NavLink>
            ))}
          </div>
        )}

        <main className="grow">
          <Outlet />
        </main>
      </div>

      <nav className="tabbar" aria-label="Primary">
        <div className="tabbar-inner">
          {MOBILE_NAV.map(item => (
            <NavLink key={item.to} to={item.to} end={item.end}
                     className={({ isActive }) => "tb-item" + (isActive ? " active" : "")}>
              <span style={{ position: "relative" }}>
                <Icon name={item.icon} size={21} />
                {item.label === "Jobs" && activeCount > 0 && <span className="sb-badge">{activeCount}</span>}
              </span>
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      {palette && (
        <CommandPalette onClose={() => setPalette(false)} novelId={novelId}
                        ceiling={novelId != null ? (qc.getQueryData(["ceiling", novelId]) || null) : null} />
      )}
    </div>
  );
}
