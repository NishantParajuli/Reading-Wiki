/* ============================================================
   Admin — ingestion pipeline controls (gated; reached via the gear menu)
   Wraps the /api/admin/* endpoints. All jobs run in the background on the
   server; these forms just schedule them and surface the server's reply.
   ============================================================ */
function useAction() {
  const [res, setRes] = useState(null); // { kind: 'pending'|'ok'|'err', msg }
  const [busy, setBusy] = useState(false);
  const run = async (fn) => {
    setBusy(true);
    setRes({ kind: "pending", msg: "Scheduling…" });
    try {
      const r = await fn();
      setRes({ kind: "ok", msg: (r && r.message) || "Done." });
    } catch (e) {
      setRes({ kind: "err", msg: (e && e.message) || "Request failed." });
    } finally {
      setBusy(false);
    }
  };
  return { res, busy, run };
}

function ResultLine({ res }) {
  if (!res) return null;
  const icon = res.kind === "ok" ? "check" : res.kind === "err" ? "x" : "clock";
  return (
    <div className={`admin-result ${res.kind}`}>
      <Icon name={icon} size={15} sw={2.2} />
      <span>{res.msg}</span>
    </div>
  );
}

function AdminCard({ icon, title, sub, children }) {
  return (
    <div className="card admin-card">
      <div className="admin-card-head">
        <div className="admin-card-icon"><Icon name={icon} size={19} /></div>
        <div>
          <div className="admin-card-title">{title}</div>
          <div className="admin-card-sub">{sub}</div>
        </div>
      </div>
      {children}
    </div>
  );
}

function numOrNull(v) {
  const s = String(v).trim();
  if (s === "") return null;
  const n = Number(s);
  return Number.isNaN(n) ? null : n;
}

function ScrapeCard() {
  const [url, setUrl] = useState("");
  const [max, setMax] = useState("");
  const [force, setForce] = useState(false);
  const { res, busy, run } = useAction();
  const submit = (e) => {
    e.preventDefault();
    if (!url.trim()) return;
    run(() => window.API.admin.scrape({
      start_url: url.trim(),
      max_chapters: numOrNull(max),
      force,
    }));
  };
  return (
    <AdminCard icon="spider" title="Scrape chapters" sub="Walk the site adapter sequentially into `chapters`.">
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="field">
          <label>Start URL</label>
          <input type="url" required value={url} onChange={(e) => setUrl(e.target.value)}
                 placeholder="https://site/novel/.../chapter-1" />
        </div>
        <div className="field">
          <label>Max chapters (optional)</label>
          <input type="number" min="1" value={max} onChange={(e) => setMax(e.target.value)} placeholder="all" />
        </div>
        <label className="field-check">
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
          Re-fetch chapters already present
        </label>
        <button className="btn btn-primary" type="submit" disabled={busy || !url.trim()}>
          <Icon name="spider" size={16} /> Run scraper
        </button>
        <ResultLine res={res} />
      </form>
    </AdminCard>
  );
}

function RangeCard({ icon, title, sub, buttonLabel, withForce, action }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [force, setForce] = useState(false);
  const { res, busy, run } = useAction();
  const submit = (e) => {
    e.preventDefault();
    const body = { from_chapter: numOrNull(from), to_chapter: numOrNull(to) };
    if (withForce) body.force = force;
    run(() => action(body));
  };
  return (
    <AdminCard icon={icon} title={title} sub={sub}>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="field-row">
          <div className="field">
            <label>From ch.</label>
            <input type="number" step="0.5" value={from} onChange={(e) => setFrom(e.target.value)} placeholder="start" />
          </div>
          <div className="field">
            <label>To ch.</label>
            <input type="number" step="0.5" value={to} onChange={(e) => setTo(e.target.value)} placeholder="end" />
          </div>
        </div>
        {withForce && (
          <label className="field-check">
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
            Reprocess even if already done
          </label>
        )}
        <button className="btn btn-primary" type="submit" disabled={busy}>
          <Icon name={icon} size={16} /> {buttonLabel}
        </button>
        <ResultLine res={res} />
      </form>
    </AdminCard>
  );
}

function Bm25Card() {
  const { res, busy, run } = useAction();
  return (
    <AdminCard icon="refresh" title="Rebuild BM25 index" sub="Rebuild + persist the in-process lexical index from chunks.">
      <button className="btn btn-primary" disabled={busy}
              onClick={() => run(() => window.API.admin.rebuildBm25())}>
        <Icon name="refresh" size={16} /> Rebuild index
      </button>
      <ResultLine res={res} />
    </AdminCard>
  );
}

function MergeCard() {
  const [keep, setKeep] = useState("");
  const [drop, setDrop] = useState("");
  const { res, busy, run } = useAction();
  const submit = (e) => {
    e.preventDefault();
    const keepId = numOrNull(keep), dropId = numOrNull(drop);
    if (keepId == null || dropId == null) return;
    run(() => window.API.admin.mergeEntities({ keep_id: keepId, drop_id: dropId }));
  };
  return (
    <AdminCard icon="merge" title="Merge entities" sub="Fold a duplicate (drop) into the canonical entity (keep). Extraction-error dedup.">
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="field-row">
          <div className="field">
            <label>Keep ID</label>
            <input type="number" value={keep} onChange={(e) => setKeep(e.target.value)} placeholder="canonical" />
          </div>
          <div className="field">
            <label>Drop ID</label>
            <input type="number" value={drop} onChange={(e) => setDrop(e.target.value)} placeholder="duplicate" />
          </div>
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy || !keep.trim() || !drop.trim()}>
          <Icon name="merge" size={16} /> Merge
        </button>
        <ResultLine res={res} />
      </form>
    </AdminCard>
  );
}

function Admin({ setView }) {
  return (
    <div className="page">
      <button className="btn btn-ghost" style={{ padding: "8px 14px" }} onClick={() => setView("home")}>
        <Icon name="arrowLeft" size={16} /> Back to reader
      </button>

      <div className="admin-hero" style={{ marginTop: 16 }}>
        <p className="section-eyebrow">Ingestion pipeline</p>
        <h1>Admin</h1>
        <p>Build the codex end-to-end: scrape chapters, chunk &amp; embed them, run forward-only
           extraction, and keep the lexical index fresh. Jobs run in the background on the server.</p>
        <span className="admin-warn">
          <Icon name="shield" size={14} /> These trigger real scraping and paid API calls — use deliberately.
        </span>
      </div>

      <div className="admin-grid">
        <ScrapeCard />
        <RangeCard icon="scissors" title="Chunk chapters" buttonLabel="Run chunking" withForce
                   sub="Split chapter bodies into within-chapter chunks."
                   action={(b) => window.API.admin.chunk(b)} />
        <RangeCard icon="cpu" title="Embed chunks" buttonLabel="Run embedding"
                   sub="Generate vector embeddings for chunks missing one."
                   action={(b) => window.API.admin.embed(b)} />
        <RangeCard icon="brain" title="Extract knowledge" buttonLabel="Run extraction" withForce
                   sub="Forward-only entity / fact / relationship extraction."
                   action={(b) => window.API.admin.extract(b)} />
        <Bm25Card />
        <MergeCard />
      </div>
    </div>
  );
}

window.Admin = Admin;
