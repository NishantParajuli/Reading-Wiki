/* ============================================================
   Profile pieces: the moonlit hero (glowing orb, display name, bio),
   count-up figures, book shelves with tilting jackets, and the loading
   composition that mirrors the finished layout.
   ============================================================ */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, Cover, IconButton, ProgressBar, Skeleton, UserAvatar } from "../../components/ui.jsx";
import { motion, rise, stagger } from "../../motion/index.js";
import { NumberTicker } from "../../motion/NumberTicker.jsx";
import { TextReveal } from "../../motion/TextReveal.jsx";
import { prefersReducedMotion } from "../../motion/navigation.js";
import { fmtChapter } from "../../lib/utils.js";

const STATS = [
  ["library_count", "In library"],
  ["reading_count", "Reading now"],
  ["completed_count", "Completed"],
  ["chapters_read", "Chapters read"],
];

export function ProfileHero({ data, feature, onEdit, onAppearance }) {
  const name = data.display_name || data.username;
  const joined = data.created_at
    ? new Date(data.created_at).toLocaleDateString(undefined, { year: "numeric", month: "long" })
    : null;
  const s = data.stats || {};
  return (
    <section className="pf-hero" aria-labelledby="pf-name">
      <div className="pf-orb" aria-hidden="true">
        <span className="pf-orb-ripples" />
        <span className="pf-orb-halo" />
        <span className="pf-orb-ring" />
        <span className="pf-orb-ring pf-orb-ring-late" />
        <span className="pf-orb-core">
          <UserAvatar url={data.avatar_url} name={name} size={176} className="pf-orb-avatar" />
          <span className="pf-orb-gloss" />
        </span>
      </div>

      <div className="pf-id">
        <p className="section-eyebrow pf-eyebrow rise" style={{ "--i": 1 }}>
          {data.is_self ? "Your public profile" : "Reader"}
          {data.role === "admin" && <Chip tone="accent" icon="shield">Admin</Chip>}
        </p>
        <TextReveal as="h1" id="pf-name" className="pf-name" text={name} delay={120} step={90} />
        <p className="pf-meta rise" style={{ "--i": 4 }}>
          <span className="pf-handle">@{data.username}</span>
          {joined && <><span className="pf-sep" aria-hidden="true" /><span>Joined {joined}</span></>}
        </p>
        {data.bio && <p className="pf-bio rise" style={{ "--i": 5 }}>{data.bio}</p>}
        {data.is_self && (
          <div className="pf-actions rise" style={{ "--i": 6 }}>
            <Button variant="ghost" size="sm" icon="edit" onClick={onEdit}>Account & settings</Button>
            <Button variant="ghost" size="sm" icon="palette" onClick={onAppearance}>Appearance</Button>
          </div>
        )}
      </div>

      {feature && <NowReading n={feature} />}

      <dl className="pf-stats rise" style={{ "--i": 6 }}>
        {STATS.map(([key, label], i) => (
          <div key={key} className="pf-stat" style={{ "--i": i }}>
            <dt>{label}</dt>
            <dd><NumberTicker value={Number(s[key]) || 0} duration={1.4} /></dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function bookMeta(n, kind) {
  if (kind === "reading" && n.last_chapter != null) {
    const pct = n.max_chapter ? Math.round(Math.min(100, (n.last_chapter / n.max_chapter) * 100)) : null;
    const text = n.max_chapter
      ? `Ch. ${fmtChapter(n.last_chapter)} of ${fmtChapter(n.max_chapter)}`
      : `Ch. ${fmtChapter(n.last_chapter)}`;
    return { pct, text };
  }
  if (kind === "finished") return { pct: null, text: "Finished", icon: "circleCheck" };
  const count = n.chapter_count != null ? `${n.chapter_count.toLocaleString()} chapters` : null;
  const vis = n.visibility === "global" ? "Global" : n.visibility === "public" ? "Public" : null;
  return { pct: null, text: [count, vis].filter(Boolean).join(" · "), icon: n.visibility === "global" ? "globe" : null };
}

/* The book on the nightstand, lifted into the hero. */
function NowReading({ n }) {
  const meta = bookMeta(n, "reading");
  return (
    <Link className="pf-feature rise" style={{ "--i": 5 }} to={`/n/${n.id}`} data-vt-card="">
      <span className="pf-feature-glow" aria-hidden="true" />
      <Cover src={n.cover_url} title={n.title} tilt={10} />
      <span className="pf-feature-cap">
        <span className="pf-feature-eyebrow"><span className="pf-live-dot" aria-hidden="true" />Now reading</span>
        <span className="pf-feature-title">{n.title}</span>
        {meta.text && <span className="pf-feature-meta">{meta.text}</span>}
        {meta.pct != null && <ProgressBar size="xs" value={meta.pct} label={`${n.title}: ${meta.pct}% read`} />}
      </span>
    </Link>
  );
}

function BookCard({ n, kind }) {
  const meta = bookMeta(n, kind);
  return (
    <motion.div className="pf-book-cell" variants={rise}>
      <Link className="pf-book" to={`/n/${n.id}`} title={n.title} data-vt-card="">
        <Cover src={n.cover_url} title={n.title} tilt={8} />
        <span className="pf-book-title">{n.title}</span>
        {meta.pct != null && <ProgressBar size="xs" value={meta.pct} label={`${n.title}: ${meta.pct}% read`} />}
        {meta.text && (
          <span className="pf-book-meta">
            {meta.icon && <Icon name={meta.icon} size={12} />}
            {meta.text}
          </span>
        )}
      </Link>
    </motion.div>
  );
}

/* A horizontal shelf: snap scrolling, edge fades that appear only when
   there is more to see, and paging buttons for pointer users. */
export function Shelf({ id, eyebrow, title, items, kind }) {
  const railRef = useRef(null);
  const frame = useRef(0);
  const [edges, setEdges] = useState({ start: true, end: true });
  const measure = useCallback(() => {
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => {
      const el = railRef.current;
      if (!el) return;
      const start = el.scrollLeft <= 4;
      const end = el.scrollLeft + el.clientWidth >= el.scrollWidth - 4;
      setEdges(prev => (prev.start === start && prev.end === end ? prev : { start, end }));
    });
  }, []);
  useEffect(() => {
    measure();
    const el = railRef.current;
    const ro = typeof ResizeObserver === "undefined" || !el ? null : new ResizeObserver(measure);
    if (ro) ro.observe(el);
    return () => { if (ro) ro.disconnect(); cancelAnimationFrame(frame.current); };
  }, [measure, items]);

  if (!items || items.length === 0) return null;
  const page = (dir) => {
    const el = railRef.current;
    if (el) el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: prefersReducedMotion() ? "auto" : "smooth" });
  };
  const fades = [edges.start ? "" : "fade-start", edges.end ? "" : "fade-end"].filter(Boolean).join(" ");
  return (
    <section className="pf-shelf" aria-labelledby={id}>
      <header className="pf-shelf-head">
        <div>
          <p className="section-eyebrow">{eyebrow}<span className="pf-count">{items.length}</span></p>
          <h2 id={id} className="pf-shelf-title">{title}</h2>
        </div>
        {!(edges.start && edges.end) && (
          <div className="pf-shelf-nav">
            <IconButton name="chevronLeft" label={`Scroll ${title} back`} disabled={edges.start} onClick={() => page(-1)} />
            <IconButton name="chevronRight" label={`Scroll ${title} forward`} disabled={edges.end} onClick={() => page(1)} />
          </div>
        )}
      </header>
      <motion.div ref={railRef} className={["pf-rail", fades].filter(Boolean).join(" ")} onScroll={measure}
                  variants={stagger(0.065, 0.05)} initial="hidden" whileInView="show"
                  viewport={{ once: true, amount: 0.15 }}>
        {items.map(n => <BookCard key={n.id} n={n} kind={kind} />)}
      </motion.div>
    </section>
  );
}

export function ProfileSkeleton() {
  return (
    <div className="pf-page" aria-busy="true">
      <span className="sr-only" role="status">Loading profile…</span>
      <div className="pf-hero">
        <div className="pf-orb"><Skeleton variant="circle" className="pf-skel-orb" /></div>
        <div className="pf-id pf-skel-id">
          <Skeleton variant="text" width={140} />
          <Skeleton height={72} width="min(520px, 90%)" style={{ borderRadius: 18 }} />
          <Skeleton variant="text" width={220} />
          <Skeleton variant="text" width="min(420px, 80%)" />
        </div>
        <div className="pf-stats pf-skel-stats">
          {STATS.map(([key]) => (
            <div key={key} className="pf-stat">
              <Skeleton variant="text" width={64} />
              <Skeleton height={40} width={90} style={{ borderRadius: 12 }} />
            </div>
          ))}
        </div>
      </div>
      <div className="pf-shelf">
        <Skeleton variant="text" width={180} height={28} />
        <div className="pf-rail pf-skel-rail">
          {Array.from({ length: 7 }, (_, k) => (
            <div key={k} className="pf-book-cell"><Skeleton variant="cover" /></div>
          ))}
        </div>
      </div>
    </div>
  );
}
