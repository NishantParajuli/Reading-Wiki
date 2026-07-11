import React from "react";
import { useNavigate, useParams } from "react-router-dom";

import { useAuth } from "../App.jsx";
import { EmptyState, PageHeader, Tabs } from "../components/ui.jsx";
import { useTitle } from "../lib/hooks.js";
import {
  ADMIN_TABS, AgyHealthTab, GlobalJobsTab, ModerationTab, UsageTab, UsersTab,
} from "../modules/admin/AdminPanels.jsx";

export function Admin() {
  const { user } = useAuth();
  const { tab: tabParam } = useParams();
  const navigate = useNavigate();
  const tab = ADMIN_TABS.some((item) => item.id === tabParam) ? tabParam : "users";
  useTitle("Admin");

  if (!user || user.role !== "admin") {
    return (
      <div className="page page-enter">
        <EmptyState icon="shield" title="Admins only" body="You don't have access to this page." />
      </div>
    );
  }

  const openNovel = (id) => navigate(`/n/${id}`);
  return (
    <div className="page page-enter">
      <PageHeader title="Admin" subtitle="Users, platform usage, moderation and the shared Global library." />
      <Tabs tabs={ADMIN_TABS} value={tab}
        onChange={(id) => navigate(id === "users" ? "/admin" : `/admin/${id}`)} />
      <div style={{ marginTop: 18 }}>
        {tab === "users" && <UsersTab me={user} />}
        {tab === "usage" && <UsageTab />}
        {tab === "moderation" && <ModerationTab openNovel={openNovel} />}
        {tab === "jobs" && <GlobalJobsTab openNovel={openNovel} />}
        {tab === "agy" && <AgyHealthTab />}
      </div>
    </div>
  );
}
