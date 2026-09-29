/** A disposable browser that completes the site's ordinary ad UI. */
const SITE = 'https://global.novelpia.com';
const API = 'https://api-global.novelpia.com';
const AUTH_NAMES = new Set(['TKEY', 'LOGINKEY', 'USERKEY']);
const COOKIE_DOMAINS = new Set(['.novelpia.com', 'novelpia.com', 'global.novelpia.com', 'api-global.novelpia.com']);

export function validateUnlock(value, maxSeconds = 75, now = Date.now() / 1000) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || !Number.isSafeInteger(value.episode_id) || value.episode_id <= 0
      || !Array.isArray(value.cookies) || value.cookies.length > 12) throw new Error('invalid');
  const seconds = value.timeout_seconds ?? maxSeconds;
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 1 || seconds > maxSeconds) throw new Error('invalid');
  const cookies = [];
  const seen = new Set();
  for (const cookie of value.cookies) {
    if (!cookie || !AUTH_NAMES.has(cookie.name) || !COOKIE_DOMAINS.has(cookie.domain)
        || cookie.path !== '/' || typeof cookie.value !== 'string' || !cookie.value
        || cookie.value.length > 8192 || /[\x00-\x20\x7f;,]/.test(cookie.value)) throw new Error('invalid');
    const key = `${cookie.domain}:${cookie.name}`;
    if (seen.has(key)) throw new Error('invalid');
    seen.add(key);
    const expires = cookie.expires ?? undefined;
    if (expires !== undefined && (typeof expires !== 'number' || !Number.isFinite(expires))) throw new Error('invalid');
    if (expires !== undefined && expires <= now) {
      if (cookie.name === 'TKEY') throw new Error('invalid');
      continue;
    }
    cookies.push({name: cookie.name, value: cookie.value, domain: cookie.domain, path: '/',
      secure: true, httpOnly: cookie.name === 'TKEY', sameSite: 'Lax', ...(expires === undefined ? {} : {expires})});
  }
  if (!cookies.some(cookie => cookie.name === 'TKEY')) throw new Error('invalid');
  return {episodeId: value.episode_id, cookies, timeoutMs: Math.floor(seconds * 1000)};
}

export function allowedViewer(url, episodeId) {
  try {
    const parsed = new URL(url);
    return parsed.origin === SITE && parsed.pathname.replace(/\/$/, '') === `/viewer/${episodeId}`
      && !parsed.username && !parsed.password;
  } catch { return false; }
}

/** Only inspect expected API responses; never retain or return chapter contents. */
export async function responseOutcome(response) {
  let url;
  try { url = new URL(response.url()); } catch { return null; }
  if (url.origin !== API) return null;
  if (url.pathname === '/v1/login/refresh' && response.status() === 401) return 'login_required';
  if (!['/v1/novel/episode/content', '/v1/ad/reward/grant'].includes(url.pathname)
      || response.status() < 200 || response.status() >= 300) return null;
  try {
    const payload = await response.json();
    if (String(payload?.code) !== '0000') return null;
    if (url.pathname === '/v1/ad/reward/grant') return 'completed';
    const data = payload?.result?.data;
    if (data && ['epi_content', 'epi_content2', 'epi_content3', 'epi_content4']
      .some(key => typeof data[key] === 'string' && data[key].trim())) return 'completed';
  } catch { /* Closing or malformed responses are not successful unlocks. */ }
  return null;
}

export function browserEnvironment(env = process.env) {
  // In particular, do not hand sidecar tokens or application secrets to pages' process.
  return Object.fromEntries(['PATH', 'HOME', 'TMPDIR', 'LANG', 'TZ', 'PLAYWRIGHT_BROWSERS_PATH']
    .filter(key => typeof env[key] === 'string').map(key => [key, env[key]]));
}

export async function unlockChapter({episodeId, cookies, timeoutMs}, {chromium, proxy, signal}) {
  let browser;
  let finished = false;
  let settle;
  const outcome = new Promise(resolve => { settle = status => {
    if (!finished) { finished = true; resolve(status); }
  }; });
  const abort = () => { settle('unavailable'); if (browser) void browser.close().catch(() => {}); };
  signal?.addEventListener('abort', abort, {once: true});
  const timer = setTimeout(() => {
    settle('timeout');
    if (browser) void browser.close().catch(() => {});
  }, timeoutMs);
  const run = async () => {
    if (signal?.aborted) { settle('unavailable'); return; }
    browser = await chromium.launch({
      headless: true, chromiumSandbox: true, timeout: Math.min(timeoutMs, 20000),
      proxy: {server: proxy, bypass: '<-loopback>'},
      env: browserEnvironment(),
      args: ['--disable-quic', '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'],
    });
    if (finished) { await browser.close(); return; }
    const context = await browser.newContext({acceptDownloads: false, serviceWorkers: 'block',
      locale: 'en-US', viewport: {width: 1280, height: 900}});
    await context.addCookies(cookies);
    const page = await context.newPage();
    context.on('page', popup => { if (popup !== page) void popup.close().catch(() => {}); });
    await context.route('**/*', async route => {
      const request = route.request();
      let parsed;
      try { parsed = new URL(request.url()); } catch { await route.abort(); return; }
      if (parsed.protocol !== 'https:') { await route.abort(); return; }
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()
          && !allowedViewer(request.url(), episodeId)) {
        if (parsed.origin === SITE && /login|sign[-_]?in/i.test(parsed.pathname)) settle('login_required');
        await route.abort(); return;
      }
      await route.continue();
    });
    page.on('response', response => { void responseOutcome(response).then(status => {
      if (status) settle(status);
    }); });
    page.on('download', download => { void download.cancel().catch(() => {}); });
    page.on('dialog', dialog => { void dialog.dismiss().catch(() => {}); });
    await page.goto(`${SITE}/viewer/${episodeId}`, {waitUntil: 'domcontentloaded', timeout: Math.min(timeoutMs, 30000)});
    // No timer edits, ad API calls, or ad clicks: Playwright waits until the
    // website's ordinary Continue button is visible and enabled.
    while (!finished) {
      const button = page.getByRole('button', {name: 'Continue', exact: true});
      if (await button.count() === 1 && await button.isVisible() && await button.isEnabled()) {
        await button.click({timeout: 3000, noWaitAfter: true});
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 250));
    }
  };
  // Track launch too: if cancellation wins before Chromium starts, run() closes
  // that late browser before we release the service's only active slot.
  const running = run().catch(() => settle(finished ? 'timeout' : 'unavailable'));
  try {
    const status = await outcome;
    if (browser) await browser.close().catch(() => {});
    await running;
    return status;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
    if (browser) await browser.close().catch(() => {});
  }
}
