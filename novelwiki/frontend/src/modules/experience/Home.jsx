/* ============================================================
   Home — the reading room at the current hour.
   A greeting under tonight's real moon; the book you're in, floating in a
   spotlight tinted by its own jacket; the rest of the nightstand; fresh
   chapters; the quiet hum of background work; the shared shelves.
   ============================================================ */
import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../../App.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Cover, ProgressBar, ProgressRing, Skeleton, RelativeTime } from "../../components/ui.jsx";
import { TextReveal } from "../../motion/TextReveal.jsx";
import { useReadySignal } from "../../motion/navigation.js";
import { useBookAtmosphere } from "../../atmosphere/store.js";
import { AddNovelDialog } from "../catalog/index.js";
import { useNovelsQuery } from "../catalog/queries.js";
import { isActiveJob, useActivityQuery, useHomeQuery } from "./queries.js";
import { activityProgress, activityFraction, ACT_KIND_LABEL, ACT_KIND_ICON } from "../../lib/constants.js";
import { fmtChapter } from "../../lib/utils.js";
import { useTitle } from "../../lib/hooks.js";
import { MoonPhase } from "./MoonPhase.jsx";

const resumeChapter = n => n.last_chapter ?? n.min_chapter ?? 1;

const HOURS = [
  { until: 5, part: "Up late", lines: ["The house is asleep. The story isn't.", "Just one more chapter — we won't tell."] },
  { until: 12, part: "Good morning", lines: ["The tide is out. Your stories are waiting.", "A quiet page before the day begins."] },
  { until: 18, part: "Good afternoon", lines: ["A little time. Another chapter.", "Somewhere, a story is holding your place."] },
  { until: 24, part: "Good evening", lines: ["The lamps are lit. Pick up where you left off.", "A little time. Another chapter."] },
];

function hourMood(date = new Date()) {
  const h = date.getHours();
  const mood = HOURS.find(x => h < x.until) || HOURS[3];
  const line = mood.lines[(date.getDate() + h) % mood.lines.length];
  return { ...mood, line };
}

function dateLine(date = new Date()) {
  return date.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

/* ---------- the book you're in ---------- */
function Spotlight({ novel: n }) {
  const chapter = resumeChapter(n);
  const pct = n.pct_read != null ? n.pct_read : 0;
  return (
    <section className="spotlight rise" style={{ "--i": 2 }} aria-label="Continue reading" data-vt-card="">
      {n.cover_url && <div className="spotlight-backdrop" style={{ backgroundImage: `url(${JSON.stringify(n.cover_url)})` }} aria-hidden="true" />}
      <div className="spotlight-sheen" aria-hidden="true" />
      <div className="spotlight-stage">
        <Link className="spotlight-book" to={`/n/${n.id}`} tabIndex={-1} aria-hidden="true">
          <span className="spotlight-float">
            <Cover src={n.cover_url} title={n.title} author={n.author} tilt={10} />
          </span>
          <span className="spotlight-reflection" aria-hidden="true">
            <Cover src={n.cover_url} title={n.title} author={n.author} />
          </span>
        </Link>
      </div>
      <div className="spotlight-copy">
        <p className="spotlight-eyebrow">
          <span className="spotlight-dot" aria-hidden="true" />
          Continue reading
          {n.last_read_at && <><span aria-hidden="true">·</span><RelativeTime iso={n.last_read_at} prefix="Last read " /></>}
        </p>
        <h2 className="spotlight-title"><Link to={`/n/${n.id}`}>{n.title}</Link></h2>
        {n.author && <p className="spotlight-author">{n.author}</p>}
        <div className="spotlight-where">
          <ProgressRing value={pct} size={54} stroke={3} label={`Reading progress for ${n.title}`}>
            {n.pct_read != null ? `${pct}%` : ""}
          </ProgressRing>
          <div>
            <span className="spotlight-chapter">Chapter {fmtChapter(chapter)}</span>
            {n.resume_chapter_title && <span className="spotlight-chapter-title">{n.resume_chapter_title}</span>}
            <span className="spotlight-of">{n.pct_read != null ? `${pct}% through your story` : "Your place is saved"}{n.chapter_count ? ` · ${n.chapter_count} chapters` : ""}</span>
          </div>
        </div>
        <div className="spotlight-actions">
          <Link className="btn btn-primary lg" to={`/n/${n.id}/read/${chapter}`}>Continue reading <Icon name="arrowRight" size={18} /></Link>
          {n.audio_chapters > 0 && <Link className="btn btn-ghost lg" to={`/n/${n.id}/read/${chapter}?listen=1`}><Icon name="headphones" size={18} /> Listen</Link>}
        </div>
      </div>
      <div className="spotlight-tideline" aria-hidden="true"><span style={{ width: `${pct}%` }} /></div>
    </section>
  );
}

function SpotlightSkeleton() {
  return (
    <div className="spotlight is-loading" role="status" aria-label="Loading your reading room">
      <div className="spotlight-stage"><Skeleton variant="cover" style={{ width: 190 }} /></div>
      <div className="spotlight-copy">
        <Skeleton variant="text" width="30%" />
        <Skeleton variant="text" width="70%" height={44} style={{ margin: "18px 0 14px" }} />
        <Skeleton variant="text" width="40%" />
        <Skeleton variant="text" width="55%" style={{ marginTop: 30 }} />
      </div>
    </div>
  );
}

function StartReading() {
  return (
    <section className="spotlight spotlight-empty rise" style={{ "--i": 2 }} aria-label="Continue reading">
      <div className="spotlight-copy">
        <p className="spotlight-eyebrow"><span className="spotlight-dot" aria-hidden="true" /> Your nightstand is clear</p>
        <h2 className="spotlight-title">Your next story is waiting</h2>
        <p className="spotlight-author">Choose a book from your library and make yourself at home.</p>
        <div className="spotlight-actions">
          <Link className="btn btn-primary lg" to="/library">Open your library <Icon name="arrowRight" size={18} /></Link>
        </div>
      </div>
    </section>
  );
}

/* Home's own query failed: say so where the book would be, and keep the
   destinations and background work beside it (they load separately). */
function SpotlightError({ retry }) {
  return (
    <section className="spotlight spotlight-empty spotlight-error" role="alert">
      <div className="spotlight-copy">
        <p className="spotlight-eyebrow"><Icon name="alert" size={14} /> Something went adrift</p>
        <h2 className="spotlight-title">Your reading room couldn't load</h2>
        <p className="spotlight-author">Your books and progress are still saved. Try loading them again.</p>
        <div className="spotlight-actions">
          <Button icon="refresh" onClick={() => retry()}>Try again</Button>
        </div>
      </div>
    </section>
  );
}

/* ---------- a shelf of covers ---------- */
function Book({ novel: n, progress = false, index = 0 }) {
  const chapter = resumeChapter(n);
  return (
    <article className="shelf-book rise" style={{ "--i": Math.min(index, 8) }} data-vt-card="">
      <div className="shelf-book-cover">
        <Link to={`/n/${n.id}`} tabIndex={-1} aria-hidden="true"><Cover src={n.cover_url} title={n.title} author={n.author} tilt /></Link>
        {n.chapter_count > 0 && (
          <Link className="shelf-book-play" aria-label={`Read ${n.title}`} to={`/n/${n.id}/read/${chapter}`}>
            <Icon name="arrowRight" size={17} />
          </Link>
        )}
      </div>
      <Link className="shelf-book-title" to={`/n/${n.id}`}>{n.title}</Link>
      {n.author && <span className="shelf-book-sub">{n.author}</span>}
      {progress ? (
        <span className="shelf-book-progress">
          <ProgressBar size="xs" value={n.pct_read || 0} label={`Reading progress for ${n.title}`} />
          <span className="shelf-book-sub">Chapter {fmtChapter(chapter)}</span>
        </span>
      ) : (
        <span className="shelf-book-sub">
          {n.chapter_count || 0} chapters
          {n.has_audio && <Icon name="headphones" size={12} className="shelf-book-flag" />}
          {n.has_codex && <Icon name="compass" size={12} className="shelf-book-flag" />}
        </span>
      )}
    </article>
  );
}

/* The last jacket on a rail: a glass door onward, so a short shelf ends on
   an invitation instead of empty space. */
function RailEnd({ to, label, sub }) {
  return (
    <Link className="shelf-end" to={to} data-spotlight="">
      <span className="shelf-end-orb" aria-hidden="true"><Icon name="arrowRight" size={20} /></span>
      <b>{label}</b>
      {sub && <span>{sub}</span>}
    </Link>
  );
}

function Section({ eyebrow, title, action, children, className = "" }) {
  return (
    <section className={["home-section", className].filter(Boolean).join(" ")}>
      <div className="home-section-head">
        <div>
          {eyebrow && <p className="section-eyebrow">{eyebrow}</p>}
          <h2>{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

/* ---------- background work ---------- */
function BackgroundWork({ loading, error, retry, jobs }) {
  return (
    <div className="tide-work glass-card">
      <div className="tide-work-head">
        <h3>Background work</h3>
        <Link className="linkish" to="/jobs">View all <Icon name="arrowRight" size={13} /></Link>
      </div>
      {loading ? <p className="tide-work-quiet" role="status"><span className="spinner" aria-hidden /> Checking background work…</p>
        : error ? (
          <div className="tide-work-error" role="alert">
            <p>Background work couldn't load.</p>
            <Button size="sm" variant="ghost" icon="refresh" onClick={() => retry()}>Try again</Button>
          </div>
        ) : jobs.length ? (
          <ul className="tide-work-list">
            {jobs.slice(0, 3).map((j, i) => {
              const frac = activityFraction(j);
              const label = ACT_KIND_LABEL[j.kind] || j.kind;
              // An import waiting on the reader opens that import, not the job list.
              const yourTurn = j.source === "import" && (j.status === "awaiting_review" || j.status === "awaiting_ocr_confirm");
              return (
                <li key={`${j.source}:${j.id}`} className="rise" style={{ "--i": i }}>
                  <Link className="tide-work-row" to={yourTurn ? `/import?job=${j.id}` : "/jobs"}>
                    <span className={"work-orb" + (j.status === "queued" ? " is-queued" : "")} aria-hidden="true"><Icon name={ACT_KIND_ICON[j.kind] || "sparkles"} size={14} /></span>
                    <span className="tide-work-text">
                      <b>{label}</b>
                      <small>{activityProgress(j) || j.status}</small>
                      {frac != null && <ProgressBar size="xs" live value={frac * 100} label={`${label} progress`} />}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="tide-work-quiet"><span className="calm-orb" aria-hidden="true"><Icon name="check" size={13} sw={2.4} /></span> All quiet. You're ready to read.</p>
        )}
    </div>
  );
}

function Horizon({ count, loading, error }) {
  return (
    <nav className="horizon" aria-label="Destinations">
      <Link className="horizon-tile" to="/library" data-spotlight="">
        <span className="horizon-icon"><Icon name="library" size={20} /></span>
        <span className="horizon-text"><b>Your collection</b><span>{loading ? "Loading your books…" : error ? "Open your saved library" : `${count} ${count === 1 ? "book" : "books"}, ready when you are`}</span></span>
        <Icon name="arrowUpRight" size={16} className="horizon-arrow" />
      </Link>
      <Link className="horizon-tile" to="/discover" data-spotlight="">
        <span className="horizon-icon"><Icon name="compass" size={20} /></span>
        <span className="horizon-text"><b>Something new</b><span>Explore the shared library</span></span>
        <Icon name="arrowUpRight" size={16} className="horizon-arrow" />
      </Link>
      <Link className="horizon-tile" to="/import" data-spotlight="">
        <span className="horizon-icon"><Icon name="upload" size={20} /></span>
        <span className="horizon-text"><b>Bring a book</b><span>Import an EPUB or PDF</span></span>
        <Icon name="arrowUpRight" size={16} className="horizon-arrow" />
      </Link>
    </nav>
  );
}

/* ---------- first visit ---------- */
function Welcome({ onAdd, newest }) {
  return (
    <div className="page home welcome-room">
      <div className="welcome-hero">
        <MoonPhase size={220} className="welcome-moon" />
        <p className="section-eyebrow rise">Welcome to Tideglass</p>
        <h1 className="welcome-title"><TextReveal text="A place for your" /><br /><em><TextReveal text="next chapter." delay={260} /></em></h1>
        <p className="welcome-lede rise" style={{ "--i": 6 }}>Bring your stories together. Pick up where you left off, listen along, and explore the world of a novel at your own pace — without ever reading ahead of yourself.</p>
      </div>
      <div className="welcome-paths">
        <button className="welcome-path rise" style={{ "--i": 8 }} onClick={onAdd} data-spotlight="">
          <span className="horizon-icon"><Icon name="link" size={22} /></span>
          <b>Add a webnovel</b><span>Start with a link to its first chapter.</span>
          <Icon name="arrowRight" size={18} className="horizon-arrow" />
        </button>
        <Link className="welcome-path rise" style={{ "--i": 9 }} to="/import" data-spotlight="">
          <span className="horizon-icon"><Icon name="upload" size={22} /></span>
          <b>Bring a book</b><span>Import an EPUB or PDF from your device.</span>
          <Icon name="arrowRight" size={18} className="horizon-arrow" />
        </Link>
        <Link className="welcome-path rise" style={{ "--i": 10 }} to="/discover" data-spotlight="">
          <span className="horizon-icon"><Icon name="compass" size={22} /></span>
          <b>Find your next read</b><span>Explore books in the shared library.</span>
          <Icon name="arrowRight" size={18} className="horizon-arrow" />
        </Link>
      </div>
      {newest.length > 0 && (
        <Section eyebrow="Shared library" title="From the shared library">
          <div className="shelf-rail">{newest.map((n, i) => <Book key={n.id} novel={n} index={i} />)}</div>
        </Section>
      )}
    </div>
  );
}

export function Home() {
  const { user } = useAuth();
  const { data, isLoading, isError, refetch } = useHomeQuery();
  const { data: novels, isLoading: libraryLoading, isError: libraryError } = useNovelsQuery();
  const { data: jobs, isLoading: activityLoading, isError: activityError, refetch: retryActivity } = useActivityQuery();
  const [adding, setAdding] = useState(false);
  const navigate = useNavigate();
  const qc = useQueryClient();
  useTitle();

  const reading = data?.continue_reading || [];
  const updated = data?.updated_in_library || [];
  const newest = data?.newest || [];
  const active = (jobs || []).filter(isActiveJob);
  const name = user?.display_name || user?.username || "reader";
  const mood = hourMood();
  useBookAtmosphere(reading[0] || null);
  useReadySignal("home", !isLoading);

  const firstRun = !isLoading && !libraryLoading && !libraryError && !isError && !activityLoading && !activityError && data && !novels?.length && !reading.length && !updated.length && !active.length && !data.recent_imports?.length;
  const addDialog = adding && <AddNovelDialog onClose={() => setAdding(false)} onCreated={id => {
    setAdding(false);
    qc.invalidateQueries({ queryKey: ["novels"] });
    qc.invalidateQueries({ queryKey: ["home"] });
    navigate(`/n/${id}`);
  }} />;
  if (firstRun) return <><Welcome onAdd={() => setAdding(true)} newest={newest} />{addDialog}</>;

  return (
    <div className="page home">
      <header className="home-hero">
        <MoonPhase size={200} className="home-moon" />
        <div className="home-hero-copy">
          <p className="section-eyebrow rise">{dateLine()}</p>
          <h1 className="home-greeting">
            <TextReveal text={`${mood.part},`} />{" "}
            <em className="home-name"><TextReveal text={name} delay={180} /></em>
          </h1>
          <p className="home-tidbit rise" style={{ "--i": 4 }}>{mood.line}</p>
        </div>
        <div className="home-hero-actions rise" style={{ "--i": 5 }}>
          <Link className="btn btn-ghost" to="/import"><Icon name="upload" size={16} /> Import a book</Link>
          <Button variant="ghost" icon="plus" onClick={() => setAdding(true)}>Add novel</Button>
        </div>
      </header>

      <div className="home-desk">
        {isError ? <SpotlightError retry={refetch} /> : isLoading ? <SpotlightSkeleton /> : reading.length ? <Spotlight novel={reading[0]} /> : <StartReading />}
        <aside className="home-aside rise" style={{ "--i": 4 }} aria-label="Reading room activity">
          <Horizon count={novels?.length || 0} loading={libraryLoading} error={libraryError} />
          <BackgroundWork loading={activityLoading} error={activityError} retry={retryActivity} jobs={active} />
        </aside>
      </div>

      {!isError && (
        <>

          {reading.length > 1 && (
            <Section eyebrow="In progress" title="Also on your nightstand"
                     action={<Link className="linkish" to="/library">Your library <Icon name="arrowRight" size={14} /></Link>}>
              <div className="shelf-rail">
                {reading.slice(1).map((n, i) => <Book key={n.id} novel={n} progress index={i} />)}
                <RailEnd to="/library" label="Your library" sub={novels?.length ? `${novels.length} ${novels.length === 1 ? "book" : "books"}` : null} />
              </div>
            </Section>
          )}

          {updated.length > 0 && (
            <Section eyebrow="In your library" title="Chapters waiting">
              <div className="fresh-list">
                {updated.map((n, i) => (
                  <Link className="newrow rise" style={{ "--i": i }} key={n.id} to={`/n/${n.id}/chapters`} data-vt-card="" data-spotlight="">
                    <Cover src={n.cover_url} title={n.title} />
                    <span className="newrow-text">
                      <span className="newrow-title">{n.title}</span>
                      <span className="newrow-sub">{n.author ? `${n.author} · ` : ""}{n.source_updated_at ? <>updated <RelativeTime iso={n.source_updated_at} /></> : "updated recently"}</span>
                    </span>
                    <span className="newrow-count" aria-label={`${n.new_chapters} unread ${n.new_chapters === 1 ? "chapter" : "chapters"}`}>
                      {n.new_chapters.toLocaleString()}<small>unread</small>
                    </span>
                    <Icon name="arrowRight" size={18} className="newrow-arrow" />
                  </Link>
                ))}
              </div>
            </Section>
          )}

          {newest.length > 0 && (
            <Section eyebrow="Shared library" title="New in the shared library"
                     action={<Link className="linkish" to="/discover">Browse all <Icon name="arrowRight" size={14} /></Link>}>
              <div className="shelf-rail">
                {newest.map((n, i) => <Book key={n.id} novel={n} index={i} />)}
                <RailEnd to="/discover" label="Browse all" sub="Discover more stories" />
              </div>
            </Section>
          )}
        </>
      )}
      {addDialog}
    </div>
  );
}
