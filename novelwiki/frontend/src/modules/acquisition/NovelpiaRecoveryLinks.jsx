import React from "react";

export function NovelpiaRecoveryLinks({ kind, error }) {
  if (kind !== "scrape" || typeof error !== "string" || !/\bNovelpia\b/i.test(error)) return null;
  const chapter = (error.match(/https?:\/\/[^\s<>"']+/g) || [])
    .map(candidate => candidate.replace(/[),.;]+$/, ""))
    .find(candidate => /^https:\/\/global\.novelpia\.com\/viewer\/[1-9]\d*$/.test(candidate));
  const needsCookies = /\b(cookies?|login|session)\b/i.test(error);
  if (!chapter && !needsCookies) return null;
  return (
    <div className="row wrap source-recovery-links">
      {chapter && <a href={chapter} target="_blank" rel="noreferrer">Open chapter on Novelpia</a>}
      {needsCookies && <a href="/account/sources" target="_blank" rel="noreferrer">Update Novelpia cookies</a>}
    </div>
  );
}
