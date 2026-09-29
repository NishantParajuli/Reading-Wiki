/* ============================================================
   Admin console panels: Usage & cost (count-up tiles, top spenders, a
   six-month chart with its table twin), Moderation (visibility per novel)
   and Global jobs (pipeline triggers for the shared library).
   Users lives in AdminUsers.jsx; worker health in AdminWorkers.jsx.
   ============================================================ */
import React, { useCallback, useEffect, useState } from "react";

import { acquisitionApi } from "../acquisition/api.js";
import { adminApi } from "./api.js";
import { catalogApi } from "../catalog/api.js";
import { codexApi } from "../codex/api.js";
import { translationApi } from "../translation/api.js";
import { BlockHead, MetricTile, VISIBILITY, VisibilitySelect, fmtDay } from "./AdminParts.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, Cover, EmptyState, SegmentedControl, Skeleton, Spinner, UserAvatar } from "../../components/ui.jsx";
import { useToast } from "../../components/toast.jsx";

export { UsersTab } from "./AdminUsers.jsx";
export { AgyHealthTab, OpenAiCodexHealthTab } from "./AdminWorkers.jsx";

export const ADMIN_TABS = [
  { id: "users", label: "Users", icon: "users" },
  { id: "usage", label: "Usage & cost", icon: "database" },
  { id: "moderation", label: "Moderation", icon: "shield" },
  { id: "jobs", label: "Global jobs", icon: "spider" },
  { id: "agy", label: "Antigravity", icon: "sparkles" },
  { id: "openai-codex", label: "OpenAI Codex", icon: "cpu" },
];

function PanelLoading({ label, rows = 3, height = 72 }) {
  return (
    <div className="adm-stack" aria-busy="true">
      <span className="sr-only" role="status">{label}</span>
      {Array.from({ length: rows }, (_, k) => <Skeleton key={k} height={height} style={{ borderRadius: 20 }} />)}
    </div>
  );
}

/* ── Usage & cost ── */
const monthLabel = (period, opts = { month: "short" }) => {
  const d = new Date(period);
  return Number.isNaN(d.getTime()) ? String(period).slice(0, 7) : d.toLocaleDateString(undefined, { ...opts, timeZone: "UTC" });
};

function niceMax(max) {
  if (max <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(max));
  const n = max / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * pow;
}

/* Chapters translated per month: one series, the latest month in accent
   (emphasis), the rest recessive. Values also live in the table below. */
function MonthChart({ months }) {
  const max = niceMax(Math.max(...months.map(m => m.translated_chapters || 0)));
  const peak = Math.max(...months.map(m => m.translated_chapters || 0));
  return (
    <div className="adm-chart" role="group" aria-label="Chapters translated per month">
      <div className="adm-chart-grid" aria-hidden="true">
        <span style={{ "--y": 1 }}><i>{max.toLocaleString()}</i></span>
        <span style={{ "--y": 0.5 }}><i>{(max / 2).toLocaleString()}</i></span>
        <span style={{ "--y": 0 }}><i>0</i></span>
      </div>
      <div className="adm-chart-bars">
        {months.map((m, i) => {
          const v = m.translated_chapters || 0;
          const latest = i === months.length - 1;
          const label = monthLabel(m.period, { month: "long", year: "numeric" });
          return (
            <div key={m.period} className={"adm-bar" + (latest ? " is-latest" : "")} tabIndex={0}
                 aria-label={`${label}: ${v} chapters translated, ${m.ocr_pages || 0} OCR pages, ${m.codex_builds || 0} codex builds`}>
              <div className="adm-bar-plot">
                <span className="adm-bar-fill" style={{ "--h": v / max, "--i": i }}>
                  {(latest || (v === peak && v > 0)) && <b className="adm-bar-value">{v.toLocaleString()}</b>}
                </span>
              </div>
              <span className="adm-bar-x">{monthLabel(m.period)}</span>
              <span className="adm-bar-tip" role="tooltip">
                <b>{v.toLocaleString()}</b> chapters
                <small>{label} · {(m.ocr_pages || 0).toLocaleString()} OCR · {(m.codex_builds || 0).toLocaleString()} codex</small>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function UsageTab() {
  const [data, setData] = useState(null);
  const load = useCallback(() => { setData(null); adminApi.usage().then(setData).catch(() => setData(false)); }, []);
  useEffect(() => { load(); }, [load]);
  if (data == null) return <PanelLoading label="Loading usage…" rows={2} height={140} />;
  if (data === false) {
    return <EmptyState icon="database" title="Couldn't load usage" body="The usage report didn't arrive."
             primaryAction={<Button variant="ghost" icon="refresh" onClick={load}>Try again</Button>} />;
  }
  const t = data.totals || {};
  const spenders = data.top_spenders || [];
  const months = [...(data.months || [])].sort((a, b) => String(a.period).localeCompare(String(b.period)));
  return (
    <div className="adm-stack">
      <div className="adm-metrics">
        <MetricTile i={0} icon="globe" value={t.translated_chapters ?? 0} label="Chapters translated" note="this month" />
        <MetricTile i={1} icon="image" value={t.ocr_pages ?? 0} label="OCR pages" note="this month" />
        <MetricTile i={2} icon="brain" value={t.codex_builds ?? 0} label="Codex builds" note="this month" />
        <MetricTile i={3} icon="activity" value={t.active_users ?? 0} label="Active this month" />
        <MetricTile i={4} icon="users" value={data.user_count ?? 0} label="Total users" />
        <MetricTile i={5} icon="library" value={data.novel_count ?? 0} label="Novels" />
      </div>

      <div className="adm-usage-grid">
        <section className="card adm-block rise" style={{ "--i": 3 }} aria-labelledby="adm-spenders-h">
          <BlockHead id="adm-spenders-h" eyebrow="This month" title="Top spenders" />
          {spenders.length === 0 ? <p className="adm-quiet">No spend recorded this month.</p> : (
            <ol className="adm-spenders">
              {spenders.map((u, i) => (
                <li key={u.id} className="adm-spender">
                  <span className="adm-rank" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                  <UserAvatar name={u.display_name || u.username} size={34} />
                  <span className="adm-spender-id">
                    <b>{u.display_name || u.username}</b>
                    <span>@{u.username}</span>
                  </span>
                  <span className="adm-spender-figs">
                    <span><b>{(u.translated_chapters || 0).toLocaleString()}</b> ch</span>
                    <span><b>{(u.ocr_pages || 0).toLocaleString()}</b> ocr</span>
                    <span><b>{(u.codex_builds || 0).toLocaleString()}</b> cdx</span>
                  </span>
                </li>
              ))}
            </ol>
          )}
        </section>

        <section className="card adm-block rise" style={{ "--i": 4 }} aria-labelledby="adm-months-h">
          <BlockHead id="adm-months-h" eyebrow="Last 6 months" title="Chapters translated" />
          {months.length === 0 ? <p className="adm-quiet">No history yet.</p> : (
            <>
              <MonthChart months={months} />
              <table className="adm-table">
                <caption className="sr-only">Monthly platform usage</caption>
                <thead><tr><th scope="col">Month</th><th scope="col">Chapters</th><th scope="col">OCR</th><th scope="col">Codex</th></tr></thead>
                <tbody>
                  {[...months].reverse().map(m => (
                    <tr key={m.period}>
                      <th scope="row">{monthLabel(m.period, { month: "short", year: "numeric" })}</th>
                      <td>{(m.translated_chapters || 0).toLocaleString()}</td>
                      <td>{(m.ocr_pages || 0).toLocaleString()}</td>
                      <td>{(m.codex_builds || 0).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

/* ── Moderation ── */
const FILTERS = [{ value: "", label: "All" }, ...Object.keys(VISIBILITY).map(v => ({ value: v, label: VISIBILITY[v].label, icon: VISIBILITY[v].icon }))];

export function ModerationTab({ openNovel }) {
  const { toast } = useToast();
  const [novels, setNovels] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [vis, setVis] = useState("");
  const [q, setQ] = useState("");
  const load = useCallback((opts, quiet) => {
    if (quiet) setRefreshing(true); else setNovels(null);
    return adminApi.novels(opts).then(setNovels).catch(() => setNovels(false)).finally(() => setRefreshing(false));
  }, []);
  useEffect(() => { load({}); }, [load]);

  const changeVis = async (n, v) => {
    try { await catalogApi.setVisibility(n.id, v); await load({ visibility: vis || undefined, q: q || undefined }, true); }
    catch (e) { toast(e.message || "Couldn't change visibility.", { tone: "danger" }); }
  };

  return (
    <div className="adm-stack">
      <div className="adm-toolbar">
        <form className="adm-search" role="search"
              onSubmit={e => { e.preventDefault(); load({ visibility: vis || undefined, q: q || undefined }); }}>
          <div className="search-box">
            <Icon name="search" size={16} />
            <input value={q} placeholder="Search title…" onChange={e => setQ(e.target.value)} aria-label="Search novels" />
          </div>
          <Button variant="ghost" type="submit" icon="search">Search</Button>
        </form>
        <SegmentedControl fit className="adm-filter" ariaLabel="Filter by visibility" value={vis} options={FILTERS}
                          onChange={(v) => { setVis(v); load({ visibility: v || undefined, q: q || undefined }); }} />
      </div>
      <p className="adm-legend">
        {Object.keys(VISIBILITY).map(k => (
          <span key={k} className={`adm-legend-item vis-${k}`}><Icon name={VISIBILITY[k].icon} size={13} /><b>{VISIBILITY[k].label}</b> {VISIBILITY[k].hint.toLowerCase()}</span>
        ))}
      </p>
      {novels == null ? <PanelLoading label="Loading novels…" rows={4} height={76} />
        : novels === false ? (
          <EmptyState icon="alert" title="Couldn't load novels" body="The moderation list didn't arrive."
            primaryAction={<Button variant="ghost" icon="refresh" onClick={() => load({ visibility: vis || undefined, q: q || undefined })}>Try again</Button>} />
        ) : novels.length === 0 ? (
          <EmptyState icon="book" title="No novels" body={q || vis ? "Nothing matches these filters." : "No novels on this instance yet."} />
        ) : (
          <div className={"card adm-novels" + (refreshing ? " is-refreshing" : "")} aria-busy={refreshing || undefined}>
            {novels.map((n, i) => (
              <div key={n.id} className="adm-novel rise" style={{ "--i": Math.min(i, 12) }}>
                <Cover src={n.cover_url} title={n.title} author={n.author} className="adm-novel-cover" />
                <div className="adm-novel-id">
                  <button type="button" className="adm-novel-title" onClick={() => openNovel(n.id)} title="Open novel">{n.title}</button>
                  <span className="adm-novel-sub">
                    {n.author && <span>{n.author}</span>}
                    <span>{(n.chapter_count || 0).toLocaleString()} ch.</span>
                    <span>{n.owner_username ? "@" + n.owner_username : "unowned"}</span>
                  </span>
                </div>
                <VisibilitySelect value={n.visibility} title={n.title} onChange={v => changeVis(n, v)} />
              </div>
            ))}
          </div>
        )}
    </div>
  );
}

/* ── Global jobs ── */
export function GlobalJobsTab({ openNovel }) {
  const [novels, setNovels] = useState(null);
  const [msg, setMsg] = useState({});
  const [busy, setBusy] = useState({});

  const load = useCallback(() => {
    setNovels(null);
    adminApi.globalNovels().then(setNovels).catch(() => setNovels(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const run = async (n, label, fn) => {
    setBusy(b => ({ ...b, [n.id]: true }));
    setMsg(m => ({ ...m, [n.id]: { kind: "pending", text: label + "…" } }));
    try {
      const r = await fn();
      setMsg(m => ({ ...m, [n.id]: { kind: "ok", text: (r && r.message) || (label + " scheduled.") } }));
    } catch (e) {
      setMsg(m => ({ ...m, [n.id]: { kind: "err", text: e.message || "Failed." } }));
    } finally {
      setBusy(b => ({ ...b, [n.id]: false }));
    }
  };

  return (
    <div className="adm-stack">
      <div className="adm-toolbar">
        <p className="adm-intro">Scrape, pre-translate, and build the codex for the shared Global library. Jobs run in the background.</p>
        <Button variant="ghost" icon="refresh" onClick={load}>Refresh</Button>
      </div>
      {novels == null ? <PanelLoading label="Loading Global library…" rows={2} height={150} />
        : novels === false ? (
          <EmptyState icon="alert" title="Couldn't load the Global library" body="The list didn't arrive."
            primaryAction={<Button variant="ghost" icon="refresh" onClick={load}>Try again</Button>} />
        ) : novels.length === 0 ? (
          <EmptyState icon="book" title="No global novels" body="Promote a public novel to Global from the Moderation tab." />
        ) : (
          <div className="adm-jobs">
            {novels.map((n, i) => {
              const m = msg[n.id]; const b = !!busy[n.id];
              return (
                <article key={n.id} className="card adm-job rise" style={{ "--i": Math.min(i, 8) }} data-spotlight=""
                         aria-labelledby={`adm-job-${n.id}`}>
                  <Cover src={n.cover_url} title={n.title} author={n.author} className="adm-job-cover" />
                  <div className="adm-job-body">
                    <button type="button" id={`adm-job-${n.id}`} className="adm-novel-title adm-job-title" onClick={() => openNovel(n.id)} title="Open novel">{n.title}</button>
                    <div className="adm-job-facts">
                      <Chip icon="layers">{(n.chapter_count || 0).toLocaleString()} ch</Chip>
                      <Chip icon="link">{n.source_count || 0} {n.source_count === 1 ? "source" : "sources"}</Chip>
                      <Chip icon="clock">scraped {fmtDay(n.last_scraped_at)}</Chip>
                      {n.has_raw && <Chip tone={n.untranslated > 0 ? "warn" : "ok"} icon="globe">{n.untranslated} untranslated</Chip>}
                      {n.codex_enabled && <Chip tone="accent" icon="brain">codex</Chip>}
                    </div>
                    <div className="adm-job-actions">
                      <Button variant="ghost" size="sm" icon="spider" disabled={b}
                              onClick={() => run(n, "Scrape", () => acquisitionApi.scrape(n.id, {}))}>Scrape</Button>
                      {n.has_raw && (
                        <Button variant="ghost" size="sm" icon="globe" disabled={b || n.untranslated === 0}
                                onClick={() => run(n, "Translate", () => translationApi.translate(n.id, {}))}>Translate raws</Button>
                      )}
                      <Button variant="ghost" size="sm" icon="brain" disabled={b}
                              onClick={() => run(n, "Codex build", () => codexApi.codexBuild(n.id, {}))}>
                        {n.codex_enabled ? "Rebuild codex" : "Build codex"}
                      </Button>
                    </div>
                    <div className={"adm-job-msg" + (m ? ` is-${m.kind}` : "")} role="status">
                      {m && m.kind === "pending" && <Spinner />}
                      {m && m.kind === "ok" && <Icon name="circleCheck" size={15} />}
                      {m && m.kind === "err" && <Icon name="circleAlert" size={15} />}
                      {m && m.text}
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        )}
    </div>
  );
}
