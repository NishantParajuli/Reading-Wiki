/* ============================================================
   Settings navigation. Desktop: a sticky, grouped list whose active
   lozenge glides between sections (motion layoutId). Phones: the same
   links become one scrollable pill row that keeps the active pill in view.
   ============================================================ */
import React, { useEffect, useRef } from "react";
import { Link } from "react-router-dom";

import { Icon } from "../../components/Icon.jsx";
import { motion, springs } from "../../motion/index.js";
import { prefersReducedMotion } from "../../motion/navigation.js";

export const SECTIONS = [
  { id: "profile", label: "Profile", icon: "user", group: "Identity" },
  { id: "appearance", label: "Appearance", icon: "palette", group: "Experience" },
  { id: "reading", label: "Reading", icon: "bookOpen", group: "Experience" },
  { id: "audio", label: "Audio", icon: "headphones", group: "Experience" },
  { id: "security", label: "Security", icon: "shield", group: "Sign-in" },
  { id: "linked", label: "Linked accounts", icon: "link", group: "Sign-in" },
  { id: "sources", label: "Source accounts", icon: "globe", group: "Imports & usage" },
  { id: "usage", label: "Usage", icon: "activity", group: "Imports & usage" },
];

const GROUPS = SECTIONS.reduce((acc, item) => {
  const last = acc[acc.length - 1];
  if (last && last.label === item.group) last.items.push(item);
  else acc.push({ label: item.group, items: [item] });
  return acc;
}, []);

export const sectionPath = (id) => (id === "profile" ? "/account" : `/account/${id}`);

export function AccountNav({ active }) {
  const scrollRef = useRef(null);

  // Phones: keep the active pill centred in the scroll row (never scrolls the page).
  useEffect(() => {
    const row = scrollRef.current;
    if (!row || row.scrollWidth <= row.clientWidth + 1) return;
    const item = row.querySelector('[aria-current="page"]');
    if (!item) return;
    const left = item.offsetLeft - (row.clientWidth - item.offsetWidth) / 2;
    row.scrollTo({ left: Math.max(0, left), behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [active]);

  return (
    <nav className="acct-nav" aria-label="Settings sections">
      <div className="acct-nav-scroll" ref={scrollRef}>
        {GROUPS.map((group, g) => (
          <div key={group.label} className="acct-nav-group" role="group" aria-labelledby={`acct-nav-g${g}`}>
            <p className="acct-nav-label" id={`acct-nav-g${g}`}>{group.label}</p>
            {group.items.map((item) => {
              const on = item.id === active;
              const index = SECTIONS.indexOf(item);
              return (
                <Link key={item.id} to={sectionPath(item.id)}
                      className={"acct-nav-item rise" + (on ? " active" : "")}
                      style={{ "--i": index + 2 }}
                      aria-current={on ? "page" : undefined}>
                  {on && (
                    <motion.span layoutId="acct-nav-pill" className="acct-nav-pill"
                                 style={{ borderRadius: 999 }} transition={springs.layout} aria-hidden="true" />
                  )}
                  <Icon name={item.icon} size={17} />
                  <span className="acct-nav-text">{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </div>
    </nav>
  );
}
