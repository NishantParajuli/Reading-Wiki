/* ============================================================
   Jobs (§6.10) — one job center over the three durable job systems.
   Active / History tabs, rows grouped by novel, failed rows expand to a
   copyable error, live updates from the shared activity poller.
   ============================================================ */
import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { API } from "../lib/api.js";
import { Icon } from "../components/Icon.jsx";
import { Button, Cover, EmptyState, Loading, PageHeader, Tabs } from "../components/ui.jsx";
import { JobRow } from "../components/JobRow.jsx";
import { useToast } from "../components/toast.jsx";
import { useActivityQuery, isActiveJob, useNovelsQuery } from "../lib/queries.js";
import { useTitle } from "../lib/hooks.js";
import { fmtDuration } from "../lib/utils.js";

export function Jobs() {
  const { data: jobs, isLoading, refetch } = useActivityQuery();
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

  async function cancel(job) {
    const rowKey = `${job.source}:${job.id}`;
    setBusyId(rowKey);
    try { await API.cancelActivity(job); await refetch(); }
    catch (e) { toast(e.message || "Cancel failed.", { tone: "danger" }); }
    finally { setBusyId(null); }
  }

  const activeCount = (jobs || []).filter(isActiveJob).length;

  return (
    <div className="page page-enter">
      <PageHeader title="Jobs" subtitle="Everything running in the background — scrapes, imports, codex, translation, narration." />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "active", label: "Active", count: activeCount },
        { id: "all", label: "History" },
      ]} />

      <div style={{ marginTop: 20 }}>
        {isLoading ? (
          <Loading label="Loading jobs…" />
        ) : shown.length === 0 ? (
          <EmptyState icon="layers"
            title={tab === "active" ? "No active jobs" : "No jobs yet"}
            body="Background work you start — scrape, import, codex, translation, narration — shows up here." />
        ) : (
          groups.map(([novelId, rows]) => {
            const novel = novelById.get(novelId);
            return (
              <div key={novelId} className="jobs-novel-group">
                <div className="jobs-novel-head">
                  {novel
                    ? <>
                        <Cover src={novel.cover_url} title={novel.title} />
                        <button className="admin-novel-title" onClick={() => navigate(`/n/${novelId}`)}>{novel.title}</button>
                      </>
                    : <b className="muted">{novelId ? `Novel #${novelId}` : "General"}</b>}
                </div>
                <div className="card" style={{ padding: 6 }}>
                  {rows.map(job => {
                    const key = `${job.source}:${job.id}`;
                    const failed = job.status === "failed" && job.error;
                    const isOpen = expanded.has(key);
                    const duration = fmtDuration(job.created_at, job.updated_at);
                    return (
                      <React.Fragment key={key}>
                        <div style={failed ? { cursor: "pointer" } : undefined}
                             onClick={failed ? () => setExpanded(prev => { const s = new Set(prev); s.has(key) ? s.delete(key) : s.add(key); return s; }) : undefined}>
                          <JobRow job={job} detail
                                  busy={busyId === key}
                                  onCancel={cancel}
                                  onOpenNovel={novelId ? null : (id) => navigate(`/n/${id}`)} />
                        </div>
                        {tab === "all" && duration && !isActiveJob(job) && !isOpen && (
                          <div className="muted" style={{ fontSize: "var(--text-xs)", padding: "0 12px 8px", marginTop: -6 }}>
                            took {duration}
                          </div>
                        )}
                        {failed && isOpen && (
                          <div className="job-error-detail">
                            {job.error}
                            <Button size="sm" variant="ghost" style={{ position: "absolute", top: 8, right: 8 }}
                                    onClick={(e) => { e.stopPropagation(); navigator.clipboard.writeText(job.error).then(() => toast("Error copied.", { tone: "ok" })); }}>
                              Copy
                            </Button>
                          </div>
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>
            );
          })
        )}
      </div>

      {tab === "active" && activeCount > 0 && (
        <p className="muted" style={{ fontSize: "var(--text-sm)", display: "flex", alignItems: "center", gap: 8 }}>
          <Icon name="refresh" size={13} className="spin" /> Updating live.
        </p>
      )}
    </div>
  );
}
