// Exercise the real Home and forecast client with deterministic HTTPS boundary responses.
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { openPreview, root } from './browser.mjs';

const out = root + '.local/qa/widgets/';
mkdirSync(out, { recursive: true });
const report = { startedAt: new Date().toISOString(), scope: 'Browser only; mock forecast service; no TV contacted.', checks: [], failures: [] };
let preview, current, requests, response, section;
const now = () => Math.floor(Date.now() / 1000);
const forecast = (patch = {}) => ({
  current_units: { temperature_2m: '°C' },
  current: { time: now(), temperature_2m: 20, apparent_temperature: 18, is_day: 1, weather_code: 2, ...patch },
  daily: { time: [now() - 3600], temperature_2m_max: [23], temperature_2m_min: [12], precipitation_probability_max: [20] }
});
const cached = (patch = {}) => ({ city: 'east-lansing-mi', time: Date.now(), temp: 20, feels: 18, code: 2, day: 1, high: 23, low: 12, rain: 20, dayStart: Date.now() - 3600000, ...patch });
function check(name, condition, detail) {
  report.checks.push({ section, name, passed: !!condition });
  assert.ok(condition, name + (detail ? ': ' + JSON.stringify(detail) : ''));
}
async function page({ cache, enabled, home, status = 200, body } = {}) {
  response = { status, body: body || forecast() }; requests = [];
  current = await preview.browser.newPage({ viewport: { width: 1920, height: 1080 }, timezoneId: 'America/Detroit' });
  current.on('pageerror', error => report.failures.push({ section, pageError: error.message }));
  await current.route('https://api.open-meteo.com/**', async route => {
    requests.push(route.request().url());
    await route.fulfill({ status: response.status, contentType: 'application/json', body: JSON.stringify(response.body) });
  });
  await current.addInitScript(({ cache, enabled, home }) => {
    if (sessionStorage.getItem('widgets-seeded')) return;
    sessionStorage.setItem('widgets-seeded', 'yes');
    if (cache !== undefined) localStorage.setItem('cleanframe.weather.cache.v1', JSON.stringify(cache));
    if (enabled !== undefined) localStorage.setItem('cleanframe.weather.v1', JSON.stringify({ enabled }));
    if (home) localStorage.setItem('cleanframe.home.v1', JSON.stringify(home));
  }, { cache, enabled, home });
  await current.goto(preview.baseURL + '/home/');
  await current.waitForFunction(() => ShoreQA.ready() && !CleanFrameWeather.state().loading);
}
const weather = () => current.evaluate(() => CleanFrameWeather.state());
const state = () => current.evaluate(() => ShoreQA.state());
const text = () => current.locator('#weather').innerText();
async function action(name) {
  const result = await current.evaluate(name => ShoreQA.activate(name), name);
  assert.ok(result, 'Action must be reachable: ' + name);
}
async function weatherSettings() {
  await current.evaluate(() => ShoreQA.scene('settings'));
  await action('settings.group.weather');
}
async function settled() { await current.waitForFunction(() => !CleanFrameWeather.state().loading); }
async function run(name, fn) {
  section = name;
  try { await fn(); console.log(name + ': passed'); }
  catch (error) { report.failures.push({ section, error: error.stack }); console.error(name + ': ' + error.message); }
  finally { if (current) { await current.close(); current = null; } }
}

try {
  preview = await openPreview({ publicFonts: true });
  await run('Personal defaults, natural text and dual units', async () => {
    await page(); const s = await state(), copy = await text();
    check('Fresh Home has the seven requested shortcuts without Stremio', JSON.stringify(s.home) === JSON.stringify(['netflix', 'youtube', 'PvWgqxV3Xa.YouTubeTV', 'disneyplus', 'primevideo', 'appletv', 'rJeHak5zRg.Spotify']));
    check('YouTube TV and Spotify have distinct labelled, bundled marks', await current.locator('.tile[data-brand="youtubetv"] [data-mark="youtubetv"]').count() === 1 && await current.locator('.tile[data-brand="spotify"] [data-mark="spotify"]').count() === 1);
    check('All seven app marks fit within the dock', await current.evaluate(() => {
      const shelf = document.getElementById('shelf').getBoundingClientRect();
      return [...document.querySelectorAll('#dock .mark')].every(mark => { const r = mark.getBoundingClientRect(); return r.left >= shelf.left && r.right <= shelf.right; });
    }));
    check('Fresh Home uses Golden hour and public Geist', s.wallpaper === 'golden' && s.font === 'geist' && s.controls === 'icons');
    check('Both units are converted from one Celsius observation', copy.includes('68°F') && copy.includes('20°C'));
    check('Forecast is natural text with an apparent temperature', copy.includes('Partly cloudy right now. Feels like 64°F / 18°C.'));
    check('City and data attribution are visible', copy.includes('East Lansing') && copy.includes('Open-Meteo'));
    check('Art Mode is absent until supported by the actual installed-app list', await current.locator('[data-action="util.art"]').count() === 0);
    const artOnNonFrame = await current.evaluate(async () => {
      window.tizen = { application: { getAppsInfo: done => done([{ id: 'org.tizen.art-app', name: 'ArtApp', show: true }]) } };
      await new Promise(resolve => FrameDevice.apps(resolve));
      return FrameDevice.supportsArt();
    });
    check('A Samsung system ArtApp component alone does not enable Frame controls', !artOnNonFrame);
    const url = new URL(requests[0]);
    check('Request uses East Lansing coordinates and its timezone', url.searchParams.get('latitude') === '42.737' && url.searchParams.get('longitude') === '-84.484' && url.searchParams.get('timezone') === 'America/Detroit');
    check('There is no key, precise geolocation or third-party font request in the weather URL', !/[?&](?:key|token|apikey)=/.test(url.href));
    check('Clock has a local date and time-appropriate greeting', await current.locator('.home-date').innerText() !== '' && /Good (morning|afternoon|evening)\./.test(await current.locator('.home-greeting').innerText()));
    await current.screenshot({ path: out + 'home-east-lansing-1920.png' });
  });
  await run('Sofa legibility, layout boundaries and remote focus', async () => {
    await page();
    for (const layout of ['dock', 'list']) for (const width of [1920, 1280]) {
      await current.setViewportSize({ width, height: width * 9 / 16 });
      await current.waitForFunction(width => Math.abs(document.getElementById('stage').getBoundingClientRect().width - width) < 1, width);
      await current.evaluate(layout => ShoreQA.look({ layout }), layout);
      await current.waitForFunction(() => ShoreQA.ready());
      const boxes = await current.evaluate(() => {
        const box = id => { const r = document.getElementById(id).getBoundingClientRect(); return { x: r.x, y: r.y, right: r.right, bottom: r.bottom }; };
        return { weather: box('weather'), caption: box('caption'), utils: box('utils'), focus: ShoreQA.where().focusCount, overflow: document.getElementById('weather').scrollWidth > document.getElementById('weather').clientWidth };
      });
      check(layout + '/' + width + ': weather fits screen without horizontal overflow', boxes.weather.x >= 0 && boxes.weather.y >= 0 && boxes.weather.right <= width && boxes.weather.bottom < width * 9 / 16 && !boxes.overflow, boxes);
      check(layout + '/' + width + ': weather does not collide with controls or clock', boxes.weather.bottom <= boxes.utils.y && (boxes.caption.right <= boxes.weather.x || boxes.caption.bottom <= boxes.weather.y), boxes);
      check(layout + '/' + width + ': only one remote action has focus', boxes.focus === 1);
      await current.keyboard.press(layout === 'dock' ? 'ArrowUp' : 'ArrowRight');
      check(layout + '/' + width + ': remote reaches utilities', await current.evaluate(() => ShoreQA.where().zone === 'util'));
      await current.keyboard.press('Escape');
      await current.screenshot({ path: out + 'home-' + layout + '-' + width + '.png' });
    }
    check('Home has no live filters or backdrop blur', await current.evaluate(() => ![...document.querySelectorAll('.home *')].some(el => {
      const css = getComputedStyle(el); return css.filter !== 'none' || (css.backdropFilter && css.backdropFilter !== 'none');
    })));
    await weatherSettings();
    check('Weather settings is reachable with a single focus', await current.evaluate(() => ShoreQA.where().focusCount === 1 && ShoreQA.state().settingsGroup === 'weather'));
    check('Weather action has an appropriate remote hint', (await current.locator('#appearanceDesc').innerText()).includes('Show or hide the weather card'));
    await current.keyboard.press('Escape');
    check('Back restores Weather category focus', (await state()).focusAction === 'settings.group.weather');
  });
  await run('Offline startup and explicit retry', async () => {
    await page({ status: 503 });
    check('Failed initial request shows an honest empty state', (await text()).includes('Weather unavailable') && !(await text()).includes('°F'));
    check('Weather failure does not block Home readiness or remote focus', await current.evaluate(() => ShoreQA.ready() && ShoreQA.where().focusCount === 1));
    response = { status: 200, body: forecast({ temperature_2m: 0, apparent_temperature: -5, weather_code: 73, is_day: 0 }) };
    await weatherSettings(); await action('weather.refresh'); await settled();
    check('Retry recovers through the real forecast client', (await weather()).data.temp === 0 && requests.length === 2);
    await current.evaluate(() => ShoreQA.scene('home'));
    check('Night and freezing weather produce accurate natural copy', (await text()).includes('Snow tonight.') && (await text()).includes('32°F') && (await text()).includes('23°F / -5°C'));
    response = { status: 200, body: forecast({ temperature_2m: null, weather_code: 999 }) };
    await weatherSettings(); await action('weather.refresh'); await settled();
    check('Malformed success response preserves the previous valid observation', (await weather()).data.temp === 0 && !!(await weather()).error);
  });
  await run('Cached weather, stale labels and expiration', async () => {
    await page({ cache: cached({ time: Date.now() - 2 * 3600000 }), status: 503 });
    check('Stale cached data is labelled with age and offline state', (await text()).includes('Last known:') && (await text()).includes('Updated 2 hr ago') && (await text()).includes('Offline'));
    await current.close(); current = null;
    await page({ cache: cached({ time: Date.now() - 7 * 3600000 }), status: 503 });
    check('Expired observations are never displayed as current weather', !(await text()).includes('°F') && (await text()).includes('Weather unavailable'));
    await current.close(); current = null;
    await page({ cache: cached({ temp: '<img src=x onerror=alert(1)>' }), status: 503 });
    check('Invalid cache values are rejected instead of inserted into HTML', !(await text()).includes('°F') && await current.locator('#weather img').count() === 0);
  });
  await run('Weather preference persistence and storage failure', async () => {
    await page(); const before = await current.evaluate(() => localStorage.getItem('cleanframe.home.v1'));
    await weatherSettings();
    await current.evaluate(() => {
      window.widgetSetItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key, value) { if (key === 'cleanframe.weather.v1') throw new DOMException('No storage', 'QuotaExceededError'); return widgetSetItem.call(this, key, value); };
    });
    await action('weather.toggle');
    check('Failed weather preference save retains the committed setting', (await weather()).enabled && !!(await weather()).saveError);
    check('Failed preference save explains retry', (await current.locator('#appearanceStatus').innerText()).includes('unchanged'));
    await current.evaluate(() => { Storage.prototype.setItem = window.widgetSetItem; });
    await action('weather.toggle');
    check('Hiding weather succeeds after storage recovers', !(await weather()).enabled);
    await current.evaluate(() => ShoreQA.scene('home'));
    check('Hidden weather is removed from the visual Home', await current.locator('#weather').isHidden());
    check('Weather changes do not rewrite Home preferences', before === await current.evaluate(() => localStorage.getItem('cleanframe.home.v1')));
    await current.reload(); await current.waitForFunction(() => ShoreQA.ready());
    check('Hidden setting survives relaunch and avoids forecast requests', !(await weather()).enabled && requests.length === 1);
    await weatherSettings(); await action('weather.toggle'); await settled();
    check('Re-enabling starts a new forecast request', (await weather()).enabled && requests.length === 2);
  });
  await run('Existing Home preferences survive the redesign', async () => {
    await page({ home: { theme: 'list', dock: ['youtube', 'netflix'], wallpaper: 'forest', mode: '15', lastApp: 'youtube' }, enabled: false });
    const s = await state();
    check('Existing app order and wallpaper are retained', JSON.stringify(s.home) === JSON.stringify(['youtube', 'netflix']) && s.wallpaper === 'forest');
    check('Existing List layout and rotation are retained', s.layout === 'list' && s.mode === '15');
    check('Disabled weather makes no external request', requests.length === 0);
  });
  await run('Requested shortcuts launch verified native app IDs', async () => {
    await page({ enabled: false });
    await current.evaluate(() => {
      window.requestedLaunches = [];
      window.tizen = { application: { launch: (id, done) => { requestedLaunches.push(id); done(); } } };
    });
    for (const id of ['PvWgqxV3Xa.YouTubeTV', 'rJeHak5zRg.Spotify']) {
      await action('home.app.' + id);
      check('Launch uses the inventory-confirmed ID: ' + id, await current.evaluate(id => requestedLaunches.at(-1) === id, id));
    }
    await current.reload(); await current.waitForFunction(() => ShoreQA.ready());
    check('Requested pins survive relaunch without adding Stremio', (await state()).home.includes('PvWgqxV3Xa.YouTubeTV') && (await state()).home.includes('rJeHak5zRg.Spotify') && !(await state()).home.includes('stremio'));
  });
  await run('Disabling weather cancels an in-flight refresh', async () => {
    await page(); const before = (await weather()).data;
    let intercepted;
    const pending = new Promise(resolve => { intercepted = resolve; });
    await current.route('https://api.open-meteo.com/**', route => { intercepted(route); });
    await current.evaluate(() => CleanFrameWeather.refresh(true));
    const held = await pending;
    await weatherSettings(); await action('weather.toggle');
    check('Turning the widget off ends its loading state', !(await weather()).enabled && !(await weather()).loading);
    await held.fulfill({ json: forecast({ temperature_2m: 35 }) }).catch(() => {});
    check('Late forecast cannot replace the retained observation', (await weather()).data.temp === before.temp);
    await current.evaluate(() => ShoreQA.scene('home'));
    check('Late response does not redisplay the hidden widget', await current.locator('#weather').isHidden());
  });
} catch (error) { report.failures.push({ section: section || 'setup', error: error.stack }); }
finally {
  if (current) await current.close();
  if (preview) await preview.close();
  report.finishedAt = new Date().toISOString();
  writeFileSync(out + 'checks.json', JSON.stringify(report, null, 2) + '\n');
}
console.log(report.checks.filter(c => c.passed).length + ' widget checks passed; ' + report.failures.length + ' failure(s).');
if (report.failures.length) process.exitCode = 1;
