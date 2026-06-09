/* ============================================================
   Ask — agentic, cited, chapter-bounded Q&A (backend-driven)
   The 4-step animation mirrors the real orchestrator (Pro plans → Flash
   retrieves/distills → Pro reasons → Flash verifies). The steps advance on a
   timer for feel, but completion is tied to the real /ask response; the final
   "verify" step holds its spinner until the server actually returns.
   ============================================================ */
const AGENT_STEPS = [
  { key: "plan", label: "Planning the approach", sub: "Decomposing the question into sub-goals", model: "Pro", icon: "brain" },
  { key: "retrieve", label: "Retrieving evidence", sub: "Hybrid search · BM25 ⊕ vector → rerank", model: "Flash", icon: "layers" },
  { key: "reason", label: "Reasoning over digests", sub: "Synthesising from cited, compressed evidence", model: "Pro", icon: "compass" },
  { key: "verify", label: "Verifying grounding", sub: "Every claim traced to a citation ≤ ceiling", model: "Flash", icon: "shield" },
];

const SUGGESTIONS = [
  "Who is the most important character so far?",
  "Summarize the main conflict up to this point.",
  "What factions or groups have appeared?",
  "Which locations have been introduced?",
];

function Ask({ novelId, ceiling, initial }) {
  const [input, setInput] = useState(initial || "");
  const [active, setActive] = useState(null);   // current question text
  const [phase, setPhase] = useState("idle");    // idle | running | done | error
  const [stepIdx, setStepIdx] = useState(-1);
  const [result, setResult] = useState(null);    // {answer, citations, evidence_ids}
  const [error, setError] = useState(null);
  const timers = useRef([]);
  const didInitial = useRef(false);

  const clearTimers = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  useEffect(() => clearTimers, []);

  async function run(question) {
    clearTimers();
    setActive(question);
    setResult(null); setError(null);
    setPhase("running");
    setStepIdx(0);
    const stepMs = [820, 1150, 1000, 760];
    let t = 0;
    for (let i = 0; i < AGENT_STEPS.length - 1; i++) {   // last step holds until response
      t += stepMs[i];
      timers.current.push(setTimeout(() => setStepIdx(i + 1), t));
    }
    try {
      const res = await window.API.ask(novelId, question, ceiling);
      clearTimers();
      setStepIdx(AGENT_STEPS.length); // all done
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

  // Auto-run a prefilled question (e.g. "Ask about X" from an entity page).
  useEffect(() => {
    if (initial && !didInitial.current) {
      didInitial.current = true;
      run(initial);
    }
  }, [initial]); // eslint-disable-line

  return React.createElement("div", { className: "page ask-page" },
    React.createElement("div", { className: "ask-hero" },
      React.createElement("h1", null, "Ask the Codex"),
      React.createElement("p", null,
        "Grounded answers, bounded to chapter ",
        React.createElement("b", { style: { color: "var(--accent-ink)" } }, ceiling), "."
      )
    ),

    React.createElement("form", { className: "ask-bar", onSubmit: submit },
      React.createElement(Icon, { name: "sparkles", size: 20, style: { color: "var(--accent-ink)" } }),
      React.createElement("input", {
        value: input, onChange: e => setInput(e.target.value),
        placeholder: "Ask anything about what you've read so far…",
      }),
      React.createElement("button", { className: "btn btn-primary", type: "submit", disabled: phase === "running" },
        React.createElement(Icon, { name: "send", size: 16 }), "Ask"
      )
    ),

    phase === "idle" && React.createElement("div", { className: "suggestions" },
      SUGGESTIONS.map((qText, i) => React.createElement("button", { key: i, className: "suggestion", onClick: () => pick(qText) }, qText))
    ),

    active && React.createElement("div", { className: "agent" },
      React.createElement("div", { className: "card", style: { padding: 14 } },
        React.createElement("div", { className: "steps" },
          AGENT_STEPS.map((s, i) => {
            const state = phase === "done" || i < stepIdx ? "done" : i === stepIdx ? "active" : "";
            return React.createElement("div", { key: s.key, className: `step ${state}` },
              React.createElement("div", { className: "step-icon" },
                state === "active" ? React.createElement("div", { className: "spinner" })
                  : state === "done" ? React.createElement(Icon, { name: "check", size: 16, sw: 2.4 })
                  : React.createElement(Icon, { name: s.icon, size: 16 })
              ),
              React.createElement("div", { className: "grow" },
                React.createElement("div", { className: "step-label" }, s.label),
                React.createElement("div", { className: "step-sub" }, s.sub)
              ),
              React.createElement("span", { className: "step-model" }, "DeepSeek " + s.model)
            );
          })
        )
      ),
      phase === "done" && React.createElement(Answer, { result, ceiling }),
      phase === "error" && React.createElement("div", { className: "answer-card card answer-enter", style: { marginTop: 18 } },
        React.createElement("div", { className: "notfound", style: { border: "none", background: "transparent", padding: 0 } },
          React.createElement(Icon, { name: "x", size: 22, className: "muted" }),
          React.createElement("div", null,
            React.createElement("b", { className: "serif", style: { fontSize: 18 } }, "Couldn't answer that"),
            React.createElement("p", { className: "muted", style: { fontSize: 15, lineHeight: 1.6, margin: "6px 0 0" } }, error)
          )
        )
      )
    )
  );
}

function Answer({ result, ceiling }) {
  const answer = (result && result.answer || "").trim();
  const citations = (result && result.citations) || [];

  if (!answer) {
    return React.createElement("div", { className: "answer-card card answer-enter", style: { marginTop: 18 } },
      React.createElement("div", { className: "notfound", style: { border: "none", background: "transparent", padding: 0 } },
        React.createElement(Icon, { name: "compass", size: 22, className: "muted" }),
        React.createElement("div", null,
          React.createElement("b", { className: "serif", style: { fontSize: 18 } }, "No grounded evidence found"),
          React.createElement("p", { className: "muted", style: { fontSize: 15, lineHeight: 1.6, margin: "6px 0 0" } },
            `I searched the codex through chapter ${ceiling} and couldn't find enough cited evidence to answer that confidently. Try rephrasing, or read a little further.`)
        )
      )
    );
  }

  const citeMap = window.buildCiteMap(citations);
  const nSources = citations.length;

  return React.createElement("div", { className: "answer-card card answer-enter", style: { marginTop: 18 } },
    React.createElement(AnswerBody, { answer, citeMap }),
    React.createElement("div", { className: "answer-foot" },
      nSources > 0
        ? React.createElement("span", { className: "verified" },
            React.createElement(Icon, { name: "shield", size: 15, sw: 2.2 }), "Verified · grounded in cited evidence")
        : React.createElement("span", { className: "muted", style: { fontSize: 13 } }, "No direct citations resolved"),
      React.createElement("span", { className: "chip" }, `bounded to ch. ≤ ${ceiling}`),
      nSources > 0 && React.createElement("span", { className: "chip mono" }, `${nSources} source${nSources === 1 ? "" : "s"}`)
    )
  );
}

window.Ask = Ask;
