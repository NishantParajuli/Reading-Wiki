/* The reading room: resume a story, find the next one, and see background work. */
import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../../App.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Cover, EmptyState, ProgressBar, Skeleton, RelativeTime } from "../../components/ui.jsx";
import { AddNovelDialog } from "../catalog/index.js";
import { useNovelsQuery } from "../catalog/queries.js";
import { isActiveJob, useActivityQuery, useHomeQuery } from "./queries.js";
import { activityProgress, activityFraction, ACT_KIND_LABEL } from "../../lib/constants.js";
import { timeGreeting, fmtChapter } from "../../lib/utils.js";
import { useTitle } from "../../lib/hooks.js";

const resumeChapter = n => n.last_chapter ?? n.min_chapter ?? 1;

function ContinueReading({ novel: n }) {
  const chapter = resumeChapter(n);
  return (
    <section className="reading-feature" aria-label="Continue reading">
      <div className="reading-feature-main">
        <Link className="reading-feature-cover" to={`/n/${n.id}`} aria-label={`About ${n.title}`}>
          <Cover src={n.cover_url} title={n.title} />
        </Link>
        <div className="reading-feature-copy">
          <h2><Link to={`/n/${n.id}`}>{n.title}</Link></h2>
          {n.author && <p className="reading-feature-author">{n.author}</p>}
          <p className="reading-feature-chapter">Chapter {fmtChapter(chapter)}{n.resume_chapter_title && <> · {n.resume_chapter_title}</>}</p>
          <div className="reading-feature-actions">
            <Link className="btn btn-primary lg" to={`/n/${n.id}/read/${chapter}`}>Continue reading <Icon name="arrowRight" size={18} /></Link>
            {n.audio_chapters > 0 && <Link className="btn btn-ghost" to={`/n/${n.id}/read/${chapter}?listen=1`}><Icon name="headphones" size={17} /> Listen</Link>}
          </div>
        </div>
      </div>
      <div className="reading-feature-foot">
        <span>{n.pct_read != null ? `${n.pct_read}% through your story` : "Your place is saved"}</span>
        {n.last_read_at && <RelativeTime iso={n.last_read_at} prefix="Last read " />}
        <ProgressBar value={n.pct_read || 0} size="xs" label={`Reading progress for ${n.title}`} />
      </div>
    </section>
  );
}

function Book({ novel: n, progress = false }) {
  return (
    <article className="rail-card">
      <div className="book-cover-wrap">
        <Link to={`/n/${n.id}`} aria-label={`About ${n.title}`}><Cover src={n.cover_url} title={n.title} /></Link>
        {n.chapter_count > 0 && <Link className="rail-play" aria-label={`Read ${n.title}`} to={`/n/${n.id}/read/${resumeChapter(n)}`}><Icon name="arrowRight" size={17} /></Link>}
      </div>
      <Link className="rail-title" to={`/n/${n.id}`}>{n.title}</Link>
      {n.author && <span className="rail-sub">{n.author}</span>}
      {progress ? <><ProgressBar size="xs" value={n.pct_read || 0} label={`Reading progress for ${n.title}`} /><span className="rail-sub">Chapter {fmtChapter(resumeChapter(n))}</span></> : <span className="rail-sub">{n.chapter_count || 0} chapters</span>}
    </article>
  );
}

function Section({ title, action, children }) {
  return <section className="home-section"><div className="home-section-head"><h2>{title}</h2>{action}</div>{children}</section>;
}

function Welcome({ onAdd, newest }) {
  return (
    <div className="page welcome reading-welcome">
      <div className="welcome-intro">
        <h1>A place for your<br /><em>next chapter.</em></h1>
        <p>Bring your stories together. Pick up where you left off, listen along, and explore the world of a novel at your own pace.</p>
      </div>
      <div className="welcome-options">
        <button onClick={onAdd}><Icon name="link" size={24} /><span><b>Add a webnovel</b><span>Start with a link to its first chapter.</span></span><Icon name="arrowRight" size={20} /></button>
        <Link to="/import"><Icon name="upload" size={24} /><span><b>Bring a book</b><span>Import an EPUB or PDF from your device.</span></span><Icon name="arrowRight" size={20} /></Link>
        <Link to="/discover"><Icon name="compass" size={24} /><span><b>Find your next read</b><span>Explore books in the shared library.</span></span><Icon name="arrowRight" size={20} /></Link>
      </div>
      {newest.length > 0 && <Section title="From the shared library"><div className="rail">{newest.map(n => <Book key={n.id} novel={n} />)}</div></Section>}
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
  const firstRun = !isLoading && !libraryLoading && !libraryError && !isError && !activityLoading && !activityError && data && !novels?.length && !reading.length && !updated.length && !active.length && !data.recent_imports?.length;
  const addDialog = adding && <AddNovelDialog onClose={() => setAdding(false)} onCreated={id => {
    setAdding(false);
    qc.invalidateQueries({ queryKey: ["novels"] });
    qc.invalidateQueries({ queryKey: ["home"] });
    navigate(`/n/${id}`);
  }} />;
  if (firstRun) return <><Welcome onAdd={() => setAdding(true)} newest={newest} />{addDialog}</>;

  return (
    <div className="page page-enter reading-home">
      <div className="page-head">
        <div className="grow"><h1 className="home-greeting">{timeGreeting(name)}</h1><p className="home-tidbit">A little time. Another chapter.</p></div>
        <div className="page-head-actions"><Link className="btn btn-ghost" to="/import"><Icon name="upload" size={16} /> Import a book</Link><Button icon="plus" onClick={() => setAdding(true)}>Add novel</Button></div>
      </div>
      {isLoading ? <div className="reading-feature loading-feature" role="status" aria-label="Loading your reading room"><Skeleton variant="cover" /><div className="grow"><Skeleton variant="text" width="65%" height={32} /><Skeleton variant="text" width="40%" /><Skeleton variant="text" width="80%" /></div></div>
        : isError ? <EmptyState icon="alert" title="Your reading room couldn't load" body="Your books and progress are still saved. Try loading them again." primaryAction={<Button icon="refresh" onClick={() => refetch()}>Try again</Button>} />
        : <>
          <div className="reading-desk">
            <div className="reading-desk-main">
              <div className="home-section-head"><h2>Continue reading</h2><Link className="linkish" to="/library">Your library <Icon name="arrowRight" size={14} /></Link></div>
              {reading.length ? <ContinueReading novel={reading[0]} /> : <div className="reading-feature start-reading"><Icon name="book" size={32} /><h2>Your next story is waiting</h2><p>Choose a book from your library and make yourself at home.</p><Link className="btn btn-primary" to="/library">Open your library <Icon name="arrowRight" size={16} /></Link></div>}
            </div>
            <aside className="reading-desk-aside" aria-label="Reading room activity">
              <h2>On your horizon</h2>
              <Link className="horizon-link" to="/library"><Icon name="library" size={19} /><span><b>Your collection</b><span>{libraryLoading ? "Loading your books…" : libraryError ? "Open your saved library" : `${novels?.length || 0} ${(novels?.length || 0) === 1 ? "book" : "books"}, ready when you are`}</span></span><Icon name="chevronRight" size={16} /></Link>
              <Link className="horizon-link" to="/discover"><Icon name="compass" size={19} /><span><b>Something new</b><span>Explore the shared library</span></span><Icon name="chevronRight" size={16} /></Link>
              <div className="home-work"><div className="home-work-head"><h3>Background work</h3><Link className="linkish" to="/jobs">View all</Link></div>
                {activityLoading ? <p role="status">Checking background work…</p> : activityError ? <div role="alert"><p>Background work couldn't load.</p><Button size="sm" variant="ghost" onClick={() => retryActivity()}>Try again</Button></div> : active.length ? active.slice(0, 3).map(j => <Link className="home-work-row" key={`${j.source}:${j.id}`} to="/jobs"><span><span className="spinner" aria-hidden /><b>{ACT_KIND_LABEL[j.kind] || j.kind}</b></span><small>{activityProgress(j) || j.status}</small>{activityFraction(j) != null && <ProgressBar size="xs" value={activityFraction(j) * 100} label={`${ACT_KIND_LABEL[j.kind] || j.kind} progress`} />}</Link>) : <p><Icon name="check" size={16} /> All quiet. You're ready to read.</p>}
              </div>
            </aside>
          </div>
          {reading.length > 1 && <Section title="Also on your nightstand"><div className="rail">{reading.slice(1).map(n => <Book key={n.id} novel={n} progress />)}</div></Section>}
          {updated.length > 0 && <Section title="Fresh chapters"><div className="new-chapters-list">{updated.map(n => <Link className="newrow" key={n.id} to={`/n/${n.id}/chapters`}><Cover src={n.cover_url} title={n.title} /><span className="grow"><span className="newrow-title">{n.title}</span><span className="newrow-sub">{n.new_chapters} new {n.new_chapters === 1 ? "chapter" : "chapters"}{n.source_updated_at && <> · <RelativeTime iso={n.source_updated_at} /></>}</span></span><Icon name="arrowRight" size={18} /></Link>)}</div></Section>}
          {newest.length > 0 && <Section title="New in the shared library" action={<Link className="linkish" to="/discover">Browse all <Icon name="arrowRight" size={14} /></Link>}><div className="rail">{newest.map(n => <Book key={n.id} novel={n} />)}</div></Section>}
        </>}
      {addDialog}
    </div>
  );
}
