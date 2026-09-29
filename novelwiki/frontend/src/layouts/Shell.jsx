/* ============================================================
   Shell — the room every screen (except the Reader) lives in.

   · Ambient: living water + the focused book's aura behind everything.
   · Island: a floating glass header — brand, primary destinations with a
     sliding active pill, search (⌘K), the theme switch (a circular wave of
     the new light), and the account menu. Condenses as you scroll.
   · Novel capsule: inside a book, a second glass bar with its cover and
     sections (Overview · Chapters · Codex · Ask · Manage).
   · Dock: on phones the destinations move to a floating bottom dock.
   Also hosts the command palette, the offline banner, and job-completion
   toasts driven by the shared activity poller.
   ============================================================ */
import React, { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";

import { identityApi } from "../modules/identity/api.js";
import { catalogApi } from "../modules/catalog/api.js";
import { readingApi } from "../modules/reading/api.js";
import { useAuth, useTheme } from "../App.jsx";
import { Icon } from "../components/Icon.jsx";
import { Cover, ProgressBar, UserAvatar } from "../components/ui.jsx";
import { MenuItem, Popover } from "../components/overlay.jsx";
import { useToast } from "../components/toast.jsx";
import { useNovelQuery } from "../modules/catalog/queries.js";
import { isActiveJob, useActivityQuery } from "../modules/experience/queries.js";
import { useOnline } from "../lib/hooks.js";
import { ACT_KIND_LABEL } from "../lib/constants.js";
import { Ambient } from "../atmosphere/Ambient.jsx";
import { springs } from "../motion/index.js";
import { transitionTheme } from "../motion/navigation.js";

import { CommandPalette } from "./CommandPalette.jsx";

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

/* Pending contributions + tag suggestions for the Manage badge (owners only). */
function useManageInbox(novelId, enabled) {
  const { data } = useQuery({
    queryKey: ["manage-inbox", novelId],
    enabled: !!enabled && novelId != null,
    staleTime: 60_000,
    queryFn: async () => {
      const [c, t] = await Promise.all([
        readingApi.contributions(novelId).catch(() => []),
        catalogApi.tagSuggestions(novelId).catch(() => []),
      ]);
      return (c || []).length + (t || []).length;
    },
  });
  return data || 0;
}

function useScrolled(threshold = 24) {
  const [state, setState] = useState({ scrolled: false, hidden: false });
  useEffect(() => {
    let last = window.scrollY;
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const y = window.scrollY;
        const dy = y - last;
        setState(s => {
          const scrolled = y > threshold;
          let hidden = s.hidden;
          if (Math.abs(dy) > 8) hidden = dy > 0 && y > 140;
          if (y < 80) hidden = false;
          return s.scrolled === scrolled && s.hidden === hidden ? s : { scrolled, hidden };
        });
        if (Math.abs(dy) > 8) last = y;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { window.removeEventListener("scroll", onScroll); cancelAnimationFrame(raf); };
  }, [threshold]);
  return state;
}

function BrandMark({ size = 34 }) {
  return (
    <span className="brand-mark" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 40 40" width={size} height={size}>
        <defs>
          <radialGradient id="bm-fill" cx="32%" cy="26%" r="78%">
            <stop offset="0" style={{ stopColor: "oklch(0.97 0.04 var(--accent-h))" }} />
            <stop offset="0.45" style={{ stopColor: "var(--accent)" }} />
            <stop offset="1" style={{ stopColor: "var(--accent-2)" }} />
          </radialGradient>
          <clipPath id="bm-clip"><circle cx="20" cy="20" r="17" /></clipPath>
        </defs>
        <circle cx="20" cy="20" r="17" fill="url(#bm-fill)" />
        <g clipPath="url(#bm-clip)">
          <path className="bm-wave bm-wave-1" d="M-6 24c5-4 9-4 14 0s9 4 14 0 9-4 14 0 9 4 14 0v20H-6z" fill="oklch(1 0 0 / 0.28)" />
          <path className="bm-wave bm-wave-2" d="M-6 28c5-3.5 9-3.5 14 0s9 3.5 14 0 9-3.5 14 0 9 3.5 14 0v20H-6z" fill="oklch(1 0 0 / 0.22)" />
        </g>
        <circle cx="20" cy="20" r="17" fill="none" stroke="oklch(1 0 0 / 0.45)" strokeWidth="1" />
        <circle cx="14" cy="13" r="3.2" fill="oklch(1 0 0 / 0.7)" />
      </svg>
    </span>
  );
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const dark = theme === "dark";
  const toggle = (e) => {
    const next = dark ? "light" : "dark";
    const r = e.currentTarget.getBoundingClientRect();
    transitionTheme(() => {
      document.documentElement.setAttribute("data-theme", next);
      setTheme(next);
    }, { x: r.left + r.width / 2, y: r.top + r.height / 2 });
  };
  return (
    <button className="shell-tool theme-toggle" onClick={toggle} data-theme-now={theme}
            aria-label={dark ? "Switch to light theme" : "Switch to dark theme"} title={dark ? "Light theme" : "Dark theme"}>
      <span className="tt-icon tt-sun"><Icon name="sun" size={18} /></span>
      <span className="tt-icon tt-moon"><Icon name="moon" size={17} /></span>
    </button>
  );
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
      <button className="avatar-trigger" aria-label="Account menu" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <UserAvatar url={user.avatar_url} name={name} size={36} />
      </button>
    }>
      <div className="usermenu-head">
        <UserAvatar url={user.avatar_url} name={name} size={44} />
        <div className="grow">
          <div className="usermenu-name">{name}</div>
          <div className="usermenu-email">{user.email}</div>
        </div>
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
      <MenuItem icon="logout" onClick={() => { setOpen(false); logout(); }}>Sign out</MenuItem>
    </Popover>
  );
}

function IslandLink({ item, badge }) {
  return (
    <NavLink to={item.to} end={item.end} className={({ isActive }) => "island-link" + (isActive ? " active" : "")}>
      {({ isActive }) => (
        <>
          {isActive && <motion.span layoutId="island-pill" className="island-pill" transition={springs.layout} aria-hidden="true" />}
          <Icon name={item.icon} size={17} />
          <span className="island-label">{item.label}</span>
          {badge > 0 && <span className="island-badge" aria-label={`${badge} active`}>{badge}</span>}
        </>
      )}
    </NavLink>
  );
}

function NovelCapsule({ novelId, novel }) {
  const inbox = useManageInbox(novelId, novel && novel.can_edit);
  const items = [
    { to: `/n/${novelId}`, icon: "book", label: "Overview", end: true },
    { to: `/n/${novelId}/chapters`, icon: "list", label: "Chapters" },
    ...(novel && novel.codex_enabled ? [
      { to: `/n/${novelId}/codex`, icon: "compass", label: "Codex" },
      { to: `/n/${novelId}/ask`, icon: "sparkles", label: "Ask" },
    ] : []),
    ...(novel && novel.can_edit ? [{ to: `/n/${novelId}/manage`, icon: "sliders", label: "Manage", badge: inbox }] : []),
  ];
  return (
    <div className="novel-capsule-wrap">
      <nav className="novel-capsule" aria-label="Novel sections">
        <Link className="nc-book" to={`/n/${novelId}`} aria-label={novel ? `${novel.title} overview` : "Novel overview"}>
          <Cover src={novel && novel.cover_url} title={novel ? novel.title : ""} className="nc-cover" />
          <span className="nc-title">{novel ? novel.title : "…"}</span>
        </Link>
        <span className="nc-sep" aria-hidden="true" />
        <div className="nc-links">
          {items.map(item => (
            <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => "nc-link" + (isActive ? " active" : "")}>
              {({ isActive }) => (
                <>
                  {isActive && <motion.span layoutId="nc-pill" className="nc-pill" transition={springs.layout} aria-hidden="true" />}
                  <Icon name={item.icon} size={15} />
                  <span>{item.label}</span>
                  {item.badge > 0 && <span className="tab-count">{item.badge}</span>}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}

export function Shell() {
  const location = useLocation();
  const online = useOnline();
  const [palette, setPalette] = useState(false);
  const qc = useQueryClient();
  const { scrolled, hidden } = useScrolled();

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

  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

  return (
    <div className="shell" data-route={location.pathname.split("/")[1] || "home"}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <Ambient />

      <header className={"shell-top" + (scrolled ? " is-scrolled" : "") + (hidden ? " is-hidden" : "")}>
        <Link className="brand" to="/" aria-label="Tideglass home">
          <BrandMark />
          <span className="brand-word">Tideglass</span>
        </Link>

        <nav className="island" aria-label="Primary">
          {NAV.map(item => (
            <IslandLink key={item.to} item={item} badge={item.label === "Jobs" ? activeCount : 0} />
          ))}
        </nav>

        <div className="shell-tools">
          <button className="shell-tool search-trigger" onClick={() => setPalette(true)} aria-label="Search (Ctrl+K)">
            <Icon name="search" size={17} />
            <span className="st-text">Search</span>
            <kbd>{mac ? "⌘" : "Ctrl"} K</kbd>
          </button>
          <ThemeToggle />
          <UserMenu />
        </div>
      </header>

      <div className="shell-main">
        {!online && <div className="offline-banner" role="status"><Icon name="alert" size={14} /> You're offline — changes won't save.</div>}
        {novelId != null && <NovelCapsule novelId={novelId} novel={novel} />}
        <main className="grow" id="main-content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>

      <nav className="dock" aria-label="Primary">
        {MOBILE_NAV.map(item => (
          <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => "dock-item" + (isActive ? " active" : "")}>
            {({ isActive }) => (
              <>
                {isActive && <motion.span layoutId="dock-blob" className="dock-blob" transition={springs.layout} aria-hidden="true" />}
                <span className="dock-icon">
                  <Icon name={item.icon} size={21} />
                  {item.label === "Jobs" && activeCount > 0 && <span className="island-badge">{activeCount}</span>}
                </span>
                <span className="dock-label">{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {palette && (
        <CommandPalette onClose={() => setPalette(false)} novelId={novelId}
                        ceiling={novelId != null ? (qc.getQueryData(["ceiling", novelId]) ?? novel?.progress?.max_chapter_read ?? 0) : null} />
      )}
    </div>
  );
}
