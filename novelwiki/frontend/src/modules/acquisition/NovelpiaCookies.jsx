/* Novelpia Global source account: login cookies for imports.
   Saved values never come back to the browser — only their names and
   storage deadlines are shown. */
import React, { useEffect, useState } from "react";

import { acquisitionApi } from "./api.js";
import { Icon } from "../../components/Icon.jsx";
import { Button, Chip, Loading } from "../../components/ui.jsx";

function displayDate(value) {
  const date = new Date(value);
  return value && !Number.isNaN(date.getTime()) ? date.toLocaleString() : "Session cookie (no fixed date)";
}

function Summary({ icon, children }) {
  return (
    <summary>
      <Icon name={icon} size={15} />
      <span>{children}</span>
      <Icon name="chevronDown" size={15} className="npc-chev" />
    </summary>
  );
}

export function NovelpiaCookies() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [cookies, setCookies] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function load() {
    setLoading(true);
    setLoadError("");
    try { setStatus(await acquisitionApi.novelpiaCookies()); }
    catch (err) {
      setLoadError(err.status === 422
        ? "Your saved cookies cannot be opened. Replace them with a fresh export, or remove them below."
        : "Couldn't load your Novelpia cookie status. Try again, or replace or remove the saved cookies below.");
    }
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  async function save(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    let parsed;
    try {
      parsed = JSON.parse(cookies);
      if (!Array.isArray(parsed) || !parsed.length) throw new Error();
    } catch {
      setError("Paste the full JSON array from your cookie export, including the opening and closing square brackets.");
      return;
    }
    setBusy("save");
    try {
      setStatus(await acquisitionApi.updateNovelpiaCookies(parsed));
      setLoadError("");
      setCookies("");
      setMessage("Cookies saved. Your next Novelpia import will use them.");
    } catch (err) {
      setError(err.message || "Couldn't save cookies. Check the export and try again.");
    } finally { setBusy(""); }
  }

  async function remove() {
    setBusy("remove");
    setError("");
    setMessage("");
    try {
      setStatus(await acquisitionApi.deleteNovelpiaCookies());
      setLoadError("");
      setCookies("");
      setMessage("Saved Novelpia cookies removed.");
    } catch {
      setError("Couldn't remove cookies. Try again.");
    } finally { setBusy(""); }
  }

  const chipTone = !status ? "neutral" : !status.configured ? "neutral" : status.usable ? "ok" : "warn";
  return (
    <section className="card npc" aria-labelledby="novelpia-title">
      <div className="npc-head" style={{ "--i": 0 }}>
        <span className="npc-mark" aria-hidden="true">N</span>
        <div className="npc-headings">
          <p className="npc-eyebrow">Source account</p>
          <h2 id="novelpia-title" className="npc-title">Novelpia Global</h2>
        </div>
        {status && <Chip tone={chipTone} className="npc-chip">
          <span className="chip-dot" aria-hidden="true" />
          {!status.configured ? "No cookies saved" : status.usable ? "Cookies saved" : "Update needed"}
        </Chip>}
      </div>
      <p className="npc-lede" style={{ "--i": 1 }}>Use your Novelpia account to import chapters you can access. Saved cookies belong to your Tideglass account.</p>
      {loading ? <Loading label="Loading cookie status…" /> : (
        <>
          {loadError && <div className="npc-alert" style={{ "--i": 2 }}>
            <p className="acct-err" role="alert">{loadError}</p>
            <Button variant="ghost" size="sm" icon="refresh" onClick={load} disabled={!!busy}>Try again</Button>
          </div>}
          {status?.configured && (
            <div className={"npc-status" + (status.usable ? "" : " is-warn")} style={{ "--i": 2 }}>
              <span className="npc-status-icon" aria-hidden="true"><Icon name={status.usable ? "shield" : "alert"} size={16} /></span>
              <div>
                <p>{status.usable
                  ? "Login cookies are stored. Novelpia checks your session and chapter access when an import runs."
                  : "Your saved login cookies are missing or expired. Sign in to Novelpia and replace them with a fresh export."}</p>
                {status.updated_at && <p className="npc-updated">Updated {displayDate(status.updated_at)}</p>}
              </div>
            </div>
          )}
          {status?.configured && !!status.cookies?.length && (
            <details className="npc-details" style={{ "--i": 3 }}>
              <Summary icon="clock">Saved cookie expiry dates</Summary>
              <div className="npc-details-body">
                <dl className="npc-dates">
                  {status.cookies.map(cookie => <div key={`${cookie.domain}:${cookie.name}`}>
                    <dt>{cookie.name}</dt><dd>{displayDate(cookie.expires_at)}</dd>
                  </div>)}
                </dl>
                <p className="npc-small">These are storage deadlines. Novelpia may end your login earlier.</p>
              </div>
            </details>
          )}
          <details className="npc-details npc-help" style={{ "--i": 4 }}>
            <Summary icon="compass">How to get your cookies</Summary>
            <div className="npc-details-body">
              <ol className="npc-steps">
                <li>Sign in at <a href="https://global.novelpia.com" target="_blank" rel="noreferrer">Novelpia Global</a> in your browser.</li>
                <li>Use your cookie extension to export this site's cookies as JSON. EditThisCookie exports are supported.</li>
                <li>Paste the export below and save. Repeat this when your login expires.</li>
              </ol>
            </div>
          </details>
          <form onSubmit={save} className="npc-form" style={{ "--i": 5 }}>
            <label className="npc-label" htmlFor="novelpia-cookies">
              <Icon name="lock" size={14} />{status?.configured ? "Replace cookies" : "Cookie export"}
            </label>
            <div className="npc-secure">
              <textarea id="novelpia-cookies" value={cookies} onChange={event => {
                setCookies(event.target.value); setError(""); setMessage("");
              }} rows={6} autoComplete="off" autoCapitalize="off" spellCheck={false}
                disabled={!!busy} maxLength={131072} placeholder="Paste your cookie export JSON here"
                aria-invalid={!!error} aria-describedby={`novelpia-cookie-help${error ? " novelpia-cookie-error" : ""}`} />
              <span className="npc-secure-tag" aria-hidden="true">JSON</span>
            </div>
            <p id="novelpia-cookie-help" className="npc-hint">Only login cookies are kept. Saved values are never shown here, and this field clears after saving.</p>
            {error && <p id="novelpia-cookie-error" className="acct-err npc-msg" role="alert">{error}</p>}
            {message && <p className="acct-ok npc-msg" role="status">{message}</p>}
            <div className="npc-actions">
              <Button type="submit" loading={busy === "save"} disabled={!!busy || !cookies.trim()}>
                {busy === "save" ? "Saving cookies…" : status?.configured ? "Replace cookies" : "Save cookies"}
              </Button>
              {(status?.configured || loadError) && <Button variant="ghost" className="is-danger" loading={busy === "remove"} disabled={!!busy} onClick={remove}>
                {busy === "remove" ? "Removing…" : "Remove saved cookies"}
              </Button>}
            </div>
          </form>
          <p className="npc-foot" style={{ "--i": 6 }}>
            <Icon name="sparkles" size={14} />
            Imports complete supported ad countdowns automatically when the browser helper is available. If an ad needs your attention, saved chapters are kept and a recovery link is shown.
          </p>
        </>
      )}
    </section>
  );
}
