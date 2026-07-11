/* Public profile (§6.11) — hero card, stat tiles, cover rails for activity. */
import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { API } from "../lib/api.js";
import { useAuth } from "../App.jsx";
import { Button, Chip, Cover, EmptyState, Loading, ProgressBar, StatTile, UserAvatar } from "../components/ui.jsx";
import { useTitle } from "../lib/hooks.js";
import { fmtChapter } from "../lib/utils.js";

function MiniNovelRail({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <section style={{ marginTop: 26 }}>
      <h2 className="section-title">{title}</h2>
      <div className="rail mini-rail">
        {items.map(n => {
          const pct = (n.max_chapter && n.last_chapter != null)
            ? Math.round(Math.min(100, (n.last_chapter / n.max_chapter) * 100)) : null;
          return (
            <Link key={n.id} className="rail-card" to={`/n/${n.id}`} title={n.title}>
              <Cover src={n.cover_url} title={n.title} />
              <span className="rail-title">{n.title}</span>
              {pct != null && <ProgressBar size="xs" value={pct} />}
              <span className="rail-sub">
                {n.last_chapter != null ? `Ch. ${fmtChapter(n.last_chapter)}` : n.chapter_count != null ? `${n.chapter_count} ch.` : ""}
              </span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

export function Profile() {
  const { username } = useParams();
  const { user: currentUser } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useTitle(data ? `@${data.username}` : "Profile");

  useEffect(() => {
    setData(null); setErr(null);
    API.profile(username).then(setData).catch(e => setErr(e.message || "Couldn't load this profile."));
  }, [username]);

  if (err) {
    return (
      <div className="page page-enter">
        <EmptyState icon="user" title="Profile unavailable" body={err} />
      </div>
    );
  }
  if (data == null) return <div className="page"><Loading label="Loading profile…" /></div>;

  const joined = data.created_at ? new Date(data.created_at).toLocaleDateString(undefined, { year: "numeric", month: "long" }) : null;
  const s = data.stats || {};
  const empty = (data.currently_reading || []).length === 0
    && (data.recently_finished || []).length === 0
    && (data.published || []).length === 0;

  return (
    <div className="page page-enter">
      <div className="profile-head card">
        <UserAvatar url={data.avatar_url} name={data.display_name} size={84} />
        <div className="profile-head-body">
          <div className="row wrap" style={{ gap: 10 }}>
            <h1 className="serif" style={{ margin: 0, fontSize: "var(--text-2xl)" }}>{data.display_name}</h1>
            {data.role === "admin" && <Chip tone="accent">Admin</Chip>}
          </div>
          <div className="muted">@{data.username}{joined ? ` · joined ${joined}` : ""}</div>
          {data.bio && <p style={{ color: "var(--ink-2)", lineHeight: 1.55, maxWidth: "60ch", marginTop: 8, marginBottom: 0 }}>{data.bio}</p>}
          {data.is_self && (
            <div className="row" style={{ gap: 8, marginTop: 12 }}>
              <Button variant="ghost" size="sm" icon="gear" onClick={() => navigate("/account")}>Account & settings</Button>
            </div>
          )}
        </div>
      </div>

      <div className="profile-stats">
        <StatTile value={s.library_count || 0} label="in library" />
        <StatTile value={s.reading_count || 0} label="reading" />
        <StatTile value={s.completed_count || 0} label="completed" />
        <StatTile value={s.chapters_read || 0} label="chapters read" />
      </div>

      {empty ? (
        <div style={{ marginTop: 22 }}>
          <EmptyState icon="book" title="No public activity yet" body="Reading activity on shared novels shows up here." />
        </div>
      ) : (
        <>
          <MiniNovelRail title="Currently reading" items={data.currently_reading} />
          <MiniNovelRail title="Recently finished" items={data.recently_finished} />
          <MiniNovelRail title={data.is_self ? "Published by you" : "Published"} items={data.published} />
        </>
      )}
    </div>
  );
}
