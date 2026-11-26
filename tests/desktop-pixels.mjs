// Renders the real Studio in a Chromium-family browser, in Hermes Desktop's light and dark tokens,
// and checks what was actually drawn by reading screenshot pixels.
//
//   CUTROOM_UI_MODULES=<node_modules with react, react-dom and esbuild>
//   CUTROOM_BROWSER=<path to Chrome, Edge or Chromium>
//   node --test tests/desktop-pixels.mjs
//
// Without both variables the test is skipped. CUTROOM_UI_SHOTS=<folder> keeps the screenshots.
// Host controls (Button, Input) are drawn by stand-ins, so only whether they show is checked;
// contrast is measured on what Cutroom draws itself.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { inflateSync } from 'node:zlib';

const here = fileURLToPath(new URL('./pixels/', import.meta.url));
const modules = process.env.CUTROOM_UI_MODULES;
const browser = process.env.CUTROOM_BROWSER;
const ready = modules && browser && existsSync(join(modules, 'esbuild')) && existsSync(browser);
const themes = JSON.parse(readFileSync(join(here, 'themes.json'), 'utf8'));
const shots = process.env.CUTROOM_UI_SHOTS;

// ---- pixels -----------------------------------------------------------------------------------
function decodePng(buffer) {
  let offset = 8, width = 0, height = 0, type = 0;
  const data = [];
  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const name = buffer.toString('ascii', offset + 4, offset + 8);
    const body = buffer.subarray(offset + 8, offset + 8 + length);
    if (name === 'IHDR') { width = body.readUInt32BE(0); height = body.readUInt32BE(4); type = body[9]; assert.equal(body[8], 8, 'PNG bit depth'); }
    if (name === 'IDAT') data.push(body);
    offset += 12 + length;
  }
  const channels = type === 6 ? 4 : 3;
  const raw = inflateSync(Buffer.concat(data));
  const stride = width * channels;
  const out = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    for (let x = 0; x < stride; x++) {
      const value = raw[y * (stride + 1) + 1 + x];
      const a = x >= channels ? out[y * stride + x - channels] : 0;
      const b = y ? out[(y - 1) * stride + x] : 0;
      const c = x >= channels && y ? out[(y - 1) * stride + x - channels] : 0;
      const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
      const predictor = [0, a, b, (a + b) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? b : c][filter];
      out[y * stride + x] = (value + predictor) & 255;
    }
  }
  return { width, height, at: (x, y) => { const i = y * stride + x * channels; return [out[i], out[i + 1], out[i + 2]]; } };
}
const luminance = rgb => {
  const [r, g, b] = rgb.map(v => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (one, two) => { const [a, b] = [luminance(one), luminance(two)].sort((x, y) => y - x); return (a + 0.05) / (b + 0.05); };
const near = (one, two, slack = 24) => one.every((v, i) => Math.abs(v - two[i]) <= slack);
const hex = value => [1, 3, 5].map(i => parseInt(value.slice(i, i + 2), 16));
function pixels(image, rect) {
  const out = [];
  for (let y = Math.ceil(rect.y); y < Math.floor(rect.y + rect.h); y++) for (let x = Math.ceil(rect.x); x < Math.floor(rect.x + rect.w); x++) out.push([x, y, image.at(x, y)]);
  return out;
}
function background(list) {
  const counts = new Map();
  for (const [, , rgb] of list) { const key = rgb.map(v => v >> 3).join(','); counts.set(key, (counts.get(key) || [0, rgb]).map((v, i) => (i ? v : v + 1))); }
  return [...counts.values()].sort((a, b) => b[0] - a[0])[0][1];
}
/** Background of the box and the strongest text contrast drawn on it. */
function textContrast(image, rect) {
  const list = pixels(image, rect);
  const bg = background(list);
  return { bg, ratio: Math.max(...list.map(([, , rgb]) => contrast(bg, rgb))) };
}

// ---- browser ----------------------------------------------------------------------------------
async function session(port) {
  const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const ws = new WebSocket(pages.find(p => p.type === 'page').webSocketDebuggerUrl);
  await new Promise(resolve => ws.addEventListener('open', resolve));
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', event => { const m = JSON.parse(event.data); if (pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
  const send = (method, params = {}) => new Promise((resolve, reject) => { const i = ++id; pending.set(i, m => (m.error ? reject(new Error(m.error.message)) : resolve(m.result))); ws.send(JSON.stringify({ id: i, method, params })); });
  const evaluate = async expression => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const shot = async name => {
    const r = await send('Page.captureScreenshot', { format: 'png' });
    const buffer = Buffer.from(r.data, 'base64');
    if (shots) { mkdirSync(shots, { recursive: true }); writeFileSync(join(shots, `${name}.png`), buffer); }
    return decodePng(buffer);
  };
  return { send, evaluate, shot, close: () => ws.close() };
}
const rectOf = (page, selector) => page.evaluate(`(() => { const e = ${selector}; if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; })()`);
const byText = (tag, label) => `Array.from(document.querySelectorAll('${tag}')).find(e => e.innerText.trim() === ${JSON.stringify(label)} || e.innerText.trim().split('\\n').map(s => s.trim()).includes(${JSON.stringify(label)}))`;

// ---- scenario ---------------------------------------------------------------------------------
const zone = (top, bottom, left, right) => ({ top, bottom, left, right, source: 'https://example.test/spec', checked: '2026-11-12' });
const platforms = [
  { name: 'custom', label: 'Custom', short_label: 'Custom', orientation: null, frame: null, safe_zone: null },
  { name: 'youtube_shorts', label: 'YouTube Shorts', short_label: 'Shorts', orientation: 'portrait', frame: { preview: [1080, 1920], final: { 1080: [1080, 1920] } }, safe_zone: zone(0.15, 0.35, 0.05, 0.18), max_duration_seconds: 180 },
];
const sentence = 'Climate change is really not that complicated once you see the basic structure of the problem';
const words = sentence.split(' ').map((text, id) => ({ id, text, start: 0.5 + id * 0.55, end: 0.5 + id * 0.55 + 0.45, probability: 0.9 }));
const POSTER = '#2F8F6A';
const project = layout => ({
  id: 'p1', name: 'Talk', revision: 3, source: 'C:/v/talk.mp4', status: 'editing', posterTime: 3.6,
  source_info: { duration: 12, width: 1920, height: 1080, has_audio: true },
  transcript: { engine: 'test', status: 'ok', language: 'en', text: sentence, words },
  segments: [{ start: 0, end: 12 }], base_segments: [{ start: 0, end: 12 }], excluded_word_ids: [], artifacts: {},
  settings: { platform: 'youtube_shorts', aspect: 'portrait', framing: 'fill', captions: false, brand: {}, ...(layout ? { layout } : {}),
    redactions: { bleeps: [{ ids: [11], start: 6.55, end: 7, said: 'basic', mode: 'bleep' }], hidden: [{ start: 3, end: 4, said: 'that', box: { x: 0.55, y: 0.55, w: 0.2, h: 0.2 }, style: 'cover' }] } },
});
const SPLIT = { layout: 'split', speaker: 'wide', background: 'paper', divider: 1170, hold: 'whole', headline: { l1: 'CLIMATE CHANGE IS REALLY NOT', l2: 'THAT COMPLICATED', boxed: [1] },
  panel: { kind: 'card', type: 'title', text: 'Basics' }, pictures: [] };

test('Studio draws selections, buttons, layout and hidden areas readably in light and dark', { skip: !ready && 'set CUTROOM_UI_MODULES and CUTROOM_BROWSER' }, async () => {
  const work = mkdtempSync(join(process.env.TMPDIR || tmpdir(), 'cutroom-pixels-'));
  const require = createRequire(join(modules, 'noop.js'));
  await require('esbuild').build({
    entryPoints: [join(here, 'page.js')], bundle: true, format: 'iife', outfile: join(work, 'bundle.js'), logLevel: 'error', nodePaths: [modules],
    alias: { '@hermes/plugin-sdk': join(here, 'sdk.js'), PLUGIN: fileURLToPath(new URL('../desktop/plugin.js', import.meta.url)) },
    define: { 'process.env.NODE_ENV': '"production"' },
  });
  const html = `<!doctype html><meta charset=utf-8><style>
    img, video { max-width: 100%; height: auto; } /* Hermes Desktop's base rule */
    html, body { margin: 0; background: var(--ui-bg-editor); color: var(--ui-text-primary); font: 13px/1.45 "Segoe UI", system-ui, sans-serif; }
    #app { height: 100vh; overflow: auto; padding: 0 12px; box-sizing: border-box; }
    .sdk-button { font: inherit; height: 28px; padding: 0 10px; border-radius: 6px; border: 1px solid var(--ui-stroke-secondary); background: transparent; color: var(--ui-text-primary); }
    .sdk-button.primary { background: var(--ui-accent); border-color: var(--ui-accent); color: #fff; }
    .sdk-input { font: inherit; height: 28px; padding: 0 8px; border: 1px solid var(--ui-stroke-secondary); border-radius: 6px; background: transparent; color: var(--ui-text-primary); }
    .sdk-badge { font-size: 11px; padding: 1px 7px; border-radius: 9px; border: 1px solid var(--ui-stroke-secondary); }
  </style><div id=app></div><script src="bundle.js"></script>`;
  const server = createServer((request, response) => {
    const body = request.url.startsWith('/bundle.js') ? readFileSync(join(work, 'bundle.js')) : html;
    response.writeHead(200, { 'content-type': request.url.startsWith('/bundle.js') ? 'text/javascript' : 'text/html' });
    response.end(body);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const profile = join(work, 'profile');
  const child = spawn(browser, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--window-size=1500,1000', '--force-device-scale-factor=1', '--hide-scrollbars', '--no-first-run', 'about:blank'], { stdio: 'ignore' });
  let page = null;
  try {
    let port = null;
    for (let i = 0; i < 100 && !port; i++) { await new Promise(r => setTimeout(r, 100)); try { port = readFileSync(join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0]; } catch { /* Not yet. */ } }
    assert.ok(port, 'The browser opened a debugging port');
    page = await session(port);
    await page.send('Emulation.setDeviceMetricsOverride', { width: 1500, height: 1000, deviceScaleFactor: 1, mobile: false });
    await page.send('Page.navigate', { url: `http://127.0.0.1:${server.address().port}/` });
    await new Promise(r => setTimeout(r, 800));
    for (const name of ['light', 'dark']) {
      const theme = themes[name];
      // Edit: one selected word and its toolbar.
      await page.evaluate(`window.__mount(${JSON.stringify({ project: project(null), platforms, theme, posterColour: POSTER })})`);
      await page.evaluate(`(() => { document.querySelector('[data-word-id="5"]').click(); return 1; })()`);
      await new Promise(r => setTimeout(r, 300));
      let image = await page.shot(`${name}-edit`);
      const selected = await rectOf(page, `document.querySelector('[data-word-id="5"]')`);
      const plain = await rectOf(page, `document.querySelector('[data-word-id="8"]')`);
      const chosen = textContrast(image, selected), other = textContrast(image, plain);
      assert.ok(contrast(chosen.bg, other.bg) >= 1.25, `${name}: the selected word is visibly highlighted (${contrast(chosen.bg, other.bg).toFixed(2)})`);
      assert.ok(chosen.ratio >= 4.5, `${name}: selected word text contrast ${chosen.ratio.toFixed(2)}`);
      assert.ok(other.ratio >= 4.5, `${name}: transcript text contrast ${other.ratio.toFixed(2)}`);
      for (const label of ['Bleep', 'Hide area']) {
        const rect = await rectOf(page, byText('button', label));
        assert.ok(rect && rect.w > 0, `${name}: ${label} is shown for the selection`);
      }
      const hint = await rectOf(page, `Array.from(document.querySelectorAll('p')).find(p => p.innerText.startsWith('Click a word to jump there'))`);
      assert.ok(textContrast(image, hint).ratio >= 4.5, `${name}: help text contrast ${textContrast(image, hint).ratio.toFixed(2)}`);
      // Fill framing: the hidden box sits on the picture where it was drawn.
      const frame = await rectOf(page, `document.querySelector('[aria-label="YouTube Shorts frame"]')`);
      const hidden = await rectOf(page, `document.querySelector('[data-cutroom-hidden]')`);
      assert.ok(hidden && hidden.w > 4, `${name}: the hidden area is drawn on the player`);
      const shown = { x: Math.max(hidden.x, frame.x), y: Math.max(hidden.y, frame.y) };
      shown.w = Math.min(hidden.x + hidden.w, frame.x + frame.w) - shown.x;
      shown.h = Math.min(hidden.y + hidden.h, frame.y + frame.h) - shown.y;
      assert.ok(shown.w > 4 && shown.h > 4, `${name}: part of the hidden area is in the frame`);
      assert.ok(near(image.at(Math.round(shown.x + shown.w / 2), Math.round(shown.y + shown.h / 2)), hex('#101114'), 12), `${name}: the hidden area is solid`);
      // Fill framing crops the sides; the part of the box outside the crop must not be drawn over the player.
      const outside = pixels(image, { x: frame.x + frame.w + 2, y: shown.y + 2, w: 12, h: shown.h - 4 }).filter(([, , rgb]) => near(rgb, hex('#101114'), 8));
      assert.equal(outside.length, 0, `${name}: nothing of the hidden area spills past the frame`);
      // A video stage is dark in both themes, like every player; captions and the frame read the same everywhere.
      const stage = image.at(Math.round(frame.x - 30), Math.round(frame.y + 40));
      assert.ok(luminance(stage) < 0.06, `${name}: the player stage is dark (${stage})`);

      // The timed strip: blocks stand out from their lane (3:1, like any control) and a real mouse drag moves one.
      await page.evaluate(`(() => { document.querySelectorAll('details').forEach(d => { d.open = true; }); document.querySelector('[data-cutroom-lane="bleeps"]').scrollIntoView({ block: 'center' }); return 1; })()`);
      await new Promise(r => setTimeout(r, 300));
      image = await page.shot(`${name}-strip`);
      for (const key of ['hidden', 'bleeps']) {
        const laneBox = await rectOf(page, `document.querySelector('[data-cutroom-lane="${key}"]')`);
        const blockBox = await rectOf(page, `document.querySelector('[data-cutroom-block="${key}0"]')`);
        const ground = image.at(Math.round(laneBox.x + laneBox.w - 6), Math.round(laneBox.y + laneBox.h / 2));
        const fill = image.at(Math.round(blockBox.x + blockBox.w / 2), Math.round(blockBox.y + blockBox.h / 2));
        assert.ok(contrast(ground, fill) >= 3, `${name}: ${key} blocks stand out from their lane (${contrast(ground, fill).toFixed(2)})`);
      }
      const block = await rectOf(page, `document.querySelector('[data-cutroom-block="bleeps0"]')`);
      const laneBox = await rectOf(page, `document.querySelector('[data-cutroom-lane="bleeps"]')`);
      const mouse = (type, x, buttons) => page.send('Input.dispatchMouseEvent', { type, x, y: Math.round(block.y + block.h / 2), button: 'left', buttons, clickCount: 1 });
      const from = Math.round(block.x + block.w / 2), to = Math.round(from + (2.2 / 12) * laneBox.w);
      await mouse('mouseMoved', from, 0);
      await mouse('mousePressed', from, 1);
      for (let x = from; x <= to; x += 12) await mouse('mouseMoved', x, 1);
      await mouse('mouseMoved', to, 1);
      await mouse('mouseReleased', to, 0);
      await new Promise(r => setTimeout(r, 300));
      const moved = await page.evaluate(`document.querySelector('[data-cutroom-block="bleeps0"]').getAttribute('aria-label')`);
      assert.match(moved, /“problem”/, `${name}: a mouse drag moved the bleep 2.2 s later, onto a whole word (${moved})`);

      // Style: split layout with the speaker card, headline and panel.
      await page.evaluate(`window.__mount(${JSON.stringify({ project: { ...project(SPLIT), posterTime: 8 }, platforms, theme, posterColour: POSTER })})`);
      image = await page.shot(`${name}-split`);
      const load = await rectOf(page, byText('button', 'Load video (100 MB)'));
      const onTop = await page.evaluate(`(() => { const b = ${byText('button', 'Load video (100 MB)')}; const r = b.getBoundingClientRect(); return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2) === b; })()`);
      assert.ok(load && onTop, `${name}: Load video is not covered by the layout`);
      const card = await rectOf(page, `document.querySelector('[data-cutroom-speaker]')`);
      const inside = pixels(image, { x: card.x + 6, y: card.y + 6, w: card.w - 12, h: card.h - 12 });
      const filled = inside.filter(([, , rgb]) => near(rgb, hex(POSTER), 30)).length / inside.length;
      assert.ok(filled > 0.95, `${name}: the speaker fills the card (${(filled * 100).toFixed(1)} %)`);
      const shorts = await rectOf(page, `document.querySelector('[aria-label="YouTube Shorts frame"]')`);
      const head = await rectOf(page, `document.querySelector('[data-cutroom-headline]')`);
      const limit = shorts.x + shorts.w * (1 - 0.18);
      const ink = pixels(image, { x: limit, y: head.y, w: shorts.x + shorts.w - limit, h: head.h }).filter(([, , rgb]) => near(rgb, hex('#1D2128'), 40) || near(rgb, hex('#FFD02E'), 40));
      assert.equal(ink.length, 0, `${name}: no headline pixels beside the Shorts buttons`);
    }
  } finally {
    page?.close();
    child.kill();
    server.close();
    await new Promise(r => setTimeout(r, 500));
    rmSync(work, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
});
