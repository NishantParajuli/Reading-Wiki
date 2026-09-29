/* Ask the Codex — an oracle over what you have read. Grounded Q&A and recaps
   are cleared whenever the chapter boundary changes, and late answers for an
   old boundary are ignored. The waiting state is honest: one calm ripple and
   the real copy — never simulated stages. */
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { codexApi } from "./api.js";
import { buildCiteMap } from "./presentation.js";
import { experienceApi } from "../../modules/experience/api.js";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, EmptyState } from "../../components/ui.jsx";
import { TextReveal } from "../../motion/TextReveal.jsx";
import { AnswerBody, collectCitations } from "../../lib/markdown.jsx";
import { CeilingControl } from "./CeilingControl.jsx";
import { useTitle } from "../../lib/hooks.js";
import { fmtChapter } from "../../lib/utils.js";
import { useTypeReveal } from "./typeReveal.js";

const SUGGESTIONS = [
  "Who is the most important character so far?",
  "Summarize the main conflict up to this point.",
  "What factions or groups have appeared?",
  "Which locations have been introduced?",
];

// Snippets that already open with a quotation mark are not wrapped again.
const startsQuoted = (text) => /^[\u201C\u2018"']/.test(String(text).trim());

function Sources({ entries }) {
  if (!entries.length) return null;
  return (
    <div className="cx-sources">
      <h3 className="cx-sources-title">Sources</h3>
      <ol className="cx-sources-list">
        {entries.map(({ n, key, cite }) => (
          <li key={key} className="cx-source">
            <span className="cx-source-n" aria-hidden="true">{n}</span>
            <span className="cx-source-body">
              <span className="cx-source-where">
                <span className="sr-only">Source {n}: </span>
                {cite.ch != null ? `Chapter ${fmtChapter(cite.ch)}` : "Source"}
              </span>
              {cite.quote && <span className={"cx-source-quote" + (startsQuoted(cite.quote) ? " is-quoted" : "")}>{cite.quote}</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Answer({ result, ceiling }) {
  const answer = (result && result.answer || "").trim();
  const citations = (result && result.citations) || [];
  const typeRef = useTypeReveal(answer);

  if (!answer) {
    return (
      <div className="cx-answer card answer-enter">
        <EmptyState icon="compass" title="No grounded evidence found"
          body={`I searched the codex through chapter ${fmtChapter(ceiling)} and couldn't find enough cited evidence to answer that confidently. Try rephrasing, or read a little further.`} />
      </div>
    );
  }

  const citeMap = buildCiteMap(citations);
  const shown = collectCitations(answer, citeMap);
  const nSources = citations.length;

  return (
    <article className="cx-answer card answer-enter">
      <header className="cx-answer-head">
        <span className="cx-answer-mark" aria-hidden="true"><Icon name="sparkles" size={15} sw={2} /></span>
        <span className="cx-answer-eyebrow">The Codex answers</span>
      </header>
      <div className="cx-type cx-answer-text" ref={typeRef}>
        <AnswerBody answer={answer} citeMap={citeMap} />
      </div>
      <Sources entries={shown} />
      <footer className="answer-foot">
        {nSources > 0
          ? <span className="verified"><Icon name="book" size={15} sw={2.2} /> Includes chapter references</span>
          : <span className="cx-foot-muted">No direct citations resolved</span>}
        <span className="answer-foot-chips">
          <Chip icon="shield">bounded to ch. ≤ {fmtChapter(ceiling)}</Chip>
          {nSources > 0 && <Chip className="mono">{nSources} source{nSources === 1 ? "" : "s"}</Chip>}
        </span>
      </footer>
    </article>
  );
}

/* One slow ripple on still water, and the real copy. Elapsed time is shown
   (not announced) once the wait is noticeable. */
function Waiting({ ceiling }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);
  const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  return (
    <div className="cx-waiting card answer-enter" role="status">
      <div className="cx-pool" aria-hidden="true"><i /><i /><i /><span className="cx-pool-drop" /></div>
      <div className="cx-waiting-copy">
        <div className="cx-waiting-label">Looking through your story…</div>
        <div className="cx-waiting-sub">Using evidence through chapter {fmtChapter(ceiling)}. This can take a few minutes.</div>
      </div>
      {seconds >= 3 && <span className="cx-elapsed" aria-hidden="true">{clock}</span>}
    </div>
  );
}

function RecapCard({ novelId, ceiling }) {
  const [state, setState] = useState({ status: "idle" });
  const activeRequest = useRef(0);
  useEffect(() => () => { activeRequest.current += 1; }, []);

  async function run() {
    const request = ++activeRequest.current;
    setState({ status: "loading" });
    try {
      const r = await experienceApi.recap(novelId, ceiling);
      if (request !== activeRequest.current) return;
      setState({ status: "ready", data: r });
    } catch (e) {
      if (request !== activeRequest.current) return;
      setState({ status: "error", message: e.message || "Recap failed." });
    }
  }

  const d = state.data;
  const typeRef = useTypeReveal(state.status === "ready" && d ? d.answer || "" : "");
  return (
    <section className={"cx-recap card rise is-" + state.status} style={{ "--i": 8 }} aria-labelledby="cx-recap-title">
      <div className="cx-recap-head">
        <span className="cx-recap-icon" aria-hidden="true"><Icon name="bookOpen" size={18} /></span>
        <div className="cx-recap-titles">
          <h2 id="cx-recap-title" className="cx-recap-title">Story so far</h2>
          <span className="cx-recap-bound"><Icon name="shield" size={12} sw={2} /> Spoiler-safe · up to ch. {fmtChapter(ceiling)}</span>
        </div>
      </div>
      {state.status === "idle" && (
        <p className="cx-recap-lead">
          Get a concise recap of everything up to your current chapter — nothing past it.
        </p>
      )}
      {state.status === "error" && <p className="cx-recap-error" role="alert"><Icon name="circleAlert" size={15} /> {state.message}</p>}
      {state.status === "ready" && d && (
        <>
          <div className="recap-body cx-type" ref={typeRef}><AnswerBody answer={d.answer || ""} citeMap={buildCiteMap(d.citations)} /></div>
          {d.ceiling_clamped && (
            <p className="cx-recap-note">
              Bounded to chapter {fmtChapter(d.effective_ceiling)} (your trusted progress).
            </p>
          )}
        </>
      )}
      <div className="cx-recap-actions">
        <Button variant="secondary" icon="sparkles" onClick={run} loading={state.status === "loading"}>
          {state.status === "loading" ? "Building recap…" : state.status === "ready" ? "Refresh recap" : "Recap the story so far"}
        </Button>
        {state.status === "loading" && (
          <p className="cx-recap-note">
            A fresh recap can take a few minutes. Keep this tab open while it finishes.
          </p>
        )}
      </div>
    </section>
  );
}

function QuestionField({ value, onChange, onSubmit, busy }) {
  const ref = useRef(null);
  // Grow with the question (up to a few lines) instead of scrolling sideways.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    if (el.scrollHeight > 0) el.style.height = `${Math.min(el.scrollHeight, 188)}px`;
  }, [value]);
  return (
    <form className="cx-ask-form rise" style={{ "--i": 4 }} onSubmit={onSubmit}>
      <div className="cx-ask-shell">
        <span className="cx-ask-glow" aria-hidden="true" />
        <div className="cx-ask-field">
          <span className="cx-ask-glyph" aria-hidden="true"><Icon name="sparkles" size={20} /></span>
          <textarea ref={ref} rows={1} value={value} onChange={e => onChange(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); onSubmit(); }
                    }}
                    placeholder="Ask anything about what you've read so far…" aria-label="Your question"
                    enterKeyHint="send" spellCheck />
          <Button type="submit" variant="primary" icon="send" className="cx-ask-submit" disabled={busy || !value.trim()}>Ask</Button>
        </div>
      </div>
      <p className="cx-ask-hint" aria-hidden="true"><kbd>Enter</kbd> to send · <kbd>Shift</kbd> + <kbd>Enter</kbd> for a new line</p>
    </form>
  );
}

export function Ask() {
  const { novel, novelId, ceiling } = useNovel();
  const [sp] = useSearchParams();
  const initial = sp.get("q") || "";
  const [input, setInput] = useState(initial);
  const [active, setActive] = useState(null);
  const [phase, setPhase] = useState("idle");    // idle | running | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const requestId = useRef(0);
  const [activeScope, setActiveScope] = useState(null);
  const scope = `${novelId}:${ceiling}`;
  const didInitial = useRef(false);
  useTitle("Ask", novel.title);

  useEffect(() => {
    requestId.current += 1;
    setPhase("idle"); setActive(null); setResult(null); setError(null);
    return () => { requestId.current += 1; };
  }, [scope]);

  async function run(question) {
    const request = ++requestId.current;
    setActiveScope(scope);
    setActive(question);
    setResult(null); setError(null);
    setPhase("running");
    try {
      const res = await codexApi.ask(novelId, question, ceiling);
      if (request !== requestId.current) return;
      setResult(res);
      setPhase("done");
    } catch (e) {
      if (request !== requestId.current) return;
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

  const visiblePhase = activeScope === scope ? phase : "idle";

  return (
    <div className={"page page-narrow cx-page cx-ask page-enter" + (visiblePhase !== "idle" ? " is-asking" : "")}>
      <div className="cx-ask-top">
        <CeilingControl />
      </div>
      <header className="cx-ask-hero">
        <div className="cx-oracle" aria-hidden="true"><span className="cx-oracle-core" /><i /><i /></div>
        <h1 className="cx-ask-title">
          <TextReveal text="Ask the" delay={120} />{" "}
          <TextReveal text="Codex" className="cx-title-em" delay={260} />
        </h1>
        <p className="cx-ask-sub rise" style={{ "--i": 3 }}>
          Grounded answers, bounded to chapter <b>{fmtChapter(ceiling)}</b>.
        </p>
      </header>

      <QuestionField value={input} onChange={setInput} onSubmit={submit} busy={visiblePhase === "running"} />

      {visiblePhase === "idle" && (
        <>
          <div className="cx-suggestions" aria-label="Suggested questions" role="group">
            {SUGGESTIONS.map((qText, i) => (
              <button key={i} type="button" className="cx-suggestion rise" style={{ "--i": 5 + i }} onClick={() => pick(qText)}>
                <Icon name="sparkles" size={13} sw={2} />
                <span>{qText}</span>
                <Icon name="arrowRight" size={14} sw={2} className="cx-suggestion-go" />
              </button>
            ))}
          </div>
          <RecapCard key={scope} novelId={novelId} ceiling={ceiling} />
        </>
      )}

      {active && activeScope === scope && (
        <section className="cx-thread" aria-labelledby="cx-question">
          <div className="cx-question">
            <span className="cx-question-kicker">Your question</span>
            <h2 id="cx-question" className="cx-question-text">{active}</h2>
          </div>
          {phase === "running" && <Waiting ceiling={ceiling} />}
          {phase === "done" && <Answer result={result} ceiling={ceiling} />}
          {phase === "error" && (
            <div className="cx-answer card answer-enter">
              <EmptyState icon="x" title="Couldn't answer that" body={error}
                primaryAction={<Button variant="secondary" icon="refresh" onClick={() => run(active)}>Try again</Button>} />
            </div>
          )}
        </section>
      )}
    </div>
  );
}
