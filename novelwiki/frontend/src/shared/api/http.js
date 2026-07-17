const API_BASE = "/api";
const CSRF_COOKIE = "tg_csrf";
const CSRF_HEADER = "X-Tideglass-CSRF";
const REQUEST_HEADER = "X-Tideglass-Request";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

let onUnauthorized = null;

export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

function readCookie(name) {
  const parts = (document.cookie || "").split(";").map((part) => part.trim());
  const prefix = `${name}=`;
  for (const part of parts) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length));
  }
  return "";
}

export function mutationHeaders(headers = {}) {
  headers[REQUEST_HEADER] = "1";
  const csrf = readCookie(CSRF_COOKIE);
  if (csrf) headers[CSRF_HEADER] = csrf;
  return headers;
}

async function parseError(res) {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const payload = await res.json();
    if (payload?.detail) detail = payload.detail;
  } catch (error) {
    // Non-JSON error bodies retain the HTTP status text.
  }
  const error = new Error(detail);
  error.status = res.status;
  return error;
}

async function parseJSONStream(res) {
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result;

  function consume(line) {
    if (!line.trim()) return;
    let event;
    try {
      event = JSON.parse(line);
    } catch (error) {
      throw new Error("The recap service returned an invalid streamed response.");
    }
    if (event.event === "result") result = event.data;
    if (event.event === "error") {
      const streamError = new Error(event.detail || "Recap generation failed.");
      streamError.status = event.status;
      throw streamError;
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      lines.forEach(consume);
      if (done) break;
    }
    consume(buffer);
  } finally {
    reader.releaseLock();
  }
  if (result !== undefined) return result;
  throw new Error("The recap connection ended before a result was returned. Please try again.");
}

export async function req(method, url, body) {
  const opts = { method, credentials: "include", headers: { Accept: "application/json" } };
  if (!SAFE_METHODS.has(method.toUpperCase())) mutationHeaders(opts.headers);
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body || {});
  }
  const res = await fetch(url, opts);
  if (!res.ok) {
    if (res.status === 401 && !url.includes("/auth/") && onUnauthorized) {
      try { onUnauthorized(); } catch (error) { /* re-gating is best-effort */ }
    }
    throw await parseError(res);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const getJSON = (url) => req("GET", url);
export const postJSON = (url, body) => req("POST", url, body || {});
export const putJSON = (url, body) => req("PUT", url, body);
export const delJSON = (url) => req("DELETE", url);

export async function postJSONStream(url, body) {
  const headers = mutationHeaders({
    Accept: "application/x-ndjson",
    "Content-Type": "application/json",
  });
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers,
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    if (res.status === 401 && !url.includes("/auth/") && onUnauthorized) {
      try { onUnauthorized(); } catch (error) { /* re-gating is best-effort */ }
    }
    throw await parseError(res);
  }
  const contentType = res.headers?.get?.("content-type") || "";
  if (!contentType.includes("application/x-ndjson") || !res.body?.getReader) {
    return res.json();
  }
  return parseJSONStream(res);
}

export async function postMultipart(url, formData) {
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: mutationHeaders(),
    body: formData,
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export { API_BASE };
