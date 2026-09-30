/* ============================================================
   Admin — the operations console. Admin-only; tabs route as /admin/:tab
   (a pill row that scrolls on phones), each tab a composed panel.
   ============================================================ */
import React, { useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useAuth } from "../../App.jsx";
import { Button, EmptyState, Tabs } from "../../components/ui.jsx";
import { TextReveal } from "../../motion/TextReveal.jsx";
import { prefersReducedMotion } from "../../motion/navigation.js";
import { useTitle } from "../../lib/hooks.js";
import {
  ADMIN_TABS, AgyHealthTab, GlobalJobsTab, ModerationTab, OpenAiCodexHealthTab,
  UsageTab, UsersTab,
} from "../../modules/admin/AdminPanels.jsx";

const LEADS = {
  users: "Accounts, roles, monthly limits and AI access.",
  usage: "What the platform spent this month, and the months before.",
  moderation: "Who can see each novel — private, public, or the shared Global library.",
  jobs: "Pipelines for the shared Global library.",
  agy: "The Antigravity subscription worker.",
  "openai-codex": "The OpenAI Codex subscription worker.",
};

export function Admin() {
  const { user } = useAuth();
  const { tab: tabParam } = useParams();
  const navigate = useNavigate();
  const tabsRef = useRef(null);
  const tab = ADMIN_TABS.some((item) => item.id === tabParam) ? tabParam : "users";
  const current = ADMIN_TABS.find((item) => item.id === tab);
  useTitle(tab === "users" ? "Admin" : current.label, tab === "users" ? null : "Admin");

  // Phones: keep the active tab centred in the scrolling pill row.
  useEffect(() => {
    const row = tabsRef.current && tabsRef.current.querySelector(".tabs");
    if (!row || row.scrollWidth <= row.clientWidth + 1) return;
    const item = row.querySelector('[aria-selected="true"]');
    if (!item) return;
    row.scrollTo({ left: Math.max(0, item.offsetLeft - (row.clientWidth - item.offsetWidth) / 2), behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [tab]);

  if (!user || user.role !== "admin") {
    return (
      <div className="page page-enter">
        <EmptyState icon="shield" title="Admins only" body="You don't have access to this page."
          primaryAction={<Button variant="ghost" icon="home" onClick={() => navigate("/")}>Back to home</Button>} />
      </div>
    );
  }

  const openNovel = (id) => navigate(`/n/${id}`);
  return (
    <div className="page adm-page page-enter">
      <header className="adm-head">
        <p className="section-eyebrow rise"><span className="adm-live" aria-hidden="true" />Operations console</p>
        <TextReveal as="h1" className="page-title adm-title" text="Admin" />
        <p className="page-sub rise" style={{ "--i": 3 }}>Users, platform usage, moderation and the shared Global library.</p>
      </header>

      <div className="adm-tabs-wrap rise" style={{ "--i": 4 }} ref={tabsRef}>
        <Tabs className="adm-tabs" tabs={ADMIN_TABS} value={tab} label="Admin sections" idBase="adm"
          onChange={(id) => navigate(id === "users" ? "/admin" : `/admin/${id}`)} />
        <p className="adm-tab-lead" aria-live="polite">{LEADS[tab]}</p>
      </div>

      <div className="adm-panel" role="tabpanel" id="adm-panel" aria-labelledby={`adm-tab-${tab}`} key={tab}>
        {tab === "users" && <UsersTab me={user} />}
        {tab === "usage" && <UsageTab />}
        {tab === "moderation" && <ModerationTab openNovel={openNovel} />}
        {tab === "jobs" && <GlobalJobsTab openNovel={openNovel} />}
        {tab === "agy" && <AgyHealthTab />}
        {tab === "openai-codex" && <OpenAiCodexHealthTab />}
      </div>
    </div>
  );
}
