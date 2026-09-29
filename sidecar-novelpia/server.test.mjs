import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {once} from 'node:events';
import {configFromEnv, createServer} from './server.mjs';

const TOKEN = 'test-only-sidecar-token-32-characters';
const body = {episode_id: 610753, cookies: [{name: 'TKEY', value: 'private-test-value', domain: '.novelpia.com', path: '/'}]};
async function serve(t, unlock, extra = {}) {
  const server = createServer({token: TOKEN, proxy: 'http://egress:8899', unlock, ...extra});
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => { server.abortActive(); server.closeAllConnections(); server.close(); });
  return {url: `http://127.0.0.1:${server.address().port}`, server};
}
const post = (url, value = body, token = TOKEN, options = {}) => fetch(`${url}/unlock`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tideglass-Sidecar-Token': token}, body: JSON.stringify(value), ...options});

test('startup refuses missing auth, proxy, and unsafe limits', () => {
  const valid = {NOVELPIA_BROWSER_TOKEN: TOKEN, NOVELPIA_BROWSER_PROXY: 'http://novelpia-egress:8899'};
  assert.equal(configFromEnv(valid).port, 8079);
  assert.equal(configFromEnv({...valid, NOVELPIA_BROWSER_TOKEN: '', SIDECAR_AUTH_TOKEN: TOKEN}).token, TOKEN);
  for (const env of [{}, {...valid, NOVELPIA_BROWSER_TOKEN: ''}, {...valid, NOVELPIA_BROWSER_PROXY: ''},
    {...valid, NOVELPIA_BROWSER_PROXY: 'http://secret:password@egress:8899'}, {...valid, NOVELPIA_BROWSER_TIMEOUT_SECONDS: '91'}]) assert.throws(() => configFromEnv(env));
});
test('only authenticated validated requests launch the browser', async t => {
  let calls = 0;
  const {url} = await serve(t, async () => { calls++; return 'completed'; });
  assert.equal((await fetch(`${url}/health`)).status, 200);
  assert.equal((await post(url, body, 'wrong')).status, 401);
  assert.equal((await post(url, {...body, episode_id: 'https://evil.test'})).status, 400);
  assert.equal((await post(url, {...body, padding: 'x'.repeat(65536)})).status, 413);
  assert.equal(calls, 0);
  const response = await post(url);
  assert.equal(response.status, 200); assert.deepEqual(await response.json(), {status: 'completed'}); assert.equal(calls, 1);
});
test('concurrent requests get busy and disconnect cancels the active job', async t => {
  let signal;
  let entered;
  const started = new Promise(resolve => { entered = resolve; });
  const {url} = await serve(t, async (_request, options) => {
    signal = options.signal; entered();
    await new Promise(resolve => signal.addEventListener('abort', resolve, {once: true}));
    return 'unavailable';
  });
  const controller = new AbortController();
  const first = post(url, body, TOKEN, {signal: controller.signal}).catch(() => null);
  await started;
  // Fully reading a request must not count as disconnecting.
  assert.equal(signal.aborted, false);
  const second = await post(url);
  assert.equal(second.status, 429); assert.deepEqual(await second.json(), {status: 'busy'});
  controller.abort(); await first;
  if (!signal.aborted) await once(signal, 'abort');
  assert.equal(signal.aborted, true);
});
test('errors never return cookies, browser output, or arbitrary statuses', async t => {
  const {url} = await serve(t, async () => { throw new Error(body.cookies[0].value); });
  const response = await post(url);
  assert.equal(response.status, 503); assert.deepEqual(await response.json(), {status: 'unavailable'});
});
test('oversized chunked bodies cannot launch browser', async t => {
  let calls = 0;
  const {url} = await serve(t, async () => { calls++; return 'completed'; });
  await new Promise(resolve => {
    const request = http.request(`${url}/unlock`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tideglass-Sidecar-Token': TOKEN}}, response => {
      assert.equal(response.statusCode, 413); response.resume(); response.on('end', resolve);
    });
    request.on('error', resolve);
    request.write('x'.repeat(32768)); request.end('x'.repeat(32769));
  });
  assert.equal(calls, 0);
});

test('hung cleanup triggers a hard-stop watchdog without releasing the occupied slot', async t => {
  let entered, stopped, finish;
  const started = new Promise(resolve => { entered = resolve; });
  const hardStopped = new Promise(resolve => { stopped = resolve; });
  const {url} = await serve(t, async () => {
    entered();
    await new Promise(resolve => { finish = resolve; });
    return 'unavailable';
  }, {hardStop: stopped, cleanupGraceMs: 10});
  const controller = new AbortController();
  const pending = post(url, body, TOKEN, {signal: controller.signal}).catch(() => null);
  await started; controller.abort(); await pending; await hardStopped;
  assert.equal((await post(url)).status, 429);
  finish();
});
