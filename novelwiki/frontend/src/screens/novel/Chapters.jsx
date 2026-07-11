/* Novel → Chapters tab: searchable, jumpable, virtualized full TOC. */
import React, { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../../App.jsx";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { NovelHeader } from "./NovelHeader.jsx";
import { Icon } from "../../components/Icon.jsx";
import { Button, EmptyState, Loading, SegmentedControl } from "../../components/ui.jsx";
import { VolumeTOC } from "../../features/toc.jsx";
import { readTtsPrefs } from "../../features/narrate.jsx";
import { useAudioCoverageQuery, useVoicesQuery } from "../../modules/narration/queries.js";
import { useChaptersQuery } from "../../modules/reading/queries.js";
import { useTitle } from "../../lib/hooks.js";

export function Chapters() {
  const { novel, novelId } = useNovel();
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: toc, isLoading } = useChaptersQuery(novelId);
  const { data: audioCoverage } = useAudioCoverageQuery(novelId);
  const { data: voicesData } = useVoicesQuery();
  const [q, setQ] = useState("");
  const [jump, setJump] = useState("");
  const [sortDesc, setSortDesc] = useState(false);
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

  function doJump(e) {
    e.preventDefault();
    const n = parseFloat(jump);
    if (!isNaN(n) && (toc || []).some(c => Number(c.number) === n)) {
      navigate(`/n/${novelId}/read/${n}`);
    }
  }

  return (
    <div className="page page-enter">
      <NovelHeader />

      <div className="toc-toolbar">
        <div className="search-box">
          <Icon name="search" size={15} className="muted" />
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search chapters…" aria-label="Search chapters" />
          {q && <button className="icon-btn plain" style={{ width: 24, height: 24 }} aria-label="Clear" onClick={() => setQ("")}><Icon name="x" size={12} /></button>}
        </div>
        <form className="row" style={{ gap: 6 }} onSubmit={doJump}>
          <input className="input" style={{ width: 96 }} value={jump} onChange={e => setJump(e.target.value)}
                 placeholder="Go to #" inputMode="decimal" aria-label="Jump to chapter number" />
          <Button variant="ghost" size="sm" type="submit" disabled={!jump.trim()}>Jump</Button>
        </form>
        <SegmentedControl fit ariaLabel="Sort order" value={sortDesc}
          onChange={setSortDesc}
          options={[{ value: false, label: "1 → n" }, { value: true, label: "n → 1" }]} />
      </div>

      {isLoading ? (
        <Loading label="Loading chapters…" />
      ) : (toc || []).length === 0 ? (
        <EmptyState icon="book" title="No chapters yet"
          body={novel.can_edit ? "Scrape the source from the Manage tab to fetch chapters." : "The owner hasn't added chapters yet."} />
      ) : filtered.length === 0 ? (
        <EmptyState icon="search" title="No matching chapters" body="Try a number or part of a title." />
      ) : (
        <div className="card toc">
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
          />
        </div>
      )}
    </div>
  );
}
