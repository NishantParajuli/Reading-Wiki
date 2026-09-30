/* ============================================================
   Novel → Manage (owner/admin): the book's control room.
   A section ledger — each row a numbered title and purpose on the left,
   its cards on the right:
     Inbox (only when something waits) · Content · Processing ·
     Illustrations · Sharing & details · Activity & health · Glossary ·
     Danger zone.
   Cards own their state and API calls (ManageSections / ManagePanels);
   this screen composes them and keeps the inbox counts fresh.
   ============================================================ */
import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { catalogApi } from "../../modules/catalog/api.js";
import { readingApi } from "../../modules/reading/api.js";
import { useNovel } from "../../layouts/NovelLayout.jsx";
import { NovelHeader } from "./NovelHeader.jsx";
import { useArrival } from "./NovelHeroParts.jsx";
import { EmptyState } from "../../components/ui.jsx";
import { useVoicesQuery } from "../../modules/narration/queries.js";
import { useChaptersQuery } from "../../modules/reading/queries.js";
import { useTitle } from "../../lib/hooks.js";
import {
  ContributionsInbox, GlossaryCard, HealthPanel,
  MetadataCard, NovelJobs, TagSuggestionsInbox,
} from "../../modules/catalog/ManagePanels.jsx";
import { DangerCard, PipelineCard, SharingCard, SourcesCard } from "./ManageSections.jsx";
import { ManageSection } from "./ManageKit.jsx";

import { IllustrationRangePanel } from "../codex/index.js";

/* Pending contributions + tag suggestions, shared with the capsule badge. */
function useInboxes(novelId, enabled) {
  const qc = useQueryClient();
  const contributions = useQuery({
    queryKey: ["contributions", Number(novelId)],
    queryFn: () => readingApi.contributions(novelId),
    enabled, staleTime: 15_000,
  });
  const suggestions = useQuery({
    queryKey: ["tag-suggestions", Number(novelId)],
    queryFn: () => catalogApi.tagSuggestions(novelId),
    enabled, staleTime: 15_000,
  });
  const refresh = (query) => () => {
    query.refetch();
    qc.invalidateQueries({ queryKey: ["manage-inbox", novelId] });
  };
  return {
    contributions: contributions.data || [],
    suggestions: suggestions.data || [],
    reloadContributions: refresh(contributions),
    reloadSuggestions: refresh(suggestions),
  };
}

export function Manage() {
  const { novel, novelId, reloadNovel } = useNovel();
  const arrival = useArrival();
  const { refetch: refetchToc } = useChaptersQuery(novelId);
  const { data: voicesData } = useVoicesQuery();
  const inbox = useInboxes(novelId, !!novel.can_edit);
  useTitle("Manage", novel.title);

  const pageCls = "page nv-page mg-page" + (arrival === "direct" ? " page-enter" : "");
  if (!novel.can_edit) {
    return (
      <div className={pageCls}>
        <NovelHeader compact />
        <EmptyState icon="lock" title="Owners only" body="You don't have permission to manage this novel." />
      </div>
    );
  }

  const pending = inbox.contributions.length + inbox.suggestions.length;
  const sections = [
    pending > 0 && {
      id: "inbox", title: "Inbox", desc: `${pending} ${pending === 1 ? "request waits" : "requests wait"} for your review.`, tone: "accent",
      body: (
        <>
          <ContributionsInbox novelId={novelId} items={inbox.contributions} reload={inbox.reloadContributions} reloadNovel={reloadNovel} />
          <TagSuggestionsInbox novelId={novelId} items={inbox.suggestions} reload={inbox.reloadSuggestions} reloadNovel={reloadNovel} />
        </>
      ),
    },
    {
      id: "content", title: "Content", desc: "Where the text comes from, and how its chapters line up.",
      body: <SourcesCard novel={novel} novelId={novelId} reloadNovel={reloadNovel} refetchToc={refetchToc} />,
    },
    {
      id: "processing", title: "Processing", desc: "Fetch new chapters, translate raws and build the spoiler-safe Codex.",
      body: <PipelineCard novel={novel} novelId={novelId} reloadNovel={reloadNovel} refetchToc={refetchToc} />,
    },
    {
      id: "illustrations", title: "Illustrations", desc: "Paint scenes ahead of your reading, chapter by chapter.",
      body: <div className="mg-spot" data-spotlight=""><IllustrationRangePanel key={novelId} novelId={novelId} novel={novel} /></div>,
    },
    {
      id: "sharing", title: "Sharing & details", desc: "Who can read it, how edits arrive, and how it's presented.",
      body: (
        <div className="mg-pair">
          <SharingCard novel={novel} novelId={novelId} reloadNovel={reloadNovel} />
          <MetadataCard key={novel.id + ":" + novel.title} novel={novel} reloadNovel={reloadNovel} />
        </div>
      ),
    },
    {
      id: "activity", title: "Activity & health", desc: "Background work for this book, and anything that needs attention.",
      body: (
        <>
          <NovelJobs novelId={novelId} />
          <HealthPanel novelId={novelId} ttsVoices={(voicesData && voicesData.voices) || []} />
        </>
      ),
    },
    {
      id: "glossary", title: "Glossary", desc: "Names and terms the translator must always render the same way.",
      body: <GlossaryCard novelId={novelId} />,
    },
    {
      id: "danger", title: "Danger zone", desc: "Irreversible actions.", tone: "danger",
      body: <DangerCard novel={novel} novelId={novelId} />,
    },
  ].filter(Boolean);

  return (
    <div className={pageCls}>
      <NovelHeader compact />

      <nav className="mg-index" aria-label="Manage sections">
        {sections.map((s, i) => (
          <a key={s.id} href={`#manage-${s.id}`} className={"mg-index-link" + (s.tone ? ` is-${s.tone}` : "")}
             style={{ "--i": i }}
             onClick={(e) => {
               const el = document.getElementById(`manage-${s.id}`);
               if (!el) return;
               e.preventDefault();
               el.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
               const heading = el.querySelector("h2");
               if (heading) { heading.setAttribute("tabindex", "-1"); heading.focus({ preventScroll: true }); }
             }}>
            <span className="mono">{String(i + 1).padStart(2, "0")}</span>
            {s.title}
            {s.id === "inbox" && <span className="mg-index-count">{pending}</span>}
          </a>
        ))}
      </nav>

      <div className="mg-ledger">
        {sections.map((s, i) => (
          <ManageSection key={s.id} id={s.id} index={i + 1} title={s.title} desc={s.desc} tone={s.tone}>
            {s.body}
          </ManageSection>
        ))}
      </div>
    </div>
  );
}
