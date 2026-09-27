import http from 'node:http';
import {timingSafeEqual} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {validateUnlock, unlockChapter} from './browser.mjs';

const BODY_LIMIT = 65536;
export function configFromEnv(env = process.env) {
  const token = env.NOVELPIA_BROWSER_TOKEN || env.SIDECAR_AUTH_TOKEN;
  if (typeof token !== 'string' || token.length < 24 || token.length > 4096) throw new Error('A sidecar authentication token of at least 24 characters is required.');
  let proxy;
  try { proxy = new URL(env.NOVELPIA_BROWSER_PROXY); } catch { throw new Error('NOVELPIA_BROWSER_PROXY is required.'); }
  if (proxy.protocol !== 'http:' || proxy.username || proxy.password || proxy.pathname !== '/' || proxy.search || proxy.hash) throw new Error('Invalid browser egress proxy.');
  const maxSeconds = Number(env.NOVELPIA_BROWSER_TIMEOUT_SECONDS || 75);
  const port = Number(env.PORT || 8079);
  if (!Number.isInteger(maxSeconds) || maxSeconds < 1 || maxSeconds > 90
      || !Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid sidecar limits.');
  return {token, proxy: proxy.origin, maxSeconds, port};
}
function authorized(value, token) {
  if (typeof value !== 'string' || value.length > 4096) return false;
  const supplied = Buffer.from(value);
  const expected = Buffer.from(token);
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}
function respond(res, code, status) {
  if (res.destroyed || res.writableEnded) return;
  res.writeHead(code, {'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'Connection': 'close'});
  res.end(JSON.stringify({status}));
}
async function readBody(req) {
  let size = 0;
  const chunks = [];
  if (Number(req.headers['content-length']) > BODY_LIMIT) throw new Error('too_large');
  for await (const chunk of req) {
    size += chunk.length;
    if (size > BODY_LIMIT) throw new Error('too_large');
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
export function createServer({token, proxy, maxSeconds = 75, chromium, unlock = unlockChapter, hardStop = () => process.exit(1), cleanupGraceMs = 5000}) {
  let active = null;
  const server = http.createServer(async (req, res) => {
    if (req.method === 'GET' && req.url === '/health') { respond(res, 200, 'ok'); return; }
    if (!authorized(req.headers['x-tideglass-sidecar-token'], token)) { respond(res, 401, 'unauthorized'); return; }
    if (req.method !== 'POST' || req.url !== '/unlock') { respond(res, 404, 'not_found'); return; }
    if (active) { respond(res, 429, 'busy'); return; }
    if (!(req.headers['content-type'] || '').toLowerCase().startsWith('application/json')) { respond(res, 400, 'invalid'); return; }
    const controller = new AbortController();
    active = controller;
    let cleanupWatchdog;
    const watchCleanup = () => { cleanupWatchdog = setTimeout(hardStop, cleanupGraceMs); };
    controller.signal.addEventListener('abort', watchCleanup, {once: true});
    const disconnect = () => { if (!res.writableEnded) controller.abort(); };
    res.once('close', disconnect);
    // Includes a client that trickles the body without ever starting Chromium.
    const expire = () => { respond(res, 504, 'timeout'); controller.abort(); req.destroy(); };
    let deadline = setTimeout(expire, (maxSeconds + 2) * 1000);
    try {
      let request;
      try { request = validateUnlock(await readBody(req), maxSeconds); }
      catch (error) { respond(res, error.message === 'too_large' ? 413 : 400, 'invalid'); return; }
      if (controller.signal.aborted) return;
      clearTimeout(deadline);
      deadline = setTimeout(expire, request.timeoutMs + 1000);
      let status;
      try { status = await unlock(request, {chromium, proxy, signal: controller.signal}); }
      catch { status = 'unavailable'; }
      if (!['completed', 'timeout', 'login_required', 'unavailable'].includes(status)) status = 'unavailable';
      respond(res, status === 'unavailable' ? 503 : status === 'timeout' ? 504 : 200, status);
    } finally {
      clearTimeout(deadline);
      clearTimeout(cleanupWatchdog);
      controller.signal.removeEventListener('abort', watchCleanup);
      res.removeListener('close', disconnect);
      active = null;
    }
  });
  server.headersTimeout = 10000;
  server.requestTimeout = (maxSeconds + 3) * 1000;
  server.keepAliveTimeout = 1000;
  server.on('clientError', (_error, socket) => { socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n'); });
  server.abortActive = () => active?.abort();
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let config;
  try { config = configFromEnv(); } catch (error) { console.error(error.message); process.exit(1); }
  const {chromium} = await import('playwright');
  const server = createServer({...config, chromium});
  server.listen(config.port, '0.0.0.0', () => { console.log('Novelpia browser service ready.'); });
  for (const event of ['SIGTERM', 'SIGINT']) process.once(event, () => {
    server.abortActive();
    server.close();
    setTimeout(() => process.exit(0), 22000).unref();
  });
}
