/* ============================================================
   Novel → Chapters: the whole book as a navigable tide chart.
   A sticky glass bar (search + order) rides under the novel capsule; a
   quiet ledger line tallies the book and offers "go to #"; the TOC below
   is volume-grouped (height-tide accordions) or virtualized when flat.
   ============================================================ */
import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../../App.jsx";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { NovelHeader } from "../catalog/index.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, EmptyState, SegmentedControl, Skeleton } from "../../components/ui.jsx";
import { VolumeTOC, groupToc } from "./toc.jsx";
import { readTtsPrefs } from "../narration/index.js";
import { useAudioCoverageQuery, useVoicesQuery } from "../../modules/narration/queries.js";
import { useChaptersQuery } from "../../modules/reading/queries.js";
import { useTitle } from "../../lib/hooks.js";

const fmt = (n) => Number(n).toLocaleString();

function TocSkeleton() {
  return (
    <div className="card toc chx-toc" aria-busy="true" aria-label="Loading chapters">
      {Array.from({ length: 8 }, (_, i) => (
        <div key={i} className="toc-row is-skeleton">
          <Skeleton variant="text" width={34} />
          <Skeleton variant="text" width={`${38 + ((i * 23) % 40)}%`} />
        </div>
      ))}
    </div>
  );
}

export function Chapters() {
  const { novel, novelId } = useNovel();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: toc, isLoading, isError, refetch } = useChaptersQuery(novelId);
  const { data: audioCoverage } = useAudioCoverageQuery(novelId);
  const { data: voicesData } = useVoicesQuery();
  const [q, setQ] = useState("");
  const [jump, setJump] = useState("");
  const [jumpMiss, setJumpMiss] = useState(null);
  const [sortDesc, setSortDesc] = useState(false);
  const [locateNonce, setLocateNonce] = useState(0);
  const [arrival] = useState(() => (typeof document !== "undefined" && document.documentElement.dataset.vt) || "direct");
  useTitle("Chapters", novel.title);

  const progress = novel.progress || {};
  const currentNumber = progress.last_chapter != null ? Number(progress.last_chapter) : null;
  const maxRead = progress.max_chapter_read != null ? Number(progress.max_chapter_read) : null;

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return toc || [];
    return (toc || []).filter(c =>
      String(c.number).includes(needle) || (c.title || "").toLowerCase().includes(needle));
  }, [toc, q]);

  const tally = useMemo(() => {
    const list = toc || [];
    const chapters = list.filter(c => !c.kind || c.kind === "chapter");
    return {
      chapters: chapters.length,
      volumes: groupToc(list).filter(n => n.type === "vol").length,
      read: maxRead ? chapters.filter(c => c.number <= maxRead).length : 0,
      narrated: ((audioCoverage && audioCoverage.chapters) || []).length,
    };
  }, [toc, maxRead, audioCoverage]);

  function doJump(e) {
    e.preventDefault();
    const n = parseFloat(jump);
    if (!isNaN(n) && (toc || []).some(c => Number(c.number) === n)) {
      setJumpMiss(null);
      navigate(`/n/${novelId}/read/${n}`);
    } else if (jump.trim()) {
      setJumpMiss(jump.trim());
    }
  }

  const hasToc = (toc || []).length > 0;
  const canLocate = currentNumber != null && !q && (toc || []).some(c => Number(c.number) === currentNumber);
  return (
    <div className={"page nv-page chx-page" + (arrival === "direct" ? " page-enter" : "")}>
      <NovelHeader compact />

      {(hasToc || isLoading) && (
        <div className="chx-toolbar" role="search" aria-label="Chapters">
          <div className="search-box chx-search">
            <Icon name="search" size={16} />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="Title or number…" aria-label="Search chapters" />
            {q && <button type="button" className="icon-btn plain" aria-label="Clear" onClick={() => setQ("")}><Icon name="x" size={13} /></button>}
          </div>
          {q && <span className="chx-matches mono" role="status">{fmt(filtered.length)} match{filtered.length === 1 ? "" : "es"}</span>}
          <SegmentedControl fit ariaLabel="Sort order" value={sortDesc} className="chx-sort"
            onChange={setSortDesc}
            options={[{ value: false, label: "1 → n", title: "Oldest first" }, { value: true, label: "n → 1", title: "Newest first" }]} />
        </div>
      )}

      {hasToc && (
        <div className="chx-ledger">
          <p className="chx-tally">
            <span><b className="mono">{fmt(tally.chapters)}</b> chapters</span>
            {tally.volumes > 0 && <span><b className="mono">{fmt(tally.volumes)}</b> volumes</span>}
            {tally.read > 0 && <span><b className="mono">{fmt(tally.read)}</b> read</span>}
            {tally.narrated > 0 && <span><Icon name="headphones" size={13} /> <b className="mono">{fmt(tally.narrated)}</b> narrated</span>}
          </p>
          <div className="chx-tools">
          {canLocate && (
            <button type="button" className="chx-locate" onClick={() => setLocateNonce(n => n + 1)}>
              <span className="chx-locate-dot" aria-hidden="true" />
              You're on Ch. {currentNumber}
            </button>
          )}
          <form className="chx-jump" onSubmit={doJump}>
            <label className="chx-jump-field">
              <span aria-hidden="true">Go to</span>
              <input className="input" value={jump} onChange={e => { setJump(e.target.value); setJumpMiss(null); }}
                     placeholder="#" inputMode="decimal" aria-label="Jump to chapter number"
                     aria-describedby={jumpMiss ? "chx-jump-miss" : undefined} aria-invalid={jumpMiss ? true : undefined} />
            </label>
            <Button variant="ghost" size="sm" type="submit" disabled={!jump.trim()} iconRight="arrowRight">Jump</Button>
            {jumpMiss && <span id="chx-jump-miss" className="chx-jump-miss" role="status">No chapter {jumpMiss} in this book.</span>}
          </form>
          </div>
        </div>
      )}

      {isLoading ? (
        <TocSkeleton />
      ) : isError ? (
        <EmptyState icon="alert" title="Chapters couldn't load" body="The table of contents didn't arrive. Your place in the book is safe."
          primaryAction={<Button variant="primary" icon="refresh" onClick={() => refetch()}>Try again</Button>} />
      ) : !hasToc ? (
        <EmptyState icon="book" title="No chapters yet"
          body={novel.can_edit ? "Scrape the source from the Manage tab to fetch chapters." : "The owner hasn't added chapters yet."}
          primaryAction={novel.can_edit ? <Button variant="primary" icon="sliders" onClick={() => navigate(`/n/${novelId}/manage`)}>Open Manage</Button> : null} />
      ) : filtered.length === 0 ? (
        <EmptyState icon="search" title="No matching chapters" body="Try a number or part of a title."
          primaryAction={<Button variant="ghost" icon="x" onClick={() => setQ("")}>Clear search</Button>} />
      ) : (
        <div className="card toc chx-toc">
          <VolumeTOC
            toc={filtered}
            currentNumber={currentNumber}
            maxRead={maxRead}
            sortDesc={sortDesc}
            scrollToCurrent={!q}
            onOpen={(n) => navigate(`/n/${novelId}/read/${n}`)}
            audioCoverage={audioCoverage}
            voices={(voicesData && voicesData.voices) || []}
            preferredVoice={readTtsPrefs(user).voice}
            locateNonce={locateNonce}
          />
        </div>
      )}
    </div>
  );
}
