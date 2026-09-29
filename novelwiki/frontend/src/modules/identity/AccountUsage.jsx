/* ============================================================
   Usage — this month's quotas as luminous gauges. Each ring fills from
   empty on arrival; the fill carries severity (accent → warn → danger)
   over a track of the same hue. Loading, error and unlimited states are
   shown for what they are.
   ============================================================ */
import React, { useCallback, useEffect, useRef, useState } from "react";

import { identityApi } from "./api.js";
import { Group, SectionHead } from "./AccountParts.jsx";
import { useAuth } from "../../App.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, ProgressRing, Skeleton } from "../../components/ui.jsx";
import { useInView } from "../../motion/index.js";
import { NumberTicker } from "../../motion/NumberTicker.jsx";

const METERS = [
  { key: "translated_chapters", label: "Chapters translated", help: "On-demand reads and batch pre-translation both count.", icon: "globe" },
  { key: "ocr_pages", label: "OCR pages", help: "Pages read from scanned PDF imports.", icon: "image" },
  { key: "codex_builds", label: "Codex builds", help: "Each build or extension of a novel's codex.", icon: "brain" },
  { key: "tts_chapters", label: "Chapters narrated", help: "Chapters synthesized to audio (cached ones are free).", icon: "headphones", optional: true },
];

function nextReset() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth() + 1, 1).toLocaleDateString(undefined, { month: "long", day: "numeric" });
}

function Gauge({ label, used, limit, help, icon, i }) {
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
  const tone = pct >= 100 ? "danger" : pct >= 80 ? "warn" : "calm";
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -10% 0px" });
  const [shown, setShown] = useState(0);
  // Start empty; once the gauge is on screen the ring's stroke transition carries it to the value.
  useEffect(() => {
    if (!inView) return undefined;
    const id = requestAnimationFrame(() => setShown(pct));
    return () => cancelAnimationFrame(id);
  }, [pct, inView]);
  const left = Math.max(0, limit - used);
  return (
    <div ref={ref} className={`acct-gauge tone-${tone} rise`} style={{ "--i": i + 2 }}>
      <ProgressRing value={shown} size={112} stroke={7} label={`${label}: ${used} of ${limit} used`}>
        <span className="acct-gauge-pct"><NumberTicker value={Math.round(pct)} />%</span>
      </ProgressRing>
      <div className="acct-gauge-text">
        <span className="acct-gauge-label"><Icon name={icon} size={14} /> {label}</span>
        <span className="acct-gauge-figure">
          <NumberTicker value={used} className="acct-gauge-used" />
          <span className="acct-gauge-limit"> / {Number(limit).toLocaleString()}</span>
        </span>
        <span className="acct-gauge-left">
          {tone === "danger" ? "Limit reached" : `${left.toLocaleString()} left`}
        </span>
        <small>{help}</small>
      </div>
    </div>
  );
}

export function UsageSection() {
  const { user } = useAuth();
  const [usage, setUsage] = useState(null); // null loading · false error
  const load = useCallback(() => {
    setUsage(null);
    identityApi.usage().then(setUsage).catch(() => setUsage(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  let body;
  if (usage == null) {
    body = (
      <Group i={1} title="This month's usage" aria-busy="true">
        <span className="sr-only" role="status">Loading usage…</span>
        <div className="acct-gauges">
          {[0, 1, 2].map(k => (
            <div key={k} className="acct-gauge">
              <Skeleton variant="circle" width={112} height={112} />
              <div className="acct-gauge-text"><Skeleton variant="text" width="70%" /><Skeleton variant="text" width="40%" height={26} /></div>
            </div>
          ))}
        </div>
      </Group>
    );
  } else if (usage === false) {
    body = (
      <Group i={1} className="acct-offline">
        <span className="acct-offline-orb is-danger" aria-hidden="true"><Icon name="alert" size={22} /></span>
        <div className="grow">
          <h3 className="acct-group-title">Couldn't load your usage</h3>
          <p className="acct-group-hint">Your quotas are unchanged — the numbers just didn't arrive.</p>
        </div>
        <Button variant="ghost" icon="refresh" onClick={load}>Try again</Button>
      </Group>
    );
  } else if (usage.unlimited) {
    body = (
      <Group i={1} className="acct-unlimited">
        <span className="acct-infinity" aria-hidden="true">∞</span>
        <div className="grow">
          <h3 className="acct-group-title">Unlimited (admin)</h3>
          <p className="acct-group-hint">Admin accounts aren't metered. Platform-wide spend lives in Admin → Usage & cost.</p>
        </div>
      </Group>
    );
  } else {
    const u = usage.usage || {};
    const l = usage.limits || {};
    const meters = METERS.filter(m => !m.optional || l[m.key] != null);
    body = (
      <Group i={1} title="This month's usage"
             aside={<span className="acct-reset"><Icon name="rotateCcw" size={13} /> Resets {nextReset()}</span>}>
        <div className="acct-gauges">
          {meters.map((m, i) => (
            <Gauge key={m.key} i={i} label={m.label} help={m.help} icon={m.icon}
                   used={Number(u[m.key]) || 0} limit={Number(l[m.key]) || 0} />
          ))}
        </div>
        {!user.email_verified && (
          <p className="acct-warn" role="note"><Icon name="alert" size={15} /> Verify your email to use translation, OCR & imports.</p>
        )}
        <p className="acct-hint">Quotas reset at the start of each month.</p>
      </Group>
    );
  }

  return (
    <section className="acct-section" aria-labelledby="acct-h-usage">
      <SectionHead id="acct-h-usage" icon="activity" title="Usage"
                   lead="What your AI-powered reading has used this month, against your limits." />
      {body}
    </section>
  );
}
