/* Ask (§6.8) — grounded, cited, chapter-bounded Q&A. The old fake
   "DeepSeek Pro/Flash" 4-step theater is replaced by an honest 3-stage
   thinking shimmer with no model branding; completion is tied to the real
   /ask response. Recap lives beside the suggestions. */
import React, { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { codexApi } from "../../modules/codex/api.js";
import { buildCiteMap } from "../../modules/codex/presentation.js";
import { experienceApi } from "../../modules/experience/api.js";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState, Spinner } from "../../components/ui.jsx";
import { AnswerBody } from "../../lib/markdown.jsx";
import { CeilingControl } from "./CeilingControl.jsx";
import { useTitle } from "../../lib/hooks.js";
import { fmtChapter } from "../../lib/utils.js";

const STAGES = [
  { key: "search", label: "Searching your chapters", sub: "Only text at or below your ceiling", icon: "search" },
  { key: "read", label: "Reading the evidence", sub: "Weighing retrieved passages", icon: "layers" },
  { key: "write", label: "Writing the answer", sub: "Every claim cited back to a chapter", icon: "edit" },
];

const SUGGESTIONS = [
  "Who is the most important character so far?",
  "Summarize the main conflict up to this point.",
  "What factions or groups have appeared?",
  "Which locations have been introduced?",
];

function Answer({ result, ceiling }) {
  const answer = (result && result.answer || "").trim();
  const citations = (result && result.citations) || [];

  if (!answer) {
    return (
      <div className="answer-card card answer-enter" style={{ marginTop: 18 }}>
        <EmptyState icon="compass" title="No grounded evidence found"
          body={`I searched the codex through chapter ${fmtChapter(ceiling)} and couldn't find enough cited evidence to answer that confidently. Try rephrasing, or read a little further.`} />
      </div>
    );
  }

  const citeMap = buildCiteMap(citations);
  const nSources = citations.length;

  return (
    <div className="answer-card card answer-enter" style={{ marginTop: 18 }}>
      <AnswerBody answer={answer} citeMap={citeMap} />
      <div className="answer-foot">
        {nSources > 0
          ? <span className="verified"><Icon name="shield" size={15} sw={2.2} /> Verified · grounded in cited evidence</span>
          : <span className="muted" style={{ fontSize: "var(--text-sm)" }}>No direct citations resolved</span>}
        <Chip>bounded to ch. ≤ {fmtChapter(ceiling)}</Chip>
        {nSources > 0 && <Chip className="mono">{nSources} source{nSources === 1 ? "" : "s"}</Chip>}
      </div>
    </div>
  );
}

function RecapCard({ novelId, ceiling }) {
  const [state, setState] = useState({ status: "idle" });

  async function run() {
    setState({ status: "loading" });
    try {
      const r = await experienceApi.recap(novelId, ceiling);
      setState({ status: "ready", data: r });
    } catch (e) {
      setState({ status: "error", message: e.message || "Recap failed." });
    }
  }

  const d = state.data;
  return (
    <div className="card recap-card">
      <div className="row">
        <span className="verified"><Icon name="book" size={14} /> Story so far</span>
        <span className="muted" style={{ fontSize: "var(--text-xs)", marginLeft: "auto" }}>
          Spoiler-safe · up to ch. {fmtChapter(ceiling)}
        </span>
      </div>
      {state.status === "idle" && (
        <p className="muted" style={{ fontSize: "var(--text-sm)", lineHeight: 1.55 }}>
          Get a concise recap of everything up to your current chapter — nothing past it.
        </p>
      )}
      {state.status === "error" && <p className="acct-err">{state.message}</p>}
      {state.status === "ready" && d && (
        <>
          <div className="recap-body"><AnswerBody answer={d.answer || ""} citeMap={buildCiteMap(d.citations)} /></div>
          {d.ceiling_clamped && (
            <p className="muted" style={{ fontSize: "var(--text-xs)", marginTop: 6 }}>
              Bounded to chapter {fmtChapter(d.effective_ceiling)} (your trusted progress).
            </p>
          )}
        </>
      )}
      <div className="row" style={{ marginTop: 12 }}>
        <Button variant="secondary" icon="sparkles" onClick={run} loading={state.status === "loading"}>
          {state.status === "loading" ? "Building recap…" : state.status === "ready" ? "Refresh recap" : "Recap the story so far"}
        </Button>
      </div>
      {state.status === "loading" && (
        <p className="muted" style={{ fontSize: "var(--text-xs)", margin: "8px 0 0" }}>
          A fresh recap can take a few minutes. Keep this tab open while it finishes.
        </p>
      )}
    </div>
  );
}

export function Ask() {
  const { novel, novelId, ceiling } = useNovel();
  const [sp] = useSearchParams();
  const initial = sp.get("q") || "";
  const [input, setInput] = useState(initial);
  const [active, setActive] = useState(null);
  const [phase, setPhase] = useState("idle");    // idle | running | done | error
  const [stageIdx, setStageIdx] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const timers = useRef([]);
  const didInitial = useRef(false);
  useTitle("Ask", novel.title);

  const clearTimers = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  useEffect(() => clearTimers, []);

  async function run(question) {
    clearTimers();
    setActive(question);
    setResult(null); setError(null);
    setPhase("running");
    setStageIdx(0);
    // The first two stages advance on a gentle timer; the last holds until
    // the real response lands — no fabricated sub-steps, no model names.
    timers.current.push(setTimeout(() => setStageIdx(1), 1100));
    timers.current.push(setTimeout(() => setStageIdx(2), 2600));
    try {
      const res = await codexApi.ask(novelId, question, ceiling);
      clearTimers();
      setStageIdx(STAGES.length);
      setResult(res);
      setPhase("done");
    } catch (e) {
      clearTimers();
      setError(e.message || "Something went wrong while answering.");
      setPhase("error");
    }
  }

  function submit(e) {
    e && e.preventDefault();
    const text = input.trim();
    if (!text || phase === "running") return;
    run(text);
  }
  function pick(qText) { setInput(qText); run(qText); }

  useEffect(() => {
    if (initial && !didInitial.current) {
      didInitial.current = true;
      run(initial);
    }
  }, [initial]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="page page-narrow page-enter">
      <div className="row" style={{ justifyContent: "flex-end", marginBottom: 10 }}>
        <CeilingControl />
      </div>
      <div className="ask-hero">
        <h1>Ask the Codex</h1>
        <p>Grounded answers, bounded to chapter <b style={{ color: "var(--accent-ink)" }}>{fmtChapter(ceiling)}</b>.</p>
      </div>

      <form className="ask-bar" onSubmit={submit}>
        <Icon name="sparkles" size={20} style={{ color: "var(--accent-ink)" }} />
        <input value={input} onChange={e => setInput(e.target.value)}
               placeholder="Ask anything about what you've read so far…" aria-label="Your question" />
        <Button type="submit" variant="primary" icon="send" disabled={phase === "running"}>Ask</Button>
      </form>

      {phase === "idle" && (
        <>
          <div className="suggestions">
            {SUGGESTIONS.map((qText, i) => (
              <button key={i} className="suggestion" onClick={() => pick(qText)}>{qText}</button>
            ))}
          </div>
          <RecapCard novelId={novelId} ceiling={ceiling} />
        </>
      )}

      {active && (
        <div style={{ marginTop: 28 }}>
          {phase === "running" && (
            <div className="card thinking">
              {STAGES.map((s, i) => {
                const state = i < stageIdx ? "done" : i === stageIdx ? "active" : "";
                return (
                  <div key={s.key} className={`think-step ${state}`}>
                    <div className="think-icon">
                      {state === "active" ? <Spinner />
                        : state === "done" ? <Icon name="check" size={16} sw={2.4} />
                        : <Icon name={s.icon} size={16} />}
                    </div>
                    <div className="grow">
                      <div className="think-label">{s.label}</div>
                      <div className="think-sub">{s.sub}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {phase === "done" && <Answer result={result} ceiling={ceiling} />}
          {phase === "error" && (
            <div className="answer-card card answer-enter">
              <EmptyState icon="x" title="Couldn't answer that" body={error} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
