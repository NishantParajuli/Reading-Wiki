import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {allowedViewer, browserEnvironment, responseOutcome, unlockChapter, validateUnlock} from './browser.mjs';

const body = () => ({episode_id: 610753, cookies: [{name: 'TKEY', value: 'private-test-token', domain: '.novelpia.com', path: '/'}]});
const response = (path, payload, status = 200) => ({url: () => `https://api-global.novelpia.com${path}`, status: () => status, json: async () => payload});

test('strict cookie boundary accepts only unexpired auth cookies and a bounded episode id', () => {
  assert.equal(validateUnlock(body()).cookies[0].httpOnly, true);
  assert.equal(validateUnlock({...body(), cookies: [{...body().cookies[0], expires: null}]}).cookies[0].expires, undefined);
  assert.equal(validateUnlock({...body(), cookies: [...body().cookies, {...body().cookies[0], name: 'LOGINKEY', expires: 1}]}).cookies.length, 1);
  for (const change of [{episode_id: -1}, {episode_id: '610753'}, {episode_id: Number.MAX_SAFE_INTEGER + 1},
    {timeout_seconds: 91}, {cookies: []}, {cookies: [{...body().cookies[0], value: 'secret; x=1'}]},
    {cookies: [{...body().cookies[0], domain: '.example.com'}]}, {cookies: [{...body().cookies[0], name: 'GoogleAuth'}]},
    {cookies: [{...body().cookies[0], expires: 1}]}, {cookies: [{...body().cookies[0], expires: -1}]},
    {cookies: [{...body().cookies[0], path: '/viewer'}]}, {cookies: [...body().cookies, ...body().cookies]}]) {
    assert.throws(() => validateUnlock({...body(), ...change}), /invalid/);
  }
});
test('top-level navigation stays on the same official chapter', () => {
  assert.ok(allowedViewer('https://global.novelpia.com/viewer/610753?x=1', 610753));
  for (const url of ['http://global.novelpia.com/viewer/610753', 'https://evil.test/viewer/610753',
    'https://global.novelpia.com/viewer/610754', 'https://global.novelpia.com/novel/4053',
    'https://user:secret@global.novelpia.com/viewer/610753']) assert.equal(allowedViewer(url, 610753), false);
});
test('browser does not inherit sidecar or application secrets', () => {
  assert.deepEqual(browserEnvironment({PATH: '/bin', HOME: '/tmp', SIDECAR_AUTH_TOKEN: 'secret', DATABASE_URL: 'secret'}), {PATH: '/bin', HOME: '/tmp'});
});
test('completion requires ordinary successful content or reward response', async () => {
  assert.equal(await responseOutcome(response('/v1/ad/reward/grant', {code: '0000'}, 201)), 'completed');
  assert.equal(await responseOutcome(response('/v1/novel/episode/content', {code: '0000', result: {data: {epi_content: '<p>Text</p>'}}})), 'completed');
  assert.equal(await responseOutcome(response('/v1/ad/reward/grant', {code: '0008'})), null);
  assert.equal(await responseOutcome(response('/v1/novel/episode/content', {code: '0000', result: {data: {}}})), null);
  assert.equal(await responseOutcome(response('/v1/login/refresh', {}, 401)), 'login_required');
  assert.equal(await responseOutcome({...response('/v1/ad/reward/grant', {code: '0000'}), url: () => 'https://evil.test/v1/ad/reward/grant'}), null);
});

function fakeBrowser({mode = 'success', delayLaunch = 0} = {}) {
  const page = new EventEmitter();
  const context = new EventEmitter();
  let closed = 0;
  let clicks = 0;
  let ready = false;
  let route;
  let launchOptions;
  page.mainFrame = () => page;
  page.goto = async () => {
    if (mode === 'content') page.emit('response', response('/v1/novel/episode/content', {code: '0000', result: {data: {epi_content: 'text'}}}));
    if (mode === 'login') page.emit('response', response('/v1/login/refresh', {}, 401));
    setTimeout(() => { ready = true; }, 20);
  };
  page.getByRole = (role, options) => {
    assert.equal(role, 'button'); assert.deepEqual(options, {name: 'Continue', exact: true});
    return {count: async () => 1, isVisible: async () => true, isEnabled: async () => ready && mode === 'success',
      click: async () => { assert.ok(ready); clicks++; page.emit('response', response('/v1/ad/reward/grant', {code: '0000'}, 201)); }};
  };
  context.addCookies = async cookies => { assert.equal(cookies[0].name, 'TKEY'); };
  context.newPage = async () => page;
  context.route = async (_pattern, callback) => { route = callback; };
  const chromium = {launch: async options => {
    launchOptions = options;
    if (delayLaunch) await new Promise(resolve => setTimeout(resolve, delayLaunch));
    return {newContext: async options => { assert.equal(options.serviceWorkers, 'block'); return context; }, close: async () => { closed++; }};
  }};
  return {chromium, page, get clicks() { return clicks; }, get closed() { return closed; }, get route() {return route;}, get launchOptions() {return launchOptions;}};
}
test('waits for enabled Continue, uses mandatory proxy, closes browser after success', async () => {
  const browser = fakeBrowser();
  const status = await unlockChapter({...validateUnlock(body()), timeoutMs: 2000}, {...browser, proxy: 'http://egress:8899'});
  assert.equal(status, 'completed'); assert.equal(browser.clicks, 1); assert.ok(browser.closed);
  assert.deepEqual(browser.launchOptions.proxy, {server: 'http://egress:8899', bypass: '<-loopback>'});
});
test('already unlocked content requires no button interaction', async () => {
  const browser = fakeBrowser({mode: 'content'});
  assert.equal(await unlockChapter(validateUnlock(body()), {...browser, proxy: 'http://egress:8899'}), 'completed');
  assert.equal(browser.clicks, 0); assert.ok(browser.closed);
});
test('login rejection and deadline close disposable browser', async () => {
  for (const mode of ['login', 'timeout']) {
    const browser = fakeBrowser({mode});
    assert.equal(await unlockChapter({...validateUnlock(body()), timeoutMs: 30}, {...browser, proxy: 'http://egress:8899'}), mode === 'login' ? 'login_required' : 'timeout');
    assert.ok(browser.closed); assert.equal(browser.clicks, 0);
  }
});
test('disconnect during launch also closes the late browser before returning', async () => {
  const browser = fakeBrowser({delayLaunch: 30});
  const controller = new AbortController();
  const result = unlockChapter(validateUnlock(body()), {...browser, proxy: 'http://egress:8899', signal: controller.signal});
  controller.abort();
  assert.equal(await result, 'unavailable'); assert.ok(browser.closed); assert.equal(browser.clicks, 0);
});

test('network routing blocks foreign top-level pages and insecure subresources', async () => {
  const browser = fakeBrowser({mode: 'content'});
  await unlockChapter(validateUnlock(body()), {...browser, proxy: 'http://egress:8899'});
  for (const [url, navigation, frame, expected] of [
    ['https://global.novelpia.com/viewer/610753', true, browser.page, 'continue'],
    ['https://global.novelpia.com/viewer/610754', true, browser.page, 'abort'],
    ['https://accounts.google.com/', true, browser.page, 'abort'],
    ['https://ad.example.test/frame', true, {}, 'continue'],
    ['http://ad.example.test/script.js', false, {}, 'abort'],
  ]) {
    let decision;
    await browser.route({request: () => ({url: () => url, isNavigationRequest: () => navigation, frame: () => frame}),
      abort: async () => {decision = 'abort';}, continue: async () => {decision = 'continue';}});
    assert.equal(decision, expected);
  }
});
