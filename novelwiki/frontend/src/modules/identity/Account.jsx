/* ============================================================
   Account — a settings experience: an identity header, a grouped nav
   whose lozenge glides between sections (a pill row on phones), and one
   composed panel per section. Sections route as /account/:section.
   ============================================================ */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { authApi } from "./api.js";
import { AccountNav, SECTIONS } from "./AccountNav.jsx";
import { LinkedSection, ProfileSection, SecuritySection, SourcesSection } from "./AccountSections.jsx";
import { AppearanceSection } from "./AccountAppearance.jsx";
import { AudioSection, ReadingSection } from "./AccountReading.jsx";
import { UsageSection } from "./AccountUsage.jsx";
import { useAuth } from "../../App.jsx";
import { Button, UserAvatar } from "../../components/ui.jsx";
import { TextReveal } from "../../motion/TextReveal.jsx";
import { useTitle } from "../../lib/hooks.js";

export function Account() {
  const { section: sectionParam } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const section = SECTIONS.some((item) => item.id === sectionParam) ? sectionParam : "profile";
  const [links, setLinks] = useState(null);
  const current = SECTIONS.find((item) => item.id === section);
  useTitle(section === "profile" ? "Account" : current.label, section === "profile" ? null : "Account");

  const reloadLinks = () => authApi.links().then(setLinks).catch(() => setLinks({ linked: [], has_password: true }));
  useEffect(() => { reloadLinks(); }, []);

  const name = user.display_name || user.username;
  return (
    <div className="page acct-page page-enter">
      <header className="acct-head">
        <div className="acct-head-text">
          <p className="section-eyebrow rise">Settings</p>
          <TextReveal as="h1" className="page-title acct-title" text="Account" />
          <p className="page-sub rise" style={{ "--i": 3 }}>Your identity, appearance, reading defaults and quota.</p>
        </div>
        <div className="acct-id rise" style={{ "--i": 4 }}>
          <UserAvatar url={user.avatar_url} name={name} size={42} className="acct-id-orb" />
          <span className="acct-id-text">
            <b>{name}</b>
            <span>@{user.username}</span>
          </span>
          <Button variant="ghost" size="sm" iconRight="arrowUpRight"
                  onClick={() => navigate(`/u/${encodeURIComponent(user.username)}`)}>
            View public profile
          </Button>
        </div>
      </header>

      <div className="acct-layout">
        <AccountNav active={section} />
        <div className="acct-panel" key={section}>
          {section === "profile" && <ProfileSection />}
          {section === "appearance" && <AppearanceSection />}
          {section === "reading" && <ReadingSection />}
          {section === "audio" && <AudioSection />}
          {section === "security" && <SecuritySection links={links} reloadLinks={reloadLinks} />}
          {section === "linked" && <LinkedSection links={links} />}
          {section === "sources" && <SourcesSection />}
          {section === "usage" && <UsageSection />}
        </div>
      </div>
    </div>
  );
}
