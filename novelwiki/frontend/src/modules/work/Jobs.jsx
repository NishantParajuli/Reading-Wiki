/* ============================================================
   Jobs (§6.10) — one live operations view over the three durable job
   systems. Active / History tabs, rows grouped by novel, failed rows open
   into a copyable error, live updates from the shared activity poller.
   New rows glide in; finished ones settle and leave the Active tab.
   ============================================================ */
import React, { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { acquisitionApi } from "../../modules/acquisition/api.js";
import { NovelpiaRecoveryLinks } from "../acquisition/index.js";
import { narrationApi } from "../../modules/narration/api.js";
import { workApi } from "../../modules/work/api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Cover, EmptyState, PageHeader, Skeleton, Tabs } from "../../components/ui.jsx";
import { JobRow, jobPhase } from "./JobRow.jsx";
import { useToast } from "../../components/toast.jsx";
import { AnimatePresence, LayoutGroup, motion, springs } from "../../motion/index.js";
import { useNovelsQuery } from "../../modules/catalog/queries.js";
import { isActiveJob, useActivityQuery } from "../../modules/experience/queries.js";
import { useTitle } from "../../lib/hooks.js";
import { fmtDuration } from "../../lib/utils.js";
import { ACT_KIND_LABEL } from "../../lib/constants.js";

// Big surfaces travel and fade (no blur: filter on large cards is costly).
const rowMotion = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] } },
  exit: { opacity: 0, height: 0, overflow: "hidden", transition: { duration: 0.3, ease: [0.55, 0, 1, 0.45] } },
};
const panelMotion = {
  initial: { height: 0, opacity: 0 },
  animate: { height: "auto", opacity: 1, transition: { height: springs.smooth, opacity: { duration: 0.25, delay: 0.05 } } },
  exit: { height: 0, opacity: 0, transition: { duration: 0.22, ease: [0.55, 0, 1, 0.45] } },
};
const SUMMARY = [
  { phase: "working", label: "Running" },
  { phase: "queued", label: "Queued" },
  { phase: "waiting", label: "Waiting" },
  { phase: "attention", label: "Needs you" },
];

function CopyGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="9" width="11" height="11" rx="2.5" /><path d="M5 15V6a2 2 0 0 1 2-2h8" />
    </svg>
  );
}

function ErrorPanel({ job, id }) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);
  async function copy(event) {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(job.error);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
      toast("Error copied.", { tone: "ok" });
    } catch {
      toast("Couldn't copy the error. Select the text instead.", { tone: "danger" });
    }
  }
  return (
    <motion.div id={id} className="jobs-error-clip" {...panelMotion}>
      <div className="jobs-error">
        <div className="jobs-error-head">
          <span className="jobs-error-tag">Error</span>
          <span className="jobs-error-ref">
            {ACT_KIND_LABEL[job.kind] || job.kind} · #{job.id}
            {job.attempts ? ` · ${job.attempts}${job.max_attempts ? `/${job.max_attempts}` : ""} attempts` : ""}
          </span>
          <Button size="sm" variant="ghost" className="jobs-error-copy" onClick={copy}>
            {copied ? <Icon name="check" size={14} sw={2.2} /> : <CopyGlyph />}Copy
          </Button>
        </div>
        <pre className="jobs-error-text">{job.error}</pre>
        <NovelpiaRecoveryLinks kind={job.kind} error={job.error} />
      </div>
    </motion.div>
  );
}

function GroupHead({ novelId, novel, rows }) {
  const running = rows.filter(j => jobPhase(j.status) === "working").length;
  const sub = `${rows.length} job${rows.length === 1 ? "" : "s"}${running ? ` · ${running} running` : ""}`;
  if (novel) {
    return (
      <header className="jobs-group-head">
        <div className="jobs-group-id" data-vt-card="">
          <span className="jobs-group-cover" aria-hidden="true"><Cover src={novel.cover_url} title={novel.title} author={novel.author} /></span>
          <div className="jobs-group-titles">
            <Link to={`/n/${novelId}`} className="jobs-group-title">
              {novel.title}<Icon name="arrowUpRight" size={15} className="jobs-group-go" />
            </Link>
            {novel.author && <span className="jobs-group-author">{novel.author}</span>}
            <span className="jobs-group-sub">{sub}</span>
          </div>
        </div>
      </header>
    );
  }
  return (
    <header className="jobs-group-head">
      <div className="jobs-group-id">
        <span className="jobs-group-orb" aria-hidden="true"><Icon name={novelId ? "book" : "layers"} size={18} /></span>
        <div className="jobs-group-titles">
          <b className="jobs-group-title is-static">{novelId ? `Novel #${novelId}` : "General"}</b>
          <span className="jobs-group-sub">{novelId ? sub : `Not tied to a book · ${sub}`}</span>
        </div>
      </div>
    </header>
  );
}

function LoadingGroups() {
  return (
    <div className="jobs-groups" aria-busy="true">
      <span className="sr-only" role="status">Loading jobs…</span>
      {[3, 2].map((count, g) => (
        <div key={g} className="jobs-group" aria-hidden="true">
          <div className="jobs-group-head">
            <div className="jobs-group-id">
              <Skeleton variant="cover" width={44} />
              <div className="jobs-group-titles"><Skeleton variant="text" width={150} /><Skeleton variant="text" width={80} style={{ marginTop: 8 }} /></div>
            </div>
          </div>
          <div className="jobs-rows">
            {Array.from({ length: count }, (_, r) => (
              <div key={r} className="jobs-skel-row">
                <Skeleton width={38} height={38} style={{ borderRadius: 12 }} />
                <div className="grow"><Skeleton variant="text" width="38%" /><Skeleton variant="text" width="22%" style={{ marginTop: 8 }} /></div>
                <Skeleton variant="text" width={120} />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function Jobs() {
  const { data: jobs, isLoading, isError, refetch } = useActivityQuery();
  const { data: novels } = useNovelsQuery();
  const [tab, setTab] = useState("active");
  const [busyId, setBusyId] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());
  const { toast } = useToast();
  const navigate = useNavigate();
  useTitle("Jobs");

  const novelById = useMemo(() => new Map((novels || []).map(n => [n.id, n])), [novels]);

  const shown = useMemo(() => {
    const list = jobs || [];
    return tab === "active" ? list.filter(isActiveJob) : list;
  }, [jobs, tab]);

  const groups = useMemo(() => {
    const byNovel = new Map();
    for (const j of shown) {
      const key = j.novel_id || 0;
      if (!byNovel.has(key)) byNovel.set(key, []);
      byNovel.get(key).push(j);
    }
    return [...byNovel.entries()];
  }, [shown]);

  const counts = useMemo(() => {
    const tally = {};
    for (const j of (jobs || []).filter(isActiveJob)) {
      const phase = jobPhase(j.status);
      tally[phase] = (tally[phase] || 0) + 1;
    }
    return tally;
  }, [jobs]);

  async function cancel(job) {
    const rowKey = `${job.source}:${job.id}`;
    setBusyId(rowKey);
    try {
      if (job.source === "tts") await narrationApi.cancelTtsJob(job.id);
      else if (job.source === "import") await acquisitionApi.cancelImport(job.id);
      else await workApi.cancelJob(job.id);
      await refetch();
    }
    catch (e) { toast(e.message || "Cancel failed.", { tone: "danger" }); }
    finally { setBusyId(null); }
  }

  const toggle = key => setExpanded(prev => { const s = new Set(prev); s.has(key) ? s.delete(key) : s.add(key); return s; });
  const activeCount = (jobs || []).filter(isActiveJob).length;
  const summary = SUMMARY.filter(s => counts[s.phase]);
  // Layout animation measures every row on each poll; keep it to modest lists.
  const animateLayout = shown.length <= 40;

  let content;
  if (isLoading) content = <LoadingGroups />;
  else if (isError && !jobs) {
    content = (
      <EmptyState icon="alert" title="Couldn't load jobs"
        body="The job list didn't arrive. Your background work keeps running; try loading it again."
        primaryAction={<Button variant="ghost" icon="refresh" onClick={() => refetch()}>Try again</Button>} />
    );
  } else if (shown.length === 0) {
    const hasHistory = (jobs || []).length > 0;
    content = (
      <EmptyState icon="layers"
        title={tab === "active" ? "No active jobs" : "No jobs yet"}
        body="Background work you start — scrape, import, codex, translation, narration — shows up here."
        primaryAction={tab === "active" && hasHistory
          ? <Button variant="ghost" icon="history" onClick={() => setTab("all")}>View history</Button>
          : <Button variant="ghost" icon="upload" onClick={() => navigate("/import")}>Import a book</Button>}
        secondaryAction={hasHistory ? null
          : <Button variant="ghost" icon="library" onClick={() => navigate("/library")}>Open library</Button>} />
    );
  } else {
    content = (
      <LayoutGroup>
        <div className="jobs-groups">
          <AnimatePresence>
            {groups.map(([novelId, rows], g) => (
              <motion.section key={novelId} layout={animateLayout ? "position" : false}
                              className="jobs-group"
                              initial={{ opacity: 0, y: 18 }}
                              animate={{ opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1], delay: Math.min(g, 6) * 0.055 } }}
                              exit={{ opacity: 0, scale: 0.98, transition: { duration: 0.22 } }}
                              transition={springs.layout}>
                <GroupHead novelId={novelId} novel={novelById.get(novelId)} rows={rows} />
                <div className="jobs-rows">
                  <AnimatePresence initial={false}>
                    {rows.map(job => {
                      const key = `${job.source}:${job.id}`;
                      const failed = job.status === "failed" && !!job.error;
                      const isOpen = failed && expanded.has(key);
                      const duration = tab === "all" && !isActiveJob(job) ? fmtDuration(job.created_at, job.updated_at) : null;
                      const panelId = `job-error-${job.source}-${job.id}`;
                      return (
                        <motion.div key={key} layout={animateLayout ? "position" : false} {...rowMotion}
                                    className={"jobs-row" + (failed ? " is-expandable" : "") + (isOpen ? " is-open" : "")}>
                          <div onClick={failed ? (e) => { if (!e.target.closest("button, a")) toggle(key); } : undefined}>
                            <JobRow job={job} detail busy={busyId === key} onCancel={cancel}
                                    onOpenNovel={null} controls={failed ? panelId : undefined}
                                    expanded={isOpen} onToggle={failed ? () => toggle(key) : undefined}
                                    duration={duration} />
                          </div>
                          <AnimatePresence initial={false}>
                            {isOpen && <ErrorPanel key="error" job={job} id={panelId} />}
                          </AnimatePresence>
                        </motion.div>
                      );
                    })}
                  </AnimatePresence>
                </div>
              </motion.section>
            ))}
          </AnimatePresence>
        </div>
      </LayoutGroup>
    );
  }

  return (
    <div className="page page-enter jobs-page">
      <PageHeader eyebrow="Background work" title="Jobs"
        subtitle="Everything running in the background — scrapes, imports, codex, translation, narration."
        actions={summary.length > 0 ? (
          <div className="jobs-summary" aria-label="Active job summary">
            {summary.map(s => (
              <span key={s.phase} className={`jobs-stat is-${s.phase}`}>
                <span className="jobs-stat-orb" aria-hidden="true" />
                <b key={counts[s.phase]} className="jobs-stat-num">{counts[s.phase]}</b>
                <span>{s.label}</span>
              </span>
            ))}
          </div>
        ) : null} />

      <div className="jobs-bar rise" style={{ "--i": 4 }}>
        <Tabs value={tab} onChange={setTab} label="Job lists" idBase="jobs" tabs={[
          // No count until the list has arrived: "0" would claim nothing is running.
          { id: "active", label: "Active", count: jobs ? activeCount : undefined },
          { id: "all", label: "History", count: jobs ? jobs.length : undefined },
        ]} />
        {tab === "active" && activeCount > 0 && (
          <span className="jobs-live"><i aria-hidden="true" />Updating live</span>
        )}
      </div>

      <div className="jobs-panel" role="tabpanel" id="jobs-panel" aria-labelledby={`jobs-tab-${tab}`}>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={tab}
                      initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { duration: 0.2 } }}
                      exit={{ opacity: 0, y: -6, transition: { duration: 0.12 } }}>
            {content}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
