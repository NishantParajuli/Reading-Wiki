/* ============================================================
   NotFound — a link that leads nowhere: a message in a bottle, bobbing on
   the tide, and three ways back to dry land.
   ============================================================ */
import React from "react";
import { Link, useLocation } from "react-router-dom";
import { Icon } from "../../components/Icon.jsx";
import { TextReveal } from "../../motion/TextReveal.jsx";
import { useTitle } from "../../lib/hooks.js";

/* Waves are drawn twice as wide as the scene (period 180), so sliding one
   half-width loops seamlessly. */
const wave = (y) => `M0 ${y} Q 45 ${y - 12} 90 ${y} T 180 ${y} T 270 ${y} T 360 ${y} T 450 ${y} T 540 ${y} T 630 ${y} T 720 ${y} V 230 H 0 Z`;

function Bottle() {
  return (
    <svg className="lost-scene" viewBox="0 0 360 230" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="lost-water" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--accent)" stopOpacity="0.34" />
          <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="lost-glass" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--accent)" stopOpacity="0.42" />
          <stop offset="1" stopColor="var(--accent)" stopOpacity="0.16" />
        </linearGradient>
      </defs>
      <g className="lost-sparkles">
        <circle cx="70" cy="60" r="1.6" /><circle cx="292" cy="44" r="1.2" />
        <circle cx="250" cy="82" r="1" /><circle cx="112" cy="30" r="1.1" />
      </g>
      <path className="lost-wave lost-wave-back" d={wave(142)} />
      <g className="lost-bottle">
        <path className="lost-glass" d="M146 98 H 214 C 226 98 232 108 240 110 H 254 V 126 H 240 C 232 128 226 138 214 138 H 146 C 135 138 128 129 128 118 C 128 107 135 98 146 98 Z" />
        <rect className="lost-cork" x="253" y="111" width="11" height="14" rx="2.5" />
        <rect className="lost-scroll" x="146" y="108" width="58" height="20" rx="5" />
        <path className="lost-scroll-lines" d="M156 115 H 192 M156 121 H 184" />
        <path className="lost-ribbon" d="M176 108 V 128" />
        <path className="lost-shine" d="M142 104 Q 176 99 212 104" />
      </g>
      <path className="lost-wave lost-wave-front" d={wave(151)} />
    </svg>
  );
}

export function NotFound() {
  useTitle("Page not found");
  const { pathname } = useLocation();
  const openSearch = () => window.dispatchEvent(new Event("tg-open-palette"));
  return (
    <div className="page lost page-enter">
      <Bottle />
      <p className="section-eyebrow lost-eyebrow">Lost at sea</p>
      <h1 className="lost-title"><TextReveal text="This page drifted away." /></h1>
      <p className="lost-lede">
        Nothing lives at <code className="lost-path">{pathname}</code>. The link may be old, or the page
        may have moved. Your books and your place in them are safe.
      </p>
      <div className="lost-actions">
        <Link className="btn btn-primary lg" to="/">Back to your reading room <Icon name="arrowRight" size={18} /></Link>
        <Link className="btn btn-ghost lg" to="/library"><Icon name="library" size={18} /> Your library</Link>
        <button type="button" className="btn btn-ghost lg" onClick={openSearch}><Icon name="search" size={18} /> Search</button>
      </div>
    </div>
  );
}
