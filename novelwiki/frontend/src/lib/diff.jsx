/* LCS-based line diff + GitHub/GitLab-style DiffView. */
import React from "react";

export function lineDiff(oldText, newText) {
  const a = String(oldText == null ? "" : oldText).split("\n");
  const b = String(newText == null ? "" : newText).split("\n");
  const n = a.length, m = b.length;
  // Guard the O(n*m) table against pathologically large inputs.
  if (n * m > 4000000) {
    return [...a.map(t => ({ t: "del", text: t })), ...b.map(t => ({ t: "add", text: t }))];
  }
  const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ t: "ctx", text: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ t: "del", text: a[i] }); i++; }
    else { out.push({ t: "add", text: b[j] }); j++; }
  }
  while (i < n) out.push({ t: "del", text: a[i++] });
  while (j < m) out.push({ t: "add", text: b[j++] });
  return out;
}

const SIGN = { add: "+", del: "−", ctx: " " };

/* Two stacked boxes: the upper shows the original text plain; the lower shows the
   new text as a unified diff (removed lines red, added green, unchanged muted). */
export function DiffView({ oldText, newText, oldLabel, newLabel }) {
  const rows = lineDiff(oldText, newText);
  return (
    <div className="diff-view">
      <div className="diff-pane">
        <div className="diff-pane-head">{oldLabel || "Original"}</div>
        <pre className="diff-orig">{String(oldText == null ? "" : oldText) || "​"}</pre>
      </div>
      <div className="diff-pane">
        <div className="diff-pane-head">{newLabel || "Proposed changes"}</div>
        <div className="diff-lines">
          {rows.map((r, k) => (
            <div key={k} className={"diff-line diff-" + r.t}>
              <span className="diff-gutter">{SIGN[r.t]}</span>
              <span className="diff-text">{r.text === "" ? "​" : r.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
