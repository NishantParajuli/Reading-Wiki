/* ============================================================
   Public profile — a moonlit hero (glowing orb, name in display type,
   bio), count-up figures from the real stats, and shelves of books with
   tilting jackets. The room takes the colour of what they're reading now.
   ============================================================ */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { identityApi } from "./api.js";
import { ProfileHero, ProfileSkeleton, Shelf } from "./ProfileParts.jsx";
import { Button, EmptyState } from "../../components/ui.jsx";
import { useBookAtmosphere } from "../../atmosphere/store.js";
import { useTitle } from "../../lib/hooks.js";

export function Profile() {
  const { username } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useTitle(data ? `@${data.username}` : "Profile");

  useEffect(() => {
    let cancel = false;
    setData(null); setErr(null);
    identityApi.profile(username)
      .then(d => { if (!cancel) setData(d); })
      .catch(e => { if (!cancel) setErr(e.message || "Couldn't load this profile."); });
    return () => { cancel = true; };
  }, [username, attempt]);

  const reading = (data && data.currently_reading) || [];
  useBookAtmosphere(reading[0] || null);

  if (err) {
    return (
      <div className="page page-enter">
        <EmptyState icon="user" title="Profile unavailable" body={err}
          primaryAction={<Button variant="primary" icon="refresh" onClick={() => setAttempt(a => a + 1)}>Try again</Button>}
          secondaryAction={<Button variant="ghost" icon="home" onClick={() => navigate("/")}>Go home</Button>} />
      </div>
    );
  }
  if (data == null) return <div className="page"><ProfileSkeleton /></div>;

  const finished = data.recently_finished || [];
  const published = data.published || [];
  const empty = reading.length === 0 && finished.length === 0 && published.length === 0;

  return (
    <div className="page page-enter">
      <div className="pf-page">
        <ProfileHero data={data} feature={reading[0] || null}
                     onEdit={() => navigate("/account")} onAppearance={() => navigate("/account/appearance")} />
        {empty ? (
          <EmptyState icon="book" title="No public activity yet"
            body="Reading activity on shared novels shows up here."
            primaryAction={data.is_self
              ? <Button variant="primary" icon="compass" onClick={() => navigate("/discover")}>Find something to read</Button>
              : <Button variant="ghost" icon="compass" onClick={() => navigate("/discover")}>Browse Discover</Button>} />
        ) : (
          <>
            <Shelf id="pf-reading" eyebrow="On the nightstand" title="Currently reading" items={reading} kind="reading" />
            <Shelf id="pf-finished" eyebrow="Closed covers" title="Recently finished" items={finished} kind="finished" />
            <Shelf id="pf-published" eyebrow={data.is_self ? "Shared by you" : "Shared"}
                   title={data.is_self ? "Published by you" : "Published"} items={published} kind="published" />
          </>
        )}
      </div>
    </div>
  );
}
