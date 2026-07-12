/* ============================================================
   Home — "Continue" (§6.3, the flagship redesign).
   Hero continue card with ambient cover backdrop → jump-back-in rail →
   new-chapters rows → slim activity strip → discover shelf.
   First run gets a full welcome screen.
   ============================================================ */
import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../App.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Cover, ProgressBar, Skeleton, RelativeTime } from "../../components/ui.jsx";
import { AddNovelDialog } from "../catalog/index.js";
import { isActiveJob, useActivityQuery, useHomeQuery } from "../../modules/experience/queries.js";
import { activityProgress, activityFraction, ACT_KIND_LABEL } from "../../lib/constants.js";
import { timeGreeting, fmtChapter, relativeTime } from "../../lib/utils.js";
import { useTitle } from "../../lib/hooks.js";

function heroMeta(n) {
  const bits = [];
  if (n.last_read_at) bits.push(`last read ${relativeTime(n.last_read_at)}`);
  if (n.pct_read != null && n.pct_read > 0) bits.push(`${n.pct_read}% through`);
  if (n.new_chapters > 0) bits.push(`${n.new_chapters} new chapter${n.new_chapters === 1 ? "" : "s"}`);
  return bits.join(" · ");
}

function HeroContinueCard({ n }) {
  const navigate = useNavigate();
  const resumeCh = n.last_chapter != null ? n.last_chapter : 1;
  return (
    <div className="card hero-cont">
      {n.cover_url && <div className="hero-cont-backdrop" style={{ backgroundImage: `url(${JSON.stringify(n.cover_url)})` }} aria-hidden />}
      <div className="hero-cont-scrim" aria-hidden />
      <Cover src={n.cover_url} title={n.title} />
      <div className="hero-cont-body">
        <span className="hero-cont-eyebrow"><Icon name="book" size={13} /> Continue reading</span>
        <h2 className="hero-cont-title">
          <Link to={`/n/${n.id}`} style={{ textDecoration: "none", color: "inherit" }}>{n.title}</Link>
        </h2>
        <div className="hero-cont-chapter">
          Chapter {fmtChapter(resumeCh)}
          {n.resume_chapter_title ? <> — <em>{n.resume_chapter_title}</em></> : null}
        </div>
        <ProgressBar value={n.pct_read || 0} label="Reading progress" style={{ maxWidth: 420 }} />
        <div className="hero-cont-meta">{heroMeta(n)}</div>
        <div className="hero-cont-actions">
          <Button variant="primary" size="lg" icon="book" onClick={() => navigate(`/n/${n.id}/read/${resumeCh}`)}>
            Continue reading
          </Button>
          {n.audio_chapters > 0 && (
            <Button variant="ghost" icon="headphones" onClick={() => navigate(`/n/${n.id}/read/${resumeCh}?listen=1`)}>
              Listen
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function RailCard({ n, sub, showProgress, listenable }) {
  const navigate = useNavigate();
  const resumeCh = n.last_chapter != null ? n.last_chapter : 1;
  return (
    <Link className="rail-card" to={`/n/${n.id}`}>
      <span style={{ position: "relative", display: "block" }}>
        <Cover src={n.cover_url} title={n.title} />
        <button
          className="rail-play"
          aria-label={listenable ? `Listen to ${n.title}` : `Resume ${n.title}`}
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(`/n/${n.id}/read/${resumeCh}${listenable ? "?listen=1" : ""}`); }}
        >
          <Icon name={listenable ? "headphones" : "play"} size={15} />
        </button>
      </span>
      <span className="rail-title">{n.title}</span>
      {showProgress && <ProgressBar size="xs" value={n.pct_read || 0} />}
      {sub && <span className="rail-sub">{sub}</span>}
    </Link>
  );
}

function Section({ title, right, children }) {
  return (
    <section style={{ marginTop: 30 }}>
      <div className="row" style={{ alignItems: "baseline", marginBottom: 12 }}>
        <h2 className="section-title" style={{ margin: 0 }}>{title}</h2>
        {right && <div style={{ marginLeft: "auto" }}>{right}</div>}
      </div>
      {children}
    </section>
  );
}

function ActivityStrip({ jobs }) {
  const active = (jobs || []).filter(isActiveJob).slice(0, 4);
  if (active.length === 0) return null;
  return (
    <Section title="In progress" right={<Link className="linkish" to="/jobs">View all <Icon name="arrowRight" size={13} /></Link>}>
      <div className="card activity-strip">
        {active.map(j => {
          const frac = activityFraction(j);
          return (
            <div key={`${j.source}:${j.id}`} className="activity-strip-row">
              <span className="spinner" aria-hidden />
              <span className="grow truncate">
                <b>{ACT_KIND_LABEL[j.kind] || j.kind}</b>
                {" — "}{activityProgress(j) || j.status}
              </span>
              {frac != null && <ProgressBar size="xs" value={frac * 100} />}
            </div>
          );
        })}
      </div>
    </Section>
  );
}

function Welcome({ newest, onAdd }) {
  return (
    <div className="page page-enter welcome">
      <span className="brand-mark" style={{ width: 64, height: 64, fontSize: 36, borderRadius: 18, display: "inline-grid" }}>T</span>
      <h1>Your reading life, in one place</h1>
      <p>Add a novel from the web, import an EPUB or PDF, or browse the shared library — Tideglass keeps your place, translates raws, narrates chapters, and never spoils you.</p>
      <div className="welcome-cards">
        <button className="welcome-card" onClick={onAdd}>
          <span className="wc-icon"><Icon name="sparkles" size={21} /></span>
          <b>Add from the web</b>
          <span>Point it at a first chapter and it keeps up with new releases.</span>
        </button>
        <Link className="welcome-card" to="/import">
          <span className="wc-icon"><Icon name="upload" size={21} /></span>
          <b>Import EPUB or PDF</b>
          <span>Chapters, covers and illustrations — scanned PDFs are OCR'd.</span>
        </Link>
        <Link className="welcome-card" to="/discover">
          <span className="wc-icon"><Icon name="compass" size={21} /></span>
          <b>Browse the shared library</b>
          <span>Read what others published, with your own progress.</span>
        </Link>
      </div>
      {newest && newest.length > 0 && (
        <div style={{ maxWidth: 780, margin: "44px auto 0", textAlign: "left" }}>
          <p className="section-eyebrow">From the shared library</p>
          <div className="rail">
            {newest.map(n => (
              <RailCard key={n.id} n={n} sub={`${n.chapter_count} ch.${n.owner_username ? ` · @${n.owner_username}` : ""}`} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function HomeSkeleton() {
  return (
    <>
      <div className="card hero-cont" aria-hidden>
        <Skeleton variant="cover" style={{ width: 130 }} />
        <div className="hero-cont-body" style={{ gap: 12 }}>
          <Skeleton variant="text" width={120} />
          <Skeleton variant="text" width="55%" height={22} />
          <Skeleton variant="text" width="40%" />
          <Skeleton variant="text" width="70%" height={8} />
        </div>
      </div>
      <div className="rail" aria-hidden>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="rail-card"><Skeleton variant="cover" /><Skeleton variant="text" width="80%" /></div>
        ))}
      </div>
    </>
  );
}

export function Home() {
  const { user } = useAuth();
  const { data, isLoading } = useHomeQuery();
  const { data: jobs } = useActivityQuery();
  const [adding, setAdding] = React.useState(false);
  const navigate = useNavigate();
  const qc = useQueryClient();
  useTitle();

  const name = (user && (user.display_name || user.username)) || "reader";
  const cr = (data && data.continue_reading) || [];
  const updated = (data && data.updated_in_library) || [];
  const newest = (data && data.newest) || [];
  const activeCount = (jobs || []).filter(isActiveJob).length;

  const firstRun = !isLoading && data && cr.length === 0 && (data.recent_imports || []).length === 0
    && activeCount === 0 && updated.length === 0;

  if (firstRun) {
    return (
      <>
        <Welcome newest={newest} onAdd={() => setAdding(true)} />
        {adding && (
          <AddNovelDialog onClose={() => setAdding(false)}
                          onCreated={(id) => { setAdding(false); qc.invalidateQueries({ queryKey: ["novels"] }); navigate(`/n/${id}`); }} />
        )}
      </>
    );
  }

  const tidbits = [];
  if (updated.length > 0) tidbits.push(`${updated.length} novel${updated.length === 1 ? "" : "s"} with new chapters`);
  if (activeCount > 0) tidbits.push(`${activeCount} job${activeCount === 1 ? "" : "s"} running`);

  return (
    <div className="page page-enter">
      <div className="page-head">
        <div className="grow">
          <h1 className="home-greeting">{timeGreeting(name)}</h1>
          <p className="home-tidbit">{tidbits.length ? tidbits.join(" · ") : "All caught up. Pick a story."}</p>
        </div>
        <div className="page-head-actions">
          <Button variant="ghost" icon="upload" onClick={() => navigate("/import")}>Import</Button>
          <Button variant="primary" icon="sparkles" onClick={() => setAdding(true)}>Add novel</Button>
        </div>
      </div>

      {isLoading && <HomeSkeleton />}

      {!isLoading && cr.length > 0 && <HeroContinueCard n={cr[0]} />}

      {!isLoading && cr.length > 1 && (
        <Section title="Jump back in">
          <div className="rail">
            {cr.slice(1).map(n => (
              <RailCard key={n.id} n={n} showProgress
                        listenable={n.audio_chapters > 0}
                        sub={`Ch. ${fmtChapter(n.last_chapter != null ? n.last_chapter : 1)}${n.max_chapter ? ` / ${fmtChapter(n.max_chapter)}` : ""}`} />
            ))}
          </div>
        </Section>
      )}

      {!isLoading && updated.length > 0 && (
        <Section title="New for you">
          <div className="card" style={{ padding: 8 }}>
            {updated.map(n => (
              <Link key={n.id} className="newrow" to={`/n/${n.id}/read/${fmtChapter((n.max_chapter_read || 0) + 1)}`}>
                <Cover src={n.cover_url} title={n.title} />
                <span className="grow">
                  <span className="newrow-title">{n.title}</span>
                  <span className="newrow-sub" style={{ display: "block" }}>
                    +{n.new_chapters} new chapter{n.new_chapters === 1 ? "" : "s"}
                    {n.source_updated_at ? <> · updated <RelativeTime iso={n.source_updated_at} /></> : null}
                  </span>
                </span>
                <span className="linkish">Read Ch. {fmtChapter((n.max_chapter_read || 0) + 1)} <Icon name="arrowRight" size={13} /></span>
              </Link>
            ))}
          </div>
        </Section>
      )}

      <ActivityStrip jobs={jobs} />

      {!isLoading && newest.length > 0 && (
        <Section title="New in the shared library"
                 right={<Link className="linkish" to="/discover">Browse all <Icon name="arrowRight" size={13} /></Link>}>
          <div className="rail">
            {newest.map(n => (
              <RailCard key={n.id} n={n}
                        sub={`${n.chapter_count} ch.${n.owner_username ? ` · @${n.owner_username}` : ""}`} />
            ))}
          </div>
        </Section>
      )}

      {adding && (
        <AddNovelDialog onClose={() => setAdding(false)}
                        onCreated={(id) => { setAdding(false); qc.invalidateQueries({ queryKey: ["novels"] }); navigate(`/n/${id}`); }} />
      )}
    </div>
  );
}
