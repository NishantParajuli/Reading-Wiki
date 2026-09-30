/* ============================================================
   Subscription worker health (Antigravity, OpenAI Codex): a status orb
   that pulses while work is running, queue figures, heartbeat facts,
   the consuming smoke test (confirmed first: it spends subscription
   quota) and retry-waiting actions. Refreshes every 10s.
   ============================================================ */
import React, { useCallback, useEffect, useState } from "react";

import { adminApi } from "./api.js";
import { MetricTile, StatusOrb } from "./AdminParts.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, RelativeTime, Skeleton } from "../../components/ui.jsx";
import { ConfirmDialog } from "../../components/overlay.jsx";
import { useToast } from "../../components/toast.jsx";

const WORKER_TONE = { healthy: "ok", idle: "ok", standby: "info", starting: "info", disabled: "neutral", unhealthy: "danger" };

function WorkerHealth({ name, short, slug, icon, fetchHealth, smoke, retry, versionOf, loadingLabel, errorTitle }) {
  const { toast } = useToast();
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirmSmoke, setConfirmSmoke] = useState(false);
  const load = useCallback(() => fetchHealth().then(setHealth).catch(() => setHealth(false)), [fetchHealth]);
  useEffect(() => { load(); const timer = setInterval(load, 10000); return () => clearInterval(timer); }, [load]);

  if (health == null) {
    return (
      <div className="adm-stack" aria-busy="true">
        <span className="sr-only" role="status">{loadingLabel}</span>
        <Skeleton height={220} style={{ borderRadius: 26 }} />
        <Skeleton height={120} style={{ borderRadius: 20 }} />
      </div>
    );
  }
  if (health === false) {
    return <EmptyState icon={icon} title={errorTitle} body="The health endpoint didn't answer. It is checked again every 10 seconds."
             primaryAction={<Button variant="ghost" icon="refresh" onClick={() => { setHealth(null); load(); }}>Try again</Button>} />;
  }

  const q = health.queue || {};
  const running = q.running || 0;
  const waiting = q.waiting_provider || 0;
  const w = health.worker;
  const tone = !health.available ? "danger" : waiting > 0 ? "warn" : running > 0 ? "accent" : "ok";
  const state = !health.available ? "Offline" : running > 0 ? "Working" : "Ready";
  const act = async (fn, done) => {
    setBusy(true);
    try { const r = await fn(); toast(done(r), { tone: "ok" }); await load(); }
    catch (e) { toast(e.message || `${short} action failed.`, { tone: "danger" }); }
    finally { setBusy(false); }
  };

  return (
    <div className="adm-stack">
      <section className={`card adm-worker tone-${tone} rise`} aria-labelledby={`adm-w-${slug}`}>
        <div className="adm-worker-glow" aria-hidden="true" />
        <StatusOrb tone={tone} busy={health.available && running > 0}
                   label={`${name} worker ${state.toLowerCase()}${running ? `, ${running} running` : ""}`} />
        <div className="adm-worker-body">
          <p className="section-eyebrow">
            <span className="adm-live" aria-hidden="true" />Live · refreshes every 10 s
          </p>
          <h2 id={`adm-w-${slug}`} className="adm-worker-title">
            {name} <span className={`adm-worker-state tone-${tone}`}>{state}</span>
          </h2>
          <dl className="adm-facts">
            <div><dt>Global switch</dt><dd><Chip tone={health.enabled ? "ok" : "neutral"}>{health.enabled ? "enabled" : "disabled"}</Chip></dd></div>
            <div><dt>Worker</dt><dd>{w
              ? <><Chip tone={WORKER_TONE[w.status] || "neutral"}>{w.status}</Chip> <span className="mono">{versionOf(w)}</span></>
              : <span className="muted">no heartbeat</span>}</dd></div>
            {w && w.heartbeat_at && <div><dt>Heartbeat</dt><dd><RelativeTime iso={w.heartbeat_at} /></dd></div>}
            <div><dt>Last success</dt><dd>{health.last_success_at ? <RelativeTime iso={health.last_success_at} /> : "none"}</dd></div>
            <div><dt>Oldest queued</dt><dd>{q.oldest_at ? <RelativeTime iso={q.oldest_at} /> : "none"}</dd></div>
          </dl>
          <div className="adm-worker-actions">
            <Button variant="ghost" icon="zap" disabled={busy || !health.enabled}
                    onClick={() => setConfirmSmoke(true)}>Run consuming smoke test</Button>
            <Button variant="ghost" icon="rotateCcw" disabled={busy || !(waiting > 0)}
                    onClick={() => act(retry, r => `${(r && r.jobs_requeued) || 0} waiting ${(r && r.jobs_requeued) === 1 ? "job" : "jobs"} requeued.`)}>Retry waiting jobs</Button>
          </div>
        </div>
      </section>
      {confirmSmoke && (
        <ConfirmDialog title="Run the consuming smoke test?" confirmLabel="Run smoke test" danger={false} busy={busy}
          body={`This queues a real job on the ${name} worker. It uses no novel or reader content, but it spends subscription quota like any other run.`}
          onCancel={() => setConfirmSmoke(false)}
          onConfirm={async () => { await act(smoke, r => (r && r.warning) || "Smoke test queued."); setConfirmSmoke(false); }} />
      )}

      <div className="adm-metrics adm-metrics-3">
        <MetricTile i={1} icon="hourglass" value={q.queued || 0} label="Queued" />
        <MetricTile i={2} icon="activity" value={running} label="Running" tone={running > 0 ? "accent" : undefined} />
        <MetricTile i={3} icon="clock" value={waiting} label="Waiting provider" tone={waiting > 0 ? "warn" : undefined} />
      </div>

      {health.recent_failures && health.recent_failures.length > 0 && (
        <section className="card adm-block rise" style={{ "--i": 4 }} aria-labelledby={`adm-f-${slug}`}>
          <header className="adm-block-head"><div className="grow">
            <p className="section-eyebrow">Recent</p>
            <h2 id={`adm-f-${slug}`} className="adm-block-title">Failures</h2>
          </div></header>
          <ul className="adm-failures">
            {health.recent_failures.map(x => (
              <li key={x.code}><Icon name="circleAlert" size={15} /><code>{x.code}</code><b>{x.count}</b></li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function AgyHealthTab() {
  const fetchHealth = useCallback(() => adminApi.agyHealth(), []);
  return (
    <WorkerHealth name="Antigravity" short="AGY" slug="agy" icon="sparkles" fetchHealth={fetchHealth}
                  smoke={() => adminApi.agySmoke()} retry={() => adminApi.retryWaitingAgy()}
                  versionOf={(w) => `${w.version || "unknown version"} · plugin ${w.plugin_version || "—"}`}
                  loadingLabel="Checking Antigravity worker…" errorTitle="Couldn't load AGY health" />
  );
}

export function OpenAiCodexHealthTab() {
  const fetchHealth = useCallback(() => adminApi.openaiCodexHealth(), []);
  return (
    <WorkerHealth name="OpenAI Codex" short="OpenAI Codex" slug="openai-codex" icon="cpu" fetchHealth={fetchHealth}
                  smoke={() => adminApi.openaiCodexSmoke()} retry={() => adminApi.retryWaitingOpenaiCodex()}
                  versionOf={(w) => `${w.version || "unknown version"} · contract ${w.contract_version || "—"}`}
                  loadingLabel="Checking OpenAI Codex worker…" errorTitle="Couldn't load OpenAI Codex health" />
  );
}
