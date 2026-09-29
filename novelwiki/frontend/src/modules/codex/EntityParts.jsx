/* Dossier sections for the entity page. Every element is built from data the
   server already bounded to the reader's chapter ceiling. */
import React, { useRef } from "react";
import { Link } from "react-router-dom";

import { Icon } from "../../components/Icon.jsx";
import { EntityAvatar } from "../../components/ui.jsx";
import { fmtChapter } from "../../lib/utils.js";
import { constellation, groupFactsByChapter, monogramName, truncate } from "./presentation.js";
import { claimMorph } from "./parts.jsx";

/* "What's known": facts on a vertical tideline, grouped by chapter. */
export function KnownTideline({ facts, ceiling }) {
  const groups = groupFactsByChapter(facts);
  return (
    <section className="card cx-known rise" style={{ "--i": 6 }} aria-labelledby="cx-known-title">
      <header className="cx-panel-head">
        <h2 id="cx-known-title" className="section-eyebrow">What's known · ch. ≤ {fmtChapter(ceiling)}</h2>
        {facts.length > 0 && <span className="cx-panel-note">{facts.length} {facts.length === 1 ? "fact" : "facts"}</span>}
      </header>
      {facts.length === 0
        ? <p className="cx-known-empty">No recorded facts at this chapter yet.</p>
        : (
          <ol className="cx-tideline">
            {groups.map((group, gi) => (
              <li key={`${group.ch}-${gi}`} className="cx-tl-group" style={{ "--g": gi }}>
                <div className="cx-tl-mark"><span>Ch.</span><b>{fmtChapter(group.ch)}</b></div>
                <span className="cx-tl-node" aria-hidden="true" />
                <ul className="cx-tl-facts">
                  {group.items.map((fact, i) => (
                    <li key={fact.id ?? i} className="cx-fact">
                      <span className="cx-fact-type">{fact.type || "fact"}</span>
                      <span className="cx-fact-text">{fact.text}</span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        )}
    </section>
  );
}

function RelationCard({ rel, to, state }) {
  const orbRef = useRef(null);
  const type = rel.withType || "concept";
  const body = (
    <>
      <span className="cx-orb" ref={orbRef}><EntityAvatar entity={{ type, name: monogramName(rel.withName) }} /></span>
      <span className="cx-rel-copy">
        <span className="cx-rel-type">{rel.type}</span>
        <b className="cx-rel-name">{rel.withName || "Unknown"}</b>
        {rel.note && <span className="cx-rel-note">{rel.note}</span>}
      </span>
      <span className="cx-rel-ch">Ch. {fmtChapter(rel.ch)}</span>
    </>
  );
  if (!to) return <div className={`cx-rel t-${type}`}>{body}</div>;
  return (
    <Link to={to} state={state} className={`cx-rel is-link t-${type}`} data-spotlight=""
          onClick={() => claimMorph(orbRef.current)}>
      {body}
      <span className="cx-rel-go" aria-hidden="true"><Icon name="arrowRight" size={15} sw={2} /></span>
    </Link>
  );
}

export function RelationshipCards({ items, pathFor, stateFor }) {
  return (
    <section className="cx-relations rise" style={{ "--i": 7 }} aria-labelledby="cx-rel-title">
      <header className="cx-panel-head is-bare">
        <h2 id="cx-rel-title" className="section-eyebrow">Relationships</h2>
        <span className="cx-panel-note">{items.length}</span>
      </header>
      <div className="cx-rel-grid">
        {items.map((rel, i) => (
          <RelationCard key={rel.id ?? i} rel={rel}
                        to={rel.withId != null ? pathFor(rel.withId) : null}
                        state={rel.withId != null ? stateFor({ id: rel.withId, name: rel.withName, type: rel.withType }) : undefined} />
        ))}
      </div>
    </section>
  );
}

/* A small radial map around the entity. It repeats the relationship list
   visually (the list above stays the accessible, complete source). */
export function Constellation({ entity, items, onOpen }) {
  const radius = 84;
  const { nodes, total } = constellation(items, { max: 8, radius });
  if (!nodes.length) return null;
  const summary = nodes.map(n => `${n.relations.join(", ") || "related to"} ${n.withName || "an unknown entity"}`).join("; ");
  const more = total - nodes.length;
  const letter = (monogramName(entity.name) || "?").charAt(0).toUpperCase();
  return (
    <figure className="card cx-constellation rise" style={{ "--i": 6 }}>
      <figcaption className="cx-side-title"><Icon name="spark" size={13} sw={2} /> Connections</figcaption>
      <svg className="cx-cn-svg" viewBox="-178 -124 356 250" role="img"
           aria-label={`Relationship map for ${entity.name}: ${summary}${more > 0 ? `; and ${more} more` : ""}.`}>
        <circle className="cx-cn-orbit" r={radius} />
        <circle className="cx-cn-orbit is-inner" r={radius * 0.56} />
        {nodes.map(n => {
          const label = truncate(n.withName || "Unknown", 15);
          const top = n.side === "middle" && n.y < 0;
          const lx = n.side === "start" ? 22 : n.side === "end" ? -22 : 0;
          const ly = n.side === "middle" ? (top ? -24 : 33) : 5;
          const type = n.withType || "concept";
          return (
            <g key={n.index} className={`cx-cn-node t-${type}` + (n.withId != null ? " is-link" : "")}
               transform={`translate(${n.x.toFixed(1)} ${n.y.toFixed(1)})`} style={{ "--k": n.index }}
               onClick={() => onOpen(n)}>
              <line className="cx-cn-link" x1={(-n.x).toFixed(1)} y1={(-n.y).toFixed(1)} x2="0" y2="0" pathLength="1" />
              <g className="cx-cn-pop">
                <circle className="cx-cn-halo" r="19" />
                <circle className="cx-cn-dot" r="14" />
                <text className="cx-cn-letter" dy="0.36em">{(monogramName(n.withName) || "?").charAt(0).toUpperCase()}</text>
              </g>
              <text className="cx-cn-label" x={lx} y={ly} textAnchor={n.side}>{label}</text>
              <title>{`${n.relations.join(", ")} — ${n.withName || "Unknown"}`}</title>
            </g>
          );
        })}
        <g className={`cx-cn-center t-${entity.type}`}>
          <circle className="cx-cn-center-halo" r="34" />
          <circle className="cx-cn-center-core" r="25" />
          <text className="cx-cn-center-letter" dy="0.36em">{letter}</text>
        </g>
      </svg>
      {more > 0 && <p className="cx-cn-more">+{more} more in the list</p>}
    </figure>
  );
}

export function Timeline({ items, moreToCome }) {
  return (
    <section className="card cx-timeline rise" style={{ "--i": 7 }} aria-labelledby="cx-timeline-title">
      <h2 id="cx-timeline-title" className="cx-side-title"><Icon name="clock" size={13} sw={2} /> Timeline</h2>
      <ol className="cx-tlist">
        {items.length === 0 && <li className="cx-tlist-empty">No timeline yet at this chapter.</li>}
        {items.map((t, i) => (
          <li key={i} className="cx-tlist-item" style={{ "--k": i }}>
            <span className="cx-tlist-dot" aria-hidden="true" />
            <span className="cx-tlist-ch">Chapter {fmtChapter(t.chapter)}</span>
            <span className="cx-tlist-text">{t.content}</span>
          </li>
        ))}
        {moreToCome && (
          <li className="cx-tlist-item is-future" style={{ "--k": items.length }}>
            <span className="cx-tlist-dot" aria-hidden="true" />
            <span className="cx-tlist-ch">More to come</span>
            <span className="cx-tlist-text">Hidden until you read further.</span>
          </li>
        )}
      </ol>
    </section>
  );
}
