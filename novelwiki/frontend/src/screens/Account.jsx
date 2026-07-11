import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { authApi } from "../modules/identity/api.js";
import {
  AppearanceSection, AudioSection, LinkedSection, ProfileSection, ReadingSection,
  SECTIONS, SecuritySection, UsageSection,
} from "../modules/identity/AccountSections.jsx";
import { useAuth } from "../App.jsx";
import { Icon } from "../components/Icon.jsx";
import { Button, PageHeader } from "../components/ui.jsx";
import { useTitle } from "../lib/hooks.js";

export function Account() {
  const { section: sectionParam } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const section = SECTIONS.some((item) => item.id === sectionParam) ? sectionParam : "profile";
  const [links, setLinks] = useState(null);
  useTitle("Account");

  const reloadLinks = () => authApi.links().then(setLinks).catch(() => setLinks({ linked: [], has_password: true }));
  useEffect(() => { reloadLinks(); }, []);

  return (
    <div className="page page-enter">
      <PageHeader title="Account" subtitle="Your identity, appearance, reading defaults and quota."
        actions={<Button variant="ghost" icon="user" onClick={() => navigate(`/u/${encodeURIComponent(user.username)}`)}>View public profile</Button>} />
      <div className="acct-layout">
        <nav className="acct-nav" aria-label="Settings sections">
          {SECTIONS.map((item) => (
            <button key={item.id} className={"acct-nav-item" + (section === item.id ? " active" : "")}
              onClick={() => navigate(item.id === "profile" ? "/account" : `/account/${item.id}`)}>
              <Icon name={item.icon} size={16} /> {item.label}
            </button>
          ))}
        </nav>
        <div>
          {section === "profile" && <ProfileSection />}
          {section === "appearance" && <AppearanceSection />}
          {section === "reading" && <ReadingSection />}
          {section === "audio" && <AudioSection />}
          {section === "security" && <SecuritySection links={links} reloadLinks={reloadLinks} />}
          {section === "linked" && <LinkedSection links={links} />}
          {section === "usage" && <UsageSection />}
        </div>
      </div>
    </div>
  );
}
