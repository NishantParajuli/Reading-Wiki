import React from "react";
import { Chip } from "./ui.jsx";
import { PROVENANCE_LABELS, PROVENANCE_ORDER } from "../lib/constants.js";

export function ProvenanceBadges({ provenance, className }) {
  if (!provenance) return null;
  const on = PROVENANCE_ORDER.filter(k => provenance[k]);
  if (on.length === 0) return null;
  return (
    <div className={"prov-badges " + (className || "")}>
      {on.map(k => (
        <Chip key={k} tone="ok" title={PROVENANCE_LABELS[k].title}>{PROVENANCE_LABELS[k].label}</Chip>
      ))}
    </div>
  );
}
