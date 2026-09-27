import React, { useEffect, useState } from "react";

import { acquisitionApi } from "./api.js";
import { Button, Chip, Loading } from "../../components/ui.jsx";

function displayDate(value) {
  const date = new Date(value);
  return value && !Number.isNaN(date.getTime()) ? date.toLocaleString() : "Session cookie (no fixed date)";
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

  return (
    <section className="card acct-card source-account" aria-labelledby="novelpia-title">
      <div className="source-account-heading">
        <h2 id="novelpia-title">Novelpia Global</h2>
        {status && <Chip tone={status.usable ? "accent" : "neutral"}>
          {!status.configured ? "No cookies saved" : status.usable ? "Cookies saved" : "Update needed"}
        </Chip>}
      </div>
      <p className="muted source-account-copy">Use your Novelpia account to import chapters you can access. Saved cookies belong to your Tideglass account.</p>
      {loading ? <Loading label="Loading cookie status…" /> : (
        <>
          {loadError && <div>
            <p className="acct-err" role="alert">{loadError}</p>
            <Button variant="ghost" onClick={load} disabled={!!busy}>Try again</Button>
          </div>}
          {status?.configured && (
            <div className="source-account-status">
              <p className="source-account-copy">{status.usable
                ? "Login cookies are stored. Novelpia checks your session and chapter access when an import runs."
                : "Your saved login cookies are missing or expired. Sign in to Novelpia and replace them with a fresh export."}</p>
              {status.updated_at && <p className="muted source-account-copy">Updated {displayDate(status.updated_at)}</p>}
              {!!status.cookies?.length && <details>
                <summary>Saved cookie expiry dates</summary>
                <dl className="source-cookie-dates">
                  {status.cookies.map(cookie => <div key={`${cookie.domain}:${cookie.name}`}>
                    <dt>{cookie.name}</dt><dd>{displayDate(cookie.expires_at)}</dd>
                  </div>)}
                </dl>
                <p className="muted source-account-copy">These are storage deadlines. Novelpia may end your login earlier.</p>
              </details>}
            </div>
          )}
          <details className="source-cookie-help">
            <summary>How to get your cookies</summary>
            <ol>
              <li>Sign in at <a href="https://global.novelpia.com" target="_blank" rel="noreferrer">Novelpia Global</a> in your browser.</li>
              <li>Use your cookie extension to export this site's cookies as JSON. EditThisCookie exports are supported.</li>
              <li>Paste the export below and save. Repeat this when your login expires.</li>
            </ol>
          </details>
          <form onSubmit={save} className="source-cookie-form">
            <label className="field" htmlFor="novelpia-cookies">
              <span>{status?.configured ? "Replace cookies" : "Cookie export"}</span>
              <textarea id="novelpia-cookies" value={cookies} onChange={event => {
                setCookies(event.target.value); setError(""); setMessage("");
              }} rows={6} autoComplete="off" autoCapitalize="off" spellCheck={false}
                disabled={!!busy} maxLength={131072} placeholder="Paste your cookie export JSON here"
                aria-invalid={!!error} aria-describedby={`novelpia-cookie-help${error ? " novelpia-cookie-error" : ""}`} />
            </label>
            <p id="novelpia-cookie-help" className="muted source-account-copy">Only login cookies are kept. Saved values are never shown here, and this field clears after saving.</p>
            {error && <p id="novelpia-cookie-error" className="acct-err" role="alert">{error}</p>}
            {message && <p className="acct-ok" role="status">{message}</p>}
            <div className="row wrap">
              <Button type="submit" loading={busy === "save"} disabled={!!busy || !cookies.trim()}>
                {busy === "save" ? "Saving cookies…" : status?.configured ? "Replace cookies" : "Save cookies"}
              </Button>
              {(status?.configured || loadError) && <Button variant="ghost" loading={busy === "remove"} disabled={!!busy} onClick={remove}>
                {busy === "remove" ? "Removing…" : "Remove saved cookies"}
              </Button>}
            </div>
          </form>
          <p className="muted source-account-copy">Your Novelpia plan and ad requirements still apply.</p>
        </>
      )}
    </section>
  );
}
