import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const file = new URL('../desktop/plugin.js', import.meta.url);
let source = '';
try { source = await readFile(file, 'utf8'); } catch { /* First TDD run has no plugin yet. */ }
const imports = [...source.matchAll(/import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"];?/g)];
const records = [];
const navigation = [];
const primitive = name => Object.assign(props => ({ type: name, props }), { displayName: name });
let connectionId = 'host-a';
const sdk = {
  ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'sidebar.nav', PALETTE_AREA: 'palette',
  host: { navigate: path => navigation.push(path), state: { profile: { get: () => 'default' }, connectionId: { get: () => connectionId } } },
};
const react = {};
let activeHooks = null;
const hookStores = new Map();
const effects = [];
const queries = [];
const invalidations = [];
let projectRows = [];
let selectedProject = null;
let jobRows = [];
let posterData = null;
const zone = (top, bottom, left, right) => ({ top, bottom, left, right, source: 'https://example.test/spec', checked: '2026-11-12' });
const frames = portrait => ({ preview: portrait ? [1080, 1920] : [1920, 1080], final: portrait ? { 1080: [1080, 1920], 2160: [2160, 3840] } : { 1080: [1920, 1080], 2160: [3840, 2160] }, default_final: '1080' });
const platformRows = [
  { name: 'custom', label: 'Custom', short_label: 'Custom', orientation: null, frame: null, safe_zone: null },
  { name: 'instagram_reels', label: 'Instagram Reels', short_label: 'Reels', orientation: 'portrait', frame: frames(true), safe_zone: zone(0.14, 0.35, 0.06, 0.06), max_duration_s: { value: 1200 }, recommended_max_s: { value: 180 } },
  { name: 'youtube_shorts', label: 'YouTube Shorts', short_label: 'Shorts', orientation: 'portrait', frame: frames(true), safe_zone: zone(0.15, 0.35, 0.05, 0.18), max_duration_s: { value: 180 } },
  { name: 'tiktok', label: 'TikTok', short_label: 'TikTok', orientation: 'portrait', frame: frames(true), safe_zone: zone(0.13, 0.35, 0.12, 0.28), max_duration_s: { value: 3600 } },
  { name: 'youtube', label: 'YouTube', short_label: 'YouTube', orientation: 'landscape', frame: frames(false), safe_zone: zone(0.05, 0.05, 0.05, 0.05), max_duration_s: { value: null } },
];
react.useState = initial => {
  const store = activeHooks;
  const index = store.index++;
  if (!(index in store.slots)) store.slots[index] = typeof initial === 'function' ? initial() : initial;
  return [store.slots[index], value => { store.slots[index] = typeof value === 'function' ? value(store.slots[index]) : value; }];
};
react.useRef = initial => {
  const [value] = react.useState(() => ({ current: initial }));
  return value;
};
react.useEffect = (effect, dependencies) => {
  const ref = react.useRef({ deps: null, cleanup: null });
  if (!ref.current.deps || dependencies.some((x, i) => x !== ref.current.deps[i])) {
    ref.current.deps = dependencies;
    effects.push(() => { ref.current.cleanup?.(); ref.current.cleanup = effect(); });
  }
};
sdk.useValue = value => value.get();
sdk.useQuery = options => {
  queries.push(options);
  const kind = options.queryKey.find(x => ['projects', 'project', 'jobs', 'platforms', 'activity', 'poster'].includes(x));
  return { data: options.enabled === false ? undefined : kind === 'poster' ? posterData : kind === 'projects' ? projectRows : kind === 'project' ? selectedProject : kind === 'platforms' ? platformRows : jobRows,
    isPending: false, isFetching: false, error: null, refetch: () => options.queryFn() };
};
sdk.useQueryClient = () => ({ invalidateQueries: options => invalidations.push(options), setQueryData: () => {} });
sdk.useMutation = options => ({ isPending: false, error: null, reset() {},
  mutateAsync: async input => { const result = await options.mutationFn(input); await options.onSuccess?.(result, input); return result; } });
function render(node, path = 'root') {
  if (node == null || typeof node !== 'object') return node;
  if (Array.isArray(node)) {
    const keys = new Map();
    for (const child of node) {
      if (child == null || Array.isArray(child) || child.key == null) continue;
      const key = String(child.key);
      const name = typeof child.type === 'function' ? child.type.name : child.type;
      assert.ok(!keys.has(key), `Duplicate sibling React key "${key}" at ${path}: ${keys.get(key)} and ${name}`);
      keys.set(key, name);
    }
    return node.map((n, i) => render(n, `${path}.${i}`));
  }
  if (typeof node.type === 'function') {
    const key = `${path}:${node.type.name}:${node.key ?? ''}`;
    const store = hookStores.get(key) || { slots: [], index: 0 };
    hookStores.set(key, store); store.index = 0;
    activeHooks = store;
    return render(node.type(node.props), `${key}.child`);
  }
  return { ...node, props: { ...node.props, children: render(node.props.children, `${path}.children`) } };
}
function nodes(node) {
  if (node == null || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function text(node) {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node !== 'object') return String(node);
  if (Array.isArray(node)) return node.map(text).join(' ');
  return text(node.props?.children);
}
function draw(route) { const tree = render(route.render()); while (effects.length) effects.shift()(); return tree; }
function button(tree, label) { return nodes(tree).find(n => n.type === 'Button' && text(n).includes(label)); }
const field = (tree, name) => nodes(tree).find(n => (n.type === 'Input' || n.type === 'Textarea' || n.type === 'input') && n.props.name === name);
const role = (tree, kind, label) => nodes(tree).find(n => n.props?.role === kind && (label === undefined || n.props['aria-label'] === label || text(n).includes(label)));
const radio = (tree, group, value) => nodes(role(tree, 'radiogroup', group)).find(n => n.props?.role === 'radio' && n.props['data-value'] === value);
const labelled = (tree, label) => nodes(tree).find(n => n.props?.['aria-label'] === label);
const choice = (tree, label) => nodes(role(tree, 'group', 'Video to play')).find(n => n.type === 'Button' && text(n).trim() === label);
const disclosure = (tree, title) => nodes(tree).find(n => n.type === 'details' && text(nodes(n.props.children).find(c => c.type === 'summary')).includes(title));
const tick = () => new Promise(resolve => setImmediate(resolve));
const type = (input, value) => input.props.onChange({ target: { value } });
const runtime = { jsx: (type, props, key) => ({ type, props: props || {}, key }), jsxs: (type, props, key) => ({ type, props: props || {}, key }) };
for (const name of ['Button', 'Input', 'Textarea', 'Badge', 'Checkbox', 'Separator', 'ScrollArea', 'GlyphSpinner']) sdk[name] = primitive(name);
let pluginModule;
async function load() {
  assert.ok(source, 'The SDK-only desktop plugin must exist');
  if (pluginModule) return pluginModule;
  globalThis.__cutroomMocks = { '@hermes/plugin-sdk': sdk, react, 'react/jsx-runtime': runtime };
  const replaced = source.replace(/import\s+\*\s+as\s+(\w+)\s+from\s+['"]([^'"]+)['"];?/g, (_, name, module) => `const ${name} = globalThis.__cutroomMocks[${JSON.stringify(module)}];`).replace(/import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"];?/g,
    (_, names, module) => `const {${names.replace(/\bas\b/g, ':')}} = globalThis.__cutroomMocks[${JSON.stringify(module)}];`);
  pluginModule = await import(`data:text/javascript;base64,${Buffer.from(replaced).toString('base64')}`);
  return pluginModule;
}

// A controllable ctx.setTimeout: autosave waits for flush().
function timerBox() {
  const timers = [];
  return {
    timers,
    setTimeout: (fn, ms) => { const entry = { fn, ms }; timers.push(entry); return () => { const i = timers.indexOf(entry); if (i >= 0) timers.splice(i, 1); }; },
    async flush() { await tick(); while (timers.length) { timers.shift().fn(); await tick(); await tick(); } await tick(); },
  };
}
const patchApplies = (_path, options) => {
  if (options?.method === 'PATCH') {
    const changes = options.body.changes;
    selectedProject = { ...selectedProject, ...changes, settings: { ...selectedProject.settings, ...(changes.settings || {}) }, revision: selectedProject.revision + 1 };
  }
  return selectedProject;
};

async function studio(rest, extra = {}, more = {}) {
  hookStores.clear(); queries.length = 0; invalidations.length = 0;
  selectedProject = { id: 'p1', name: 'Demo', revision: 7, source: 'in.mp4', settings: {}, artifacts: {}, source_info: { duration: 12 }, ...extra };
  projectRows = [selectedProject];
  const entries = [], calls = [], stored = [];
  const timer = timerBox();
  const ctx = { register: x => entries.push(x), setTimeout: timer.setTimeout,
    storage: { get: (key, fallback) => key.startsWith('lastProject') ? 'p1' : fallback, set: (key, value) => stored.push([key, value]) },
    rest: async (path, options) => { calls.push({ path, options }); return rest(path, options); }, ...more };
  (await load()).default.register(ctx);
  const route = entries.find(x => x.area === sdk.ROUTES_AREA);
  const ui = { calls, stored, ctx, timer, draw: () => draw(route), flush: () => timer.flush(),
    patches: () => calls.filter(c => c.options?.method === 'PATCH'),
    async step(label) { const tab = nodes(ui.draw()).find(n => n.props?.role === 'tab' && text(n).includes(label)); assert.ok(tab, `${label} tab`); tab.props.onClick(); await tick(); return ui.draw(); } };
  return ui;
}
const currentPreview = (revision = 7, extraJobs = []) => ({
  project: { artifacts: { preview: 'preview.mp4' }, artifact_lineage: { preview: { job_id: 'pj', platform: 'instagram_reels' } } },
  jobs: [{ id: 'pj', action: 'preview', status: 'completed', revision, progress: 1 }, ...extraJobs],
});

test('renderer rejects duplicate sibling React keys across component types but allows separate scopes', () => {
  const First = () => null;
  const Second = () => null;
  assert.throws(() => render([runtime.jsx(First, {}, 1), runtime.jsx(Second, {}, '1')]), /Duplicate sibling React key "1".*First and Second/);
  assert.doesNotThrow(() => render([
    runtime.jsx('div', { children: [runtime.jsx(First, {}, 1)] }),
    runtime.jsx('div', { children: [runtime.jsx(Second, {}, 1)] }),
    null,
    'Unkeyed text',
  ]));
});

test('registers a native route, sidebar entry, palette command and a settings page', async () => {
  const module = await load();
  const pages = [];
  const ctx = { register: record => records.push(record), registerSettingsPage: page => pages.push(page) };
  module.default.register(ctx);
  assert.equal(module.default.id, 'cutroom');
  const route = records.find(record => record.area === sdk.ROUTES_AREA);
  assert.equal(route.data.path, '/cutroom');
  assert.equal(typeof route.render, 'function');
  assert.ok(records.some(record => record.area === sdk.SIDEBAR_NAV_AREA && record.data.path === '/cutroom'));
  records.find(record => record.area === sdk.PALETTE_AREA).data.run();
  assert.equal(navigation.at(-1), '/cutroom');
  assert.equal(pages.length, 1);
  assert.equal(pages[0].title, 'Cutroom');
  // Older hosts: no settings page door and no chat renderer area; registration must not throw.
  assert.doesNotThrow(() => module.default.register({ register: () => {} }));
});

test('home imports a local path, lists recent projects in plain words and scopes cached queries', async () => {
  hookStores.clear(); queries.length = 0;
  const calls = [];
  sdk.relativeTime = ms => `at ${ms}`;
  projectRows = [{ id: 'p1', name: 'Local demo', revision: 1, source: 'input.mp4', settings: { platform: 'tiktok' }, artifacts: { preview: 'x' }, modified_at: 5 },
    { id: 'p2', name: 'Talk', revision: 1, source: 'talk.mp4', settings: {}, artifacts: {} }];
  jobRows = [{ id: 'j2', project_id: 'p2', action: 'transcribe', status: 'running', progress: 0.4 }];
  selectedProject = projectRows[0];
  const module = await load();
  const registrations = [];
  const stored = {};
  module.default.register({ register: entry => registrations.push(entry),
    storage: { get: (key, fallback) => key in stored ? stored[key] : fallback, set: (key, value) => { stored[key] = value; } },
    rest: async (path, options) => { calls.push({ path, options }); return selectedProject; } });
  const route = registrations.find(r => r.area === sdk.ROUTES_AREA);
  let tree = draw(route);
  assert.match(text(tree), /Make a video/);
  assert.match(text(tree), /Recent projects/);
  assert.match(text(button(tree, 'Local demo')), /TikTok · Ready to review · at 5000/);
  assert.match(text(button(tree, 'Talk')), /Transcribing · 40%/);
  assert.match(text(tree), /Hermes chat/);
  assert.equal(button(tree, 'Browse'), undefined, 'No folder door, no Browse button');
  const input = field(tree, 'source');
  assert.ok(input, 'Local source path input is rendered');
  type(input, 'C:/raw/demo.mp4');
  tree = draw(route);
  await button(tree, 'Import video').props.onClick();
  assert.equal(calls[0].path, '/projects');
  assert.deepEqual(calls[0].options.body, { source: 'C:/raw/demo.mp4' });
  const patches = calls.filter(c => c.options?.method === 'PATCH');
  assert.equal(patches.length, 1, 'Without saved defaults, one patch applies the default caption style');
  assert.deepEqual(patches[0].options.body.changes, { settings: { caption_style: 'highlight', captions: true } });
  tree = draw(route);
  assert.equal(field(tree, 'project.name').props.value, 'Local demo');
  assert.ok(queries.some(q => q.queryKey.includes('default') && q.queryKey.includes('project') && q.queryKey.includes('p1')));
  assert.ok(queries.some(q => q.queryKey.includes('jobs') && q.refetchInterval >= 2000));
  await button(tree, 'Projects').props.onClick();
  assert.match(text(draw(route)), /Recent projects/);
  delete sdk.relativeTime;
});

test('home Browse lists only video files from a granted folder and fills the path', async () => {
  hookStores.clear();
  projectRows = []; jobRows = [];
  const registrations = [];
  const files = {
    requestFolder: async () => ({ ok: true, folder: { id: 'f1', name: 'clips', path: 'C:/clips' } }),
    list: async (id, path) => { assert.equal(id, 'f1'); assert.equal(path, ''); return { ok: true, entries: [{ name: 'a.mp4', path: 'a.mp4', isDirectory: false }, { name: 'notes.txt', path: 'notes.txt', isDirectory: false }, { name: 'raw', path: 'raw', isDirectory: true }] }; },
  };
  (await load()).default.register({ register: entry => registrations.push(entry), files, storage: { get: (_k, f) => f, set() {} }, rest: async () => [] });
  const route = registrations.find(r => r.area === sdk.ROUTES_AREA);
  await button(draw(route), 'Browse').props.onClick();
  let tree = draw(route);
  assert.ok(button(tree, 'a.mp4'));
  assert.equal(button(tree, 'notes.txt'), undefined);
  assert.equal(button(tree, 'raw'), undefined);
  button(tree, 'a.mp4').props.onClick();
  tree = draw(route);
  assert.equal(field(tree, 'source').props.value, 'C:/clips/a.mp4');
});

test('settings page stores defaults and new Desktop projects get them with one patch', async () => {
  hookStores.clear(); jobRows = []; projectRows = [];
  const stored = {};
  const storage = { get: (key, fallback) => key in stored ? stored[key] : fallback, set: (key, value) => { stored[key] = value; } };
  const pages = [], registrations = [], calls = [];
  (await load()).default.register({ register: entry => registrations.push(entry), registerSettingsPage: page => pages.push(page), storage,
    rest: async (path, options) => { calls.push({ path, options }); return path === '/projects' ? { id: 'n1', name: 'New', revision: 1, settings: {}, artifacts: {} } : { id: 'n1', revision: 2 }; } });
  const page = { render: () => pages[0].render() };
  let tree = draw(page);
  assert.match(text(tree), /new videos/i);
  // Removing words relies on the transcript: say which speech model hears
  // short words reliably before someone cuts a word that was never said.
  assert.match(text(tree), /small.*reliabl/i);
  assert.match(text(tree), /tiny.*(invent|miss)/i);
  type(field(tree, 'default.whisper_model'), 'C:/models/ggml.bin');
  tree = draw(page);
  radio(tree, 'Default platform', 'tiktok').props.onClick();
  tree = draw(page);
  radio(tree, 'Default caption style', 'highlight').props.onClick();
  assert.deepEqual(stored.defaults, { whisper_model: 'C:/models/ggml.bin', platform: 'tiktok', caption_style: 'highlight' });
  assert.equal(radio(draw(page), 'Default platform', 'tiktok').props['aria-checked'], true);
  const route = registrations.find(r => r.area === sdk.ROUTES_AREA);
  type(field(draw(route), 'source'), 'C:/raw/new.mp4');
  await button(draw(route), 'Import video').props.onClick();
  const patches = calls.filter(c => c.options?.method === 'PATCH');
  assert.equal(patches.length, 1);
  assert.equal(patches[0].path, '/projects/n1');
  assert.deepEqual(patches[0].options.body, { revision: 1, changes: { settings: { whisper_model: 'C:/models/ggml.bin', platform: 'tiktok', caption_style: 'highlight', captions: true } } });
});

test('platform length limits read in minutes, with the recommended length', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, { settings: { platform: 'instagram_reels', aspect: 'portrait', brand: {} } });
  await ui.step('Style');
  const all = text(ui.draw());
  assert.match(all, /up to 20 min, best under 3 min/);
  assert.doesNotMatch(all, /1200 s/);
});

test('the transcript wraps: words are separated by spaces, not only by margins', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, transcriptProject());
  const list = role(ui.draw(), 'listbox', 'Transcript');
  const kids = [list.props.children].flat(Infinity).filter(kid => kid !== null && kid !== undefined && kid !== false);
  const words = kids.filter(kid => kid?.props?.role === 'option');
  assert.ok(words.length > 2);
  for (let index = 1; index < kids.length; index++) {
    if (kids[index]?.props?.role === 'option' && kids[index - 1]?.props?.role === 'option') assert.fail('Adjacent word spans without a space cannot wrap onto a new line');
  }
});

test('a new install defaults to highlighted captions, the agreed default for short videos', async () => {
  hookStores.clear(); jobRows = []; projectRows = [];
  const stored = {};
  const storage = { get: (key, fallback) => key in stored ? stored[key] : fallback, set: (key, value) => { stored[key] = value; } };
  const pages = [], registrations = [], calls = [];
  (await load()).default.register({ register: entry => registrations.push(entry), registerSettingsPage: page => pages.push(page), storage,
    rest: async (path, options) => { calls.push({ path, options }); return path === '/projects' ? { id: 'n2', name: 'New', revision: 1, settings: {}, artifacts: {} } : { id: 'n2', revision: 2 }; } });
  assert.equal(radio(draw({ render: () => pages[0].render() }), 'Default caption style', 'highlight').props['aria-checked'], true);
  const route = registrations.find(r => r.area === sdk.ROUTES_AREA);
  type(field(draw(route), 'source'), 'C:/raw/new.mp4');
  await button(draw(route), 'Import video').props.onClick();
  const patch = calls.find(c => c.options?.method === 'PATCH');
  assert.deepEqual(patch.options.body.changes.settings, { caption_style: 'highlight', captions: true });
});

test('review: reframing checks read as sentences and passed checks fold away', async () => {
  const checks = [
    { name: 'platform_upscale', status: 'warning', detail: {} },
    { name: 'framing_frames', status: 'pass' }, { name: 'framing_smoothness', status: 'pass' },
    { name: 'framing_face_safe_zone', status: 'pass' }, { name: 'framing_face_coverage', status: 'pass' },
    { name: 'decode', status: 'pass' },
  ];
  const preview = currentPreview(7, [qaJob(checks)]);
  jobRows = preview.jobs;
  const ui = await studio(async () => selectedProject, preview.project);
  await ui.step('Review');
  await tick();
  const tree = ui.draw();
  const passed = disclosure(tree, '5 checks passed');
  for (const sentence of ['The crop moves smoothly', 'The face stays in the safe area']) assert.match(text(passed), new RegExp(sentence));
  assert.doesNotMatch(text(passed), /framing_/, 'No raw check names for known checks; raw names stay under Details');
  assert.ok(passed, 'Passed checks sit in a disclosure');
  assert.match(text(passed), /The crop moves smoothly/);
  const notes = role(tree, 'list', 'Checks needing a look') || nodes(tree).find(n => n.type === 'ul' && n.props['aria-label'] === 'Checks needing a look');
  assert.ok(notes && /enlarged from a smaller source/.test(text(notes)), 'Notes stay visible');
});

test('autosave waits for a pause, sends one revision-checked patch and shows the save state', async () => {
  jobRows = [];
  const ui = await studio(patchApplies);
  let tree = ui.draw();
  type(field(tree, 'project.name'), 'Demo t');
  type(field(ui.draw(), 'project.name'), 'Demo take 2');
  tree = ui.draw();
  assert.equal(ui.patches().length, 0, 'Nothing is sent while typing');
  assert.match(text(role(tree, 'status', 'Saving…')), /Saving…/);
  assert.equal(ui.timer.timers.at(-1).ms, 500);
  assert.equal(ui.timer.timers.length, 1, 'Each keystroke restarts one debounce timer');
  await ui.flush();
  assert.equal(ui.patches().length, 1);
  assert.deepEqual(ui.patches()[0].options.body, { revision: 7, changes: { name: 'Demo take 2' } });
  tree = ui.draw();
  assert.match(text(tree), /Saved/);
  assert.equal(field(tree, 'project.name').props.value, 'Demo take 2');
  assert.equal(nodes(tree).find(n => n.type === 'Button' && /^Save\b/.test(text(n).trim())), undefined, 'No Save buttons');
  assert.ok(nodes(tree).some(n => n.props?.role === 'status' && n.props['aria-live'] === 'polite'));
});

test('a failed save keeps the edit, shows an inline error and Retry sends it again', async () => {
  jobRows = [];
  let fail = true;
  const ui = await studio(async (path, options) => {
    if (options?.method === 'PATCH' && fail) throw new Error('Backend offline');
    return patchApplies(path, options);
  });
  type(field(ui.draw(), 'project.name'), 'Renamed');
  await ui.flush();
  let tree = ui.draw();
  assert.match(text(tree), /Couldn't save/);
  assert.match(text(nodes(tree).find(n => n.props?.role === 'alert')), /Backend offline/);
  assert.equal(field(tree, 'project.name').props.value, 'Renamed', 'The edit is not dropped');
  fail = false;
  await button(tree, 'Retry').props.onClick();
  await ui.flush();
  assert.equal(ui.patches().length, 2);
  assert.deepEqual(ui.patches()[1].options.body, { revision: 7, changes: { name: 'Renamed' } });
  assert.match(text(ui.draw()), /Saved/);
});

test('undo restores the previous value through a patch, from the button and from Ctrl+Z', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, { settings: { platform: 'instagram_reels', captions: true } });
  let tree = await ui.step('Style');
  assert.equal(button(tree, 'Undo').props.disabled, true);
  radio(tree, 'Platform', 'tiktok').props.onClick();
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.platform, 'tiktok');
  tree = ui.draw();
  assert.equal(button(tree, 'Undo').props.disabled, false);
  await button(tree, 'Undo').props.onClick();
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.platform, 'instagram_reels');
  assert.equal(ui.patches().at(-1).options.body.revision, 8);
  radio(ui.draw(), 'Platform', 'youtube_shorts').props.onClick();
  await ui.flush();
  const workspace = () => labelled(ui.draw(), 'Project editing workspace');
  let prevented = false;
  workspace().props.onKeyDown({ key: 'z', ctrlKey: true, target: { tagName: 'INPUT' }, preventDefault() { prevented = true; } });
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.platform, 'youtube_shorts', 'Ctrl+Z inside a text field stays native');
  assert.equal(prevented, false);
  workspace().props.onKeyDown({ key: 'z', ctrlKey: true, target: { tagName: 'DIV' }, preventDefault() { prevented = true; } });
  await ui.flush();
  assert.equal(prevented, true);
  assert.equal(ui.patches().at(-1).options.body.changes.settings.platform, 'instagram_reels');
});

const transcriptProject = () => ({ source_info: { duration: 12 }, base_segments: [{ start: 0, end: 12 }], segments: [{ start: 0, end: 12 }], excluded_word_ids: [],
  transcript: { words: [{ id: 'w1', text: 'My', start: 0, end: 0.3 }, { id: 'w2', text: 'name', start: 0.3, end: 0.6 }, { id: 'w3', text: 'is', start: 0.6, end: 0.8 },
    { id: 'w4', text: 'when', start: 1.0, end: 1.2 }, { id: 'w5', text: 'when', start: 1.3, end: 1.5 }, { id: 'w6', text: 'I', start: 2.5, end: 2.6 }] } });
const word = (tree, id) => nodes(tree).find(n => n.props?.role === 'option' && n.props['data-word-id'] === id);

test('transcript: click seeks, drag and Shift-click select, Delete removes and Restore brings words back', async () => {
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  URL.createObjectURL = () => 'blob:words'; URL.revokeObjectURL = () => {};
  try {
    jobRows = [];
    const ui = await studio(async (path, options) => path.includes('/media/') ? { data: btoa('abc'), offset: 0, next_offset: 3, total: 3, mime: 'video/mp4', version: 'v1' } : patchApplies(path, options), transcriptProject());
    let tree = ui.draw();
    assert.ok(role(tree, 'listbox', 'Transcript'));
    await choice(tree, 'Original').props.onClick();
    tree = ui.draw();
    const fake = { currentTime: 0, paused: true, play() { this.paused = false; }, pause() { this.paused = true; } };
    nodes(tree).find(n => n.type === 'video').props.ref.current = fake;
    word(tree, 'w2').props.onClick({ shiftKey: false });
    assert.equal(fake.currentTime, 0.3, 'Clicking a word seeks the source');
    word(ui.draw(), 'w4').props.onClick({ shiftKey: true });
    tree = ui.draw();
    assert.deepEqual(['w1', 'w2', 'w3', 'w4', 'w5'].map(id => word(tree, id).props['aria-selected']), [false, true, true, true, false]);
    // Drag from w5 to w6 replaces the selection.
    word(tree, 'w5').props.onMouseDown({ shiftKey: false, button: 0 });
    word(ui.draw(), 'w6').props.onMouseEnter();
    word(ui.draw(), 'w6').props.onClick({ shiftKey: false });
    tree = ui.draw();
    assert.deepEqual(['w4', 'w5', 'w6'].map(id => word(tree, id).props['aria-selected']), [false, true, true]);
    role(tree, 'listbox', 'Transcript').props.onKeyDown({ key: 'Delete', preventDefault() {} });
    await ui.flush();
    assert.deepEqual(ui.patches().at(-1).options.body, { revision: 7, changes: { excluded_word_ids: ['w5', 'w6'] } });
    tree = ui.draw();
    assert.match(String(word(tree, 'w5').props.style.textDecoration), /line-through/);
    assert.match(word(tree, 'w5').props['aria-label'], /removed/);
    word(tree, 'w6').props.onClick({ shiftKey: false });
    tree = ui.draw();
    assert.ok(button(tree, 'Restore'), 'All selected words are removed, so the action restores');
    await button(tree, 'Restore').props.onClick();
    await ui.flush();
    assert.deepEqual(ui.patches().at(-1).options.body.changes, { excluded_word_ids: ['w5'] });
    word(ui.draw(), 'w1').props.onClick({ shiftKey: false });
    await button(ui.draw(), 'Remove').props.onClick();
    await ui.flush();
    assert.deepEqual(ui.patches().at(-1).options.body.changes, { excluded_word_ids: ['w5', 'w1'] });
    // Keyboard: arrows move, Shift extends, Backspace removes.
    const list = () => role(ui.draw(), 'listbox', 'Transcript');
    list().props.onKeyDown({ key: 'ArrowRight', shiftKey: false, preventDefault() {} });
    list().props.onKeyDown({ key: 'ArrowRight', shiftKey: true, preventDefault() {} });
    list().props.onKeyDown({ key: 'Backspace', preventDefault() {} });
    await ui.flush();
    assert.deepEqual(ui.patches().at(-1).options.body.changes, { excluded_word_ids: ['w5', 'w1', 'w2', 'w3'] });
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; }
});

test('double-click fixes a word without touching its timing or the exclusions', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, { ...transcriptProject(), transcript: { language: 'en', words: [{ id: 0, text: 'Helo', start: 1, end: 2, probability: 0.9 }, { id: 1, text: 'world', start: 3, end: 4, probability: 0.8 }] }, excluded_word_ids: [1] });
  word(ui.draw(), '0').props.onDoubleClick();
  const input = field(ui.draw(), 'fix.0');
  assert.ok(input, 'Inline word fix');
  type(input, '');
  assert.match(text(ui.draw()), /cannot be empty/);
  type(field(ui.draw(), 'fix.0'), 'Hello');
  await ui.flush();
  const patches = ui.patches();
  assert.equal(patches.length, 1);
  const changes = patches[0].options.body.changes;
  assert.equal(changes.transcript.words[0].text, 'Hello');
  assert.equal(changes.transcript.words[0].probability, 0.9);
  assert.equal(changes.transcript.words[1].id, 1);
  assert.equal(changes.excluded_word_ids, undefined);
  assert.ok(button(ui.draw(), 'Fix a word') || /Double-click/.test(text(ui.draw())));
});

test('suggests long pauses and repeated words; Apply, Keep and Apply all', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, transcriptProject());
  const box = () => labelled(ui.draw(), 'Suggestions');
  assert.ok(box(), 'Suggestions are listed');
  assert.match(text(box()), /Repeated word “when when”/);
  assert.match(text(box()), /Long pause, 1\.0 s, before “I”/);
  const row = label => nodes(box()).find(n => n.props?.['data-suggestion'] && text(n).includes(label));
  await button(row('Repeated'), 'Apply').props.onClick();
  await ui.flush();
  assert.deepEqual(ui.patches().at(-1).options.body.changes, { excluded_word_ids: ['w4'] });
  assert.doesNotMatch(text(box()), /Repeated/);
  button(row('Long pause'), 'Keep').props.onClick();
  assert.ok(ui.stored.some(([key, value]) => key === 'dismissed:p1' && value.some(k => k.startsWith('pause:'))), 'Kept suggestions are remembered');
  assert.equal(box(), undefined);
  // Apply all cuts every remaining suggestion in one patch.
  const fresh = await studio(patchApplies, transcriptProject());
  await button(labelled(fresh.draw(), 'Suggestions'), 'Apply all').props.onClick();
  await fresh.flush();
  assert.equal(fresh.patches().length, 1);
  const changes = fresh.patches()[0].options.body.changes;
  assert.deepEqual(changes.excluded_word_ids, ['w4']);
  assert.deepEqual(changes.segments, [{ start: 0, end: 1.65 }, { start: 2.35, end: 12 }]);
});

test('empty transcript offers Transcribe; rarely used tools live under More tools', async () => {
  jobRows = [];
  const ui = await studio(async () => ({ id: 'j1' }));
  const tree = ui.draw();
  assert.match(text(tree), /no transcript yet/i);
  await button(tree, 'Transcribe').props.onClick();
  assert.deepEqual(ui.calls.at(-1), { path: '/projects/p1/jobs', options: { method: 'POST', body: { action: 'transcribe', options: {} } } });
  const more = disclosure(ui.draw(), 'More tools');
  assert.ok(more, 'More tools disclosure');
  for (const label of ['Story', 'Face analysis', 'Background layer', 'Framing pins', 'Project model paths', 'Cut by time']) assert.match(text(more), new RegExp(label));
  for (const name of ['whisper_model', 'face_model', 'segmentation_model', 'brief']) assert.ok(field(more, name), name);
});

test('keeps one word-fix list and one model-path form through revisions 1, 2 and 3', async () => {
  jobRows = [];
  const ui = await studio(async () => selectedProject, { revision: 1, transcript: { words: [{ id: 'w1', text: 'Caption 1', start: 0, end: 1 }] }, base_segments: [{ start: 0, end: 12 }], settings: { whisper_model: 'm1' } });
  for (const revision of [1, 2, 3]) {
    selectedProject = { ...selectedProject, revision, transcript: { words: [{ id: 'w1', text: `Caption ${revision}`, start: 0, end: 1 }] }, base_segments: [{ start: 0, end: 13 - revision }], settings: { whisper_model: `m${revision}` } };
    const tree = ui.draw();
    assert.equal(nodes(tree).filter(n => n.type === 'Input' && n.props.name === 'caption.w1').length, 1, `One fix field at revision ${revision}`);
    assert.equal(field(tree, 'caption.w1').props.value, `Caption ${revision}`);
    assert.equal(field(tree, 'range.0.end').props.value, String(13 - revision));
    assert.equal(field(tree, 'whisper_model').props.value, `m${revision}`);
  }
});

test('edits manual ranges and brand values with validation, without Save buttons', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, { base_segments: [{ start: 1, end: 8 }], segments: [{ start: 1, end: 8 }] });
  type(field(ui.draw(), 'range.0.end'), '7');
  await ui.flush();
  assert.deepEqual(ui.patches().at(-1).options.body.changes, { segments: [{ start: 1, end: 7 }] });
  type(field(ui.draw(), 'range.0.end'), '30');
  await ui.flush();
  assert.equal(ui.patches().length, 1, 'A range outside the source is refused');
  assert.match(text(ui.draw()), /inside the source/);
  type(field(ui.draw(), 'brand.title_size'), '2');
  await ui.flush();
  assert.equal(ui.patches().length, 1);
  assert.match(text(ui.draw()), /12.*120/);
  type(field(ui.draw(), 'brand.title_size'), '48');
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.brand.title_size, 48);
});

test('submits allowlisted jobs, shows plain activity with a themed bar, cancels and retries', async () => {
  jobRows = [{ id: 'j1', action: 'vision', status: 'running', progress: 0.25 }, { id: 'j2', action: 'transcribe', status: 'failed', error: 'Missing model', options: {} }];
  const ui = await studio(async () => ({ id: 'new-job' }));
  const tree = ui.draw();
  const activity = labelled(tree, 'Activity');
  assert.equal(activity.props['aria-live'], 'polite');
  assert.match(text(activity), /Analysing faces/);
  assert.match(text(activity), /25%/);
  assert.match(text(tree), /Missing model/);
  const bar = nodes(activity).find(n => n.props?.role === 'progressbar');
  assert.equal(bar.props['aria-valuenow'], 25);
  assert.match(JSON.stringify(nodes(bar).map(n => n.props?.style)), /var\(--ui-accent\)/);
  assert.equal(nodes(tree).find(n => n.type === 'progress'), undefined, 'No native progress element');
  await button(activity, 'Cancel').props.onClick();
  assert.equal(ui.calls.at(-1).path, '/jobs/j1/cancel');
  await button(labelled(ui.draw(), 'Activity'), 'Try again').props.onClick();
  assert.equal(ui.calls.at(-1).options.body.action, 'transcribe');
  assert.ok(invalidations.length >= 2);
  assert.ok(queries.some(q => q.queryKey.includes('jobs') && q.refetchInterval >= 2000));
  assert.doesNotMatch(source, /'publish'|"publish"/);
});

test('submits only supported job options and rejects invalid pause-finder input', async () => {
  jobRows = [];
  const ui = await studio(async () => ({ id: 'j1' }), transcriptProject());
  const input = name => field(ui.draw(), name);
  assert.ok(input('job.language'));
  type(input('job.language'), 'en');
  await button(ui.draw(), 'Transcribe again').props.onClick();
  assert.deepEqual(ui.calls.at(-1).options.body, { action: 'transcribe', options: { language: 'en' } });
  type(input('job.noise_db'), '-32');
  type(input('job.min_duration'), '0.5');
  await button(ui.draw(), 'Find pauses').props.onClick();
  assert.deepEqual(ui.calls.at(-1).options.body.options, { noise_db: -32, min_duration: 0.5 });
  type(input('job.min_duration'), '-1');
  const before = ui.calls.length;
  await button(ui.draw(), 'Find pauses').props.onClick();
  assert.equal(ui.calls.length, before);
  assert.match(text(ui.draw()), /positive/);
  assert.equal(input('job.model_path'), undefined, 'Model paths come from saved settings only');
  type(input('job.language'), 'English');
  await button(ui.draw(), 'Transcribe again').props.onClick();
  assert.equal(ui.calls.length, before);
  assert.match(text(ui.draw()), /two- or three-letter/);
});

test('keeps polling job and project state in the background only while work is active', async () => {
  jobRows = [{ id: 'j1', action: 'final', status: 'running', revision: 7, progress: 0.4 }];
  const ui = await studio(async () => selectedProject);
  ui.draw();
  queries.length = 0;
  ui.draw();
  const active = queries.filter(q => q.queryKey.includes('jobs') || q.queryKey.includes('project'));
  assert.ok(active.length >= 2);
  for (const q of active) assert.equal(q.refetchIntervalInBackground, true);
  jobRows = [{ id: 'j1', action: 'final', status: 'completed', revision: 7, progress: 1 }];
  ui.draw();
  queries.length = 0;
  ui.draw();
  for (const q of queries.filter(q => q.queryKey.includes('jobs') || q.queryKey.includes('project'))) assert.notEqual(q.refetchIntervalInBackground, true);
});

test('notifies natively when a preview finishes, feature-detected and throttled', async () => {
  const notes = [];
  jobRows = [{ id: 'p', action: 'preview', status: 'running', revision: 7, progress: 0.5 }, { id: 't', action: 'transcribe', status: 'running', revision: 7, progress: 0.5 }];
  const ui = await studio(async () => selectedProject, {}, { os: { notify: note => notes.push(note) } });
  ui.draw();
  jobRows = [{ id: 'p', action: 'preview', status: 'completed', revision: 7, progress: 1 }, { id: 't', action: 'transcribe', status: 'completed', revision: 7, progress: 1 }];
  ui.draw();
  assert.equal(notes.length, 1, 'Two finishes at once give one notification');
  assert.match(notes[0].title, /Preview is ready|Transcript is ready/);
  jobRows = [{ id: 'x', action: 'preview', status: 'running', revision: 7 }];
  const quiet = await studio(async () => selectedProject);
  quiet.draw();
  jobRows = [{ id: 'x', action: 'preview', status: 'completed', revision: 7 }];
  assert.doesNotThrow(() => quiet.draw(), 'Hosts without ctx.os still work');
});

test('review without a current preview offers Make preview, then checks it automatically', async () => {
  jobRows = [];
  const ui = await studio(async (path, options) => options?.method === 'POST' ? { id: options.body.action === 'preview' ? 'new-preview' : 'new-qa' } : selectedProject);
  const tree = await ui.step('Review');
  assert.match(text(tree), /no preview of this version yet/i);
  await button(tree, 'Make preview').props.onClick();
  assert.deepEqual(ui.calls.at(-1).options.body, { action: 'preview', options: {} });
  jobRows = [{ id: 'new-preview', action: 'preview', status: 'running', revision: 7, progress: 0.3 }];
  ui.draw();
  jobRows = [{ id: 'new-preview', action: 'preview', status: 'completed', revision: 7, progress: 1 }];
  ui.draw(); await tick();
  assert.deepEqual(ui.calls.at(-1).options.body, { action: 'qa', options: {} });
  // An older preview of another revision is not reviewable.
  const stale = currentPreview(6);
  jobRows = stale.jobs;
  const old = await studio(async () => selectedProject, stale.project);
  assert.match(text(await old.step('Review')), /changed the video since the last preview/i);
});

const qaJob = checks => ({ id: 'qj', action: 'qa', status: 'completed', revision: 7, upstream: 'preview', result: { passed: false, video: 'preview', checks } });

test('face tracking without a face analysis: Make preview analyses faces first, then previews and checks', async () => {
  jobRows = [];
  const ui = await studio(async (path, options) => options?.method === 'POST' ? { id: `new-${options.body.action}` } : selectedProject,
    { settings: { framing: 'face_track', aspect: 'portrait' } });
  const tree = await ui.step('Review');
  assert.match(text(tree), /analys\w* faces/i);
  await button(tree, 'Make preview').props.onClick();
  assert.deepEqual(ui.calls.at(-1).options.body, { action: 'vision', options: {} });
  jobRows = [{ id: 'new-vision', action: 'vision', status: 'completed', revision: 7, progress: 1 }];
  ui.draw(); await tick();
  assert.deepEqual(ui.calls.at(-1).options.body, { action: 'preview', options: {} });
  jobRows = [...jobRows, { id: 'new-preview', action: 'preview', status: 'completed', revision: 7, progress: 1 }];
  ui.draw(); await tick();
  assert.deepEqual(ui.calls.at(-1).options.body, { action: 'qa', options: {} });
});

test('host errors read as one plain sentence and stay on the step where they happened', async () => {
  jobRows = [];
  const detail = 'No speech model found. Put a Whisper model folder such as faster-whisper-small in C:/w/models.';
  const ui = await studio(async (path, options) => {
    if (options?.method === 'POST') throw new Error(`Error invoking remote method 'hermes:api': Error: 422: ${JSON.stringify({ detail })}`);
    return selectedProject;
  });
  await button(ui.draw(), 'Transcribe').props.onClick();
  await tick();
  const shown = text(ui.draw());
  assert.match(shown, /No speech model found/);
  assert.doesNotMatch(shown, /Error invoking|hermes:api|422|\{"detail/);
  assert.doesNotMatch(text(await ui.step('Style')), /No speech model found/);
});

test('caption style cards show the same neutral sample in every project', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, transcriptProject());
  const all = text(await ui.step('Style'));
  assert.doesNotMatch(all, /Guyana|I came from/);
  assert.match(all, /Your words/);
});

test('review headline comes from check statuses: warnings only is ready with notes and can still be approved', async () => {
  const digest = 'e'.repeat(64);
  const preview = currentPreview(7, [qaJob([{ name: 'platform_upscale', status: 'warning', detail: {} }, { name: 'decode', status: 'pass' }, { name: 'mystery_check', status: 'pass' }, { name: 'audio', status: 'skip' }])]);
  jobRows = preview.jobs;
  const ui = await studio(async path => {
    if (path.endsWith('/review')) return { digest, project: selectedProject, notice: 'Review every cut' };
    if (path.endsWith('/approve')) { selectedProject = { ...selectedProject, approval: { digest, revision: 7 }, status: 'approved' }; return selectedProject; }
    return selectedProject;
  }, preview.project);
  await ui.step('Review');
  await tick();
  const tree = ui.draw();
  assert.match(text(tree), /Ready, with 1 note/);
  assert.doesNotMatch(text(tree), /Needs attention/);
  assert.match(text(tree), /enlarged from a smaller source, so it may look slightly softer/);
  assert.match(text(tree), /mystery_check/, 'Unknown checks show their name');
  const details = disclosure(tree, 'Details');
  assert.match(text(details), new RegExp(digest));
  assert.match(text(details), /Version 7/);
  const panel = role(tree, 'tabpanel');
  const primary = text(panel).replace(text(details), '');
  assert.doesNotMatch(primary, /digest|segment|vision job/i, 'No jargon in the primary review copy');
  const box = nodes(tree).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'I watched this preview and want to export exactly this version');
  assert.ok(box);
  assert.equal(button(tree, 'Approve this version').props.disabled, true);
  box.props.onCheckedChange(true);
  await button(ui.draw(), 'Approve this version').props.onClick();
  assert.deepEqual(ui.calls.find(c => c.path.endsWith('/approve')).options.body, { digest, confirmed: true });
  assert.match(text(ui.draw()), /Approved/);
  // Any failed check changes the headline.
  jobRows = currentPreview(7, [qaJob([{ name: 'platform_upscale', status: 'warning' }, { name: 'safe_zone', status: 'fail' }])]).jobs;
  const failing = await studio(async path => path.endsWith('/review') ? { digest, project: selectedProject, notice: '' } : selectedProject, preview.project);
  await failing.step('Review'); await tick();
  assert.match(text(failing.draw()), /Needs attention/);
});

test('requires exact human confirmation, rereads review and blocks stale approval callbacks', async () => {
  const preview = currentPreview();
  jobRows = preview.jobs;
  const digest = 'a'.repeat(64);
  let changed = false;
  const ui = await studio(async (path, options) => {
    if (path.endsWith('/review')) return { digest: changed ? 'b'.repeat(64) : digest, project: selectedProject, notice: 'Review every cut' };
    if (path.endsWith('/approve')) { selectedProject = { ...selectedProject, approval: { digest, revision: 7 } }; return selectedProject; }
    if (options?.method === 'POST') return { id: 'job' };
    return selectedProject;
  }, preview.project);
  let tree = await ui.step('Export');
  assert.equal(button(tree, 'Export final video').props.disabled, true, 'Export waits for approval');
  assert.match(text(tree), /Approve this version in Review/);
  await ui.step('Review');
  await tick();
  tree = ui.draw();
  assert.match(text(tree), /Review every cut/);
  assert.equal(button(tree, 'Approve this version').props.disabled, true);
  const confirm = () => nodes(ui.draw()).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'I watched this preview and want to export exactly this version');
  confirm().props.onCheckedChange(true);
  await button(ui.draw(), 'Approve this version').props.onClick();
  assert.deepEqual(ui.calls.find(c => c.path.endsWith('/approve')).options.body, { digest, confirmed: true });
  tree = await ui.step('Export');
  assert.equal(button(tree, 'Export final video').props.disabled, false);
  const staleFinal = button(tree, 'Export final video').props.onClick;
  labelled(tree, 'Project editing workspace').props.onChangeCapture();
  await staleFinal();
  assert.ok(!ui.calls.some(c => c.options?.body?.action === 'final'));
  assert.equal(button(ui.draw(), 'Export final video').props.disabled, true);
  await ui.step('Review');
  await button(disclosure(ui.draw(), 'Details'), 'Check again').props.onClick();
  confirm().props.onCheckedChange(true);
  changed = true;
  const before = ui.calls.filter(c => c.path.endsWith('/approve')).length;
  await button(ui.draw(), 'Approve this version').props.onClick();
  assert.equal(ui.calls.filter(c => c.path.endsWith('/approve')).length, before);
  assert.match(text(ui.draw()), /changed/i);
});

test('any edit clears approval, and export runs final then cover then the report', async () => {
  const preview = currentPreview();
  jobRows = preview.jobs;
  const digest = 'f'.repeat(64);
  const ui = await studio(async (path, options) => {
    if (path.endsWith('/review')) return { digest, project: selectedProject, notice: '' };
    if (path.endsWith('/approve')) { selectedProject = { ...selectedProject, approval: { digest, revision: 7 } }; return selectedProject; }
    if (options?.method === 'POST') return { id: `job-${options.body.action}` };
    return patchApplies(path, options);
  }, { ...preview.project, ...transcriptProject() });
  await ui.step('Review'); await tick();
  nodes(ui.draw()).find(n => n.type === 'Checkbox' && n.props['aria-label']?.startsWith('I watched')).props.onCheckedChange(true);
  await button(ui.draw(), 'Approve this version').props.onClick();
  let tree = await ui.step('Export');
  await button(tree, 'Export final video').props.onClick();
  assert.deepEqual(ui.calls.at(-1).options.body, { action: 'final', options: {} });
  jobRows = [...preview.jobs, { id: 'job-final', action: 'final', status: 'running', revision: 7, progress: 0.5 }];
  ui.draw();
  jobRows = [...preview.jobs, { id: 'job-final', action: 'final', status: 'completed', revision: 7, progress: 1 }];
  ui.draw(); await tick();
  assert.equal(ui.calls.at(-1).options.body.action, 'cover');
  jobRows = [...jobRows, { id: 'job-cover', action: 'cover', status: 'completed', revision: 7 }];
  ui.draw(); await tick();
  assert.equal(ui.calls.at(-1).options.body.action, 'qa');
  // A transcript edit clears approval.
  tree = await ui.step('Edit');
  word(tree, 'w1').props.onClick({ shiftKey: false });
  await button(ui.draw(), 'Remove').props.onClick();
  tree = await ui.step('Export');
  assert.equal(button(tree, 'Export final video').props.disabled, true);
});

test('restores a saved approval only after rereading the same review', async () => {
  const preview = currentPreview();
  jobRows = preview.jobs;
  const digest = 'c'.repeat(64);
  const ui = await studio(async path => path.endsWith('/review') ? { digest, project: selectedProject, notice: '' } : selectedProject,
    { ...preview.project, status: 'approved', approval: { digest, revision: 7 } });
  await ui.step('Export'); await tick();
  assert.equal(button(ui.draw(), 'Export final video').props.disabled, false);
  assert.ok(!ui.calls.some(c => c.path.endsWith('/approve')), 'Restoring never approves');
  const other = await studio(async path => path.endsWith('/review') ? { digest: 'd'.repeat(64), project: selectedProject, notice: '' } : selectedProject,
    { ...preview.project, status: 'approved', approval: { digest, revision: 7 } });
  await other.step('Export'); await tick();
  assert.equal(button(other.draw(), 'Export final video').props.disabled, true, 'A different digest is not approved');
});

test('draws a visible outline on every unchecked checkbox, including the approval box', async () => {
  const preview = currentPreview();
  jobRows = preview.jobs;
  const ui = await studio(async path => path.endsWith('/review') ? { digest: 'c'.repeat(64), project: selectedProject, notice: 'Review every cut' } : selectedProject, preview.project);
  await ui.step('Review'); await tick();
  const boxes = nodes(ui.draw()).filter(n => n.type === 'Checkbox');
  assert.ok(boxes.some(n => n.props['aria-label'] === 'I watched this preview and want to export exactly this version'));
  for (const box of boxes) {
    if (box.props.checked) continue;
    assert.match(String(box.props.style?.borderColor || ''), /^var\(--ui-/, `${box.props['aria-label'] || 'checkbox'} needs a themed visible border`);
  }
});

test('loads authenticated versioned media chunks, rejects oversize media and revokes URLs', async () => {
  const created = [], revoked = [];
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  URL.createObjectURL = blob => { created.push(blob); return `blob:test-${created.length}`; };
  URL.revokeObjectURL = url => revoked.push(url);
  try {
    jobRows = [];
    let oversize = false;
    const ui = await studio(async path => {
      if (path.includes('/media/')) {
        const offset = Number(new URL(path, 'https://test').searchParams.get('offset') || 0);
        return { data: btoa('abc'), offset, next_offset: offset + 3, total: oversize ? 268435457 : 6, mime: 'video/mp4', version: 'v1' };
      }
      return selectedProject;
    }, { artifacts: { preview: 'backend-only.mp4', final: 'final.mp4' } });
    assert.ok(choice(ui.draw(), 'Original'));
    await choice(ui.draw(), 'Preview').props.onClick();
    const tree = ui.draw();
    assert.equal(nodes(tree).find(n => n.type === 'video').props.src, 'blob:test-1');
    assert.equal(created[0].size, 6);
    assert.ok(ui.calls.some(c => c.path.includes('version=v1')));
    assert.equal(choice(tree, 'Preview').props['aria-pressed'], true);
    // Switching to another video revokes the URL of the previous one.
    await choice(tree, 'Original').props.onClick();
    assert.deepEqual(revoked, ['blob:test-1']);
    oversize = true;
    const before = ui.calls.length;
    await choice(ui.draw(), 'Final').props.onClick();
    assert.equal(ui.calls.length, before + 1);
    assert.match(text(ui.draw()), /256 MiB/);
    assert.equal(created.length, 2);
    assert.deepEqual(revoked, ['blob:test-1', 'blob:test-2']);
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; }
});

test('space plays and pauses unless focus is in a text field', async () => {
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  URL.createObjectURL = () => 'blob:space'; URL.revokeObjectURL = () => {};
  try {
    jobRows = [];
    const ui = await studio(async path => path.includes('/media/') ? { data: btoa('abc'), offset: 0, next_offset: 3, total: 3, mime: 'video/mp4', version: 'v1' } : selectedProject);
    await choice(ui.draw(), 'Original').props.onClick();
    const fake = { paused: true, play() { this.paused = false; }, pause() { this.paused = true; } };
    nodes(ui.draw()).find(n => n.type === 'video').props.ref.current = fake;
    const workspace = () => labelled(ui.draw(), 'Project editing workspace');
    workspace().props.onKeyDown({ key: ' ', target: { tagName: 'INPUT' }, preventDefault() {} });
    assert.equal(fake.paused, true);
    workspace().props.onKeyDown({ key: ' ', target: { tagName: 'DIV' }, preventDefault() {} });
    assert.equal(fake.paused, false);
    workspace().props.onKeyDown({ key: ' ', target: { tagName: 'DIV' }, preventDefault() {} });
    assert.equal(fake.paused, true);
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; }
});

test('downloads canonical artifacts through a read-scoped native save action', async () => {
  const saves = [], order = [];
  jobRows = [];
  sdk.captureGatewayFileDownload = () => { order.push('capture'); return async (...args) => saves.push(args); };
  const ui = await studio(async path => { order.push(path); return { path: 'server/persisted/result.srt', name: 'result.srt', mime: 'text/plain', size: 12, version: 'v1' }; }, { artifacts: { captions_srt: 'x', captions_vtt: 'x', quality: 'x', cover: 'x' } });
  const tree = await ui.step('Export');
  order.length = 0;
  await button(tree, 'Download SRT').props.onClick();
  assert.deepEqual(order, ['capture', '/projects/p1/artifact-info/captions_srt']);
  assert.deepEqual(saves, [['server/persisted/result.srt', 'result.srt']]);
  for (const label of ['Download VTT', 'Download report', 'Download cover']) assert.equal(button(ui.draw(), label).props.disabled, false);
  assert.equal(button(ui.draw(), 'Download video').props.disabled, true);
  delete sdk.captureGatewayFileDownload;
  await button(ui.draw(), 'Download VTT').props.onClick();
  assert.match(text(ui.draw()), /does not support native downloads/);
});

test('scopes cached studio data to the connection as well as the profile', async () => {
  jobRows = [];
  connectionId = 'host-a';
  (await studio(async () => selectedProject)).draw();
  assert.ok(queries.length && queries.every(q => q.queryKey.includes('host-a')), 'Every query key includes the connection');
  connectionId = 'host-b';
  (await studio(async () => selectedProject)).draw();
  assert.ok(queries.length && queries.every(q => q.queryKey.includes('host-b') && !q.queryKey.includes('host-a')));
  connectionId = 'host-a';
});

test('guides the hook choice before building the selected storyboard', async () => {
  jobRows = [];
  const hooks = [{ text: 'One', start: 0, end: 1 }, { text: 'Two', start: 1, end: 2 }, { text: 'Three', start: 2, end: 3 }];
  let ui = await studio(async () => selectedProject, { story: { hooks, storyboard: [], status: 'awaiting_hook_selection', selected_hook: null } });
  assert.match(text(ui.draw()), /Choose a hook, then run Storyboard again/);
  ui = await studio(async () => selectedProject, { selected_hook: 1, story: { hooks, storyboard: [], selected_hook: null } });
  assert.match(text(ui.draw()), /Run Storyboard to build scenes for hook 2/);
  ui = await studio(patchApplies, { selected_hook: 1, story: { hooks, storyboard: [{ source_start: 0, source_end: 1, text: 'One' }], selected_hook: 1, opening_hook: hooks[1] } });
  assert.match(text(ui.draw()), /Opening hook: Two/);
  await button(ui.draw(), 'Use hook 3').props.onClick();
  await ui.flush();
  assert.deepEqual(ui.patches().at(-1).options.body.changes, { selected_hook: 2 });
  assert.match(text(ui.draw()), /not verified eye contact/i);
});

test('keeps the project fresh after a job finishes and releases render URLs on revision changes', async () => {
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  const revoked = [];
  let count = 0;
  URL.createObjectURL = () => `blob:revision-${++count}`;
  URL.revokeObjectURL = value => revoked.push(value);
  try {
    jobRows = [{ id: 'done', action: 'preview', status: 'completed', progress: 1 }];
    const ui = await studio(async () => ({ data: btoa('abc'), offset: 0, next_offset: 3, total: 3, mime: 'video/mp4', version: 'v1' }), { artifacts: { preview: 'p.mp4' } });
    ui.draw();
    assert.ok(queries.some(query => query.queryKey.includes('project') && query.enabled && query.refetchInterval >= 2000), 'Completion must not stop project refresh before artifacts arrive');
    await choice(ui.draw(), 'Preview').props.onClick();
    ui.draw();
    selectedProject = { ...selectedProject, revision: 8 };
    ui.draw();
    assert.deepEqual(revoked, ['blob:revision-1']);
    assert.equal(nodes(ui.draw()).find(n => n.type === 'video'), undefined);
    // The source never changes with a revision, so editing does not stop it.
    await choice(ui.draw(), 'Original').props.onClick();
    ui.draw();
    selectedProject = { ...selectedProject, revision: 9 };
    ui.draw();
    assert.deepEqual(revoked, ['blob:revision-1']);
    assert.equal(nodes(ui.draw()).find(n => n.type === 'video').props.src, 'blob:revision-2');
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; }
});

test('chooses a platform card and final size, with keyboard arrows in the radio group', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, { settings: { aspect: 'source', brand: {} } });
  let tree = await ui.step('Style');
  assert.ok(queries.some(q => q.queryKey.includes('platforms')), 'Profiles come from the API');
  const group = role(tree, 'radiogroup', 'Platform');
  assert.equal(nodes(group).filter(n => n.props?.role === 'radio').length, 5, 'One card per profile including custom');
  assert.match(source, /`platform:\$\{item\.name\}`/, 'Platform cards use namespaced keys');
  assert.equal(radio(tree, 'Platform', 'custom').props['aria-checked'], true);
  assert.equal(radio(tree, 'Final size', '2160').props.disabled, true, 'Resolution only applies to platform profiles');
  radio(tree, 'Platform', 'youtube_shorts').props.onClick();
  tree = ui.draw();
  assert.match(text(tree), /1080 × 1920/);
  assert.match(text(tree), /up to 3 min/);
  radio(tree, 'Final size', '2160').props.onClick();
  await ui.flush();
  const saved = ui.patches().at(-1).options.body.changes.settings;
  assert.equal(saved.platform, 'youtube_shorts');
  assert.equal(saved.final_resolution, '2160');
  assert.equal(saved.aspect, 'portrait');
  radio(ui.draw(), 'Platform', 'youtube_shorts').props.onKeyDown({ key: 'ArrowRight', preventDefault() {} });
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.platform, 'tiktok');
  assert.equal(radio(ui.draw(), 'Platform', 'tiktok').props.tabIndex, 0);
  assert.equal(radio(ui.draw(), 'Platform', 'youtube').props.tabIndex, -1);
});

test('step tabs follow the tab pattern with arrow, Home and End keys and a Next button', async () => {
  jobRows = [];
  const ui = await studio(async () => selectedProject);
  const tabs = () => nodes(role(ui.draw(), 'tablist')).filter(n => n.props?.role === 'tab');
  assert.deepEqual(tabs().map(n => text(n).replace(/\d/g, '').trim()), ['Edit', 'Style', 'Sound', 'Review', 'Export']);
  assert.equal(tabs()[0].props['aria-selected'], true);
  assert.equal(role(ui.draw(), 'tabpanel').props['aria-labelledby'], tabs()[0].props.id);
  tabs()[0].props.onKeyDown({ key: 'ArrowRight', preventDefault() {} });
  assert.equal(tabs()[1].props['aria-selected'], true);
  tabs()[1].props.onKeyDown({ key: 'End', preventDefault() {} });
  assert.equal(tabs()[4].props['aria-selected'], true);
  tabs()[4].props.onKeyDown({ key: 'ArrowRight', preventDefault() {} });
  assert.equal(tabs()[0].props['aria-selected'], true, 'Arrow keys wrap');
  tabs()[0].props.onKeyDown({ key: 'Home', preventDefault() {} });
  button(ui.draw(), 'Next: Style').props.onClick();
  assert.equal(tabs()[1].props['aria-selected'], true);
});

test('creates platform versions from the current project and opens the new one', async () => {
  jobRows = [];
  hookStores.clear(); queries.length = 0; invalidations.length = 0;
  selectedProject = { id: 'p1', name: 'Talk', revision: 3, source: 'in.mp4', settings: { aspect: 'source', brand: {} }, artifacts: {}, source_info: { duration: 12 } };
  projectRows = [selectedProject];
  const stored = [], calls = [], entries = [];
  (await load()).default.register({ register: x => entries.push(x), storage: { get: (key, fallback) => key.startsWith('lastProject') ? 'p1' : fallback, set: (key, value) => stored.push([key, value]) },
    rest: async (path, options) => { calls.push({ path, options }); if (path.endsWith('/derive')) return { ...selectedProject, id: `child-${options.body.platform}`, revision: 1 }; return selectedProject; } });
  const route = entries.find(x => x.area === sdk.ROUTES_AREA);
  const styleTab = () => nodes(draw(route)).find(n => n.props?.role === 'tab' && text(n).includes('Style')).props.onClick();
  styleTab();
  let tree = draw(route);
  for (const label of ['Create version for Reels', 'Create version for Shorts', 'Create version for TikTok', 'Create version for YouTube']) assert.ok(button(tree, label), label);
  await button(tree, 'Create version for Reels').props.onClick();
  assert.deepEqual(calls.at(-1), { path: '/projects/p1/derive', options: { method: 'POST', body: { platform: 'instagram_reels' } } });
  assert.deepEqual(stored.at(-1)[1], 'child-instagram_reels');
  assert.ok(invalidations.length >= 1);
  assert.ok(!calls.some(c => c.path.endsWith('/approve')), 'Deriving never approves');
  selectedProject = { ...selectedProject, id: 'child-tiktok', settings: { platform: 'tiktok', aspect: 'portrait' }, derived_from: { project_id: 'p1', revision: 3, digest: 'd'.repeat(64) } };
  styleTab();
  assert.match(text(draw(route)), /Derived from p1 at revision 3/);
});

test('overlays the unsafe areas of the platform the loaded render was made with, once its metadata is known', async () => {
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  URL.createObjectURL = () => 'blob:zone'; URL.revokeObjectURL = () => {};
  try {
    jobRows = [];
    const media = async path => path.includes('/media/') ? { data: btoa('abc'), offset: 0, next_offset: 3, total: 3, mime: 'video/mp4', version: 'v1' } : selectedProject;
    // The project now targets TikTok, but the loaded preview was rendered for Reels.
    let ui = await studio(media, { settings: { platform: 'tiktok', aspect: 'portrait' }, artifacts: { preview: 'preview.mp4' }, artifact_lineage: { preview: { job_id: 'j'.repeat(32), platform: 'instagram_reels' } } });
    let toggle = nodes(ui.draw()).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'Show safe zone');
    assert.ok(toggle, 'Safe-zone toggle is rendered');
    assert.notEqual(toggle.props.disabled, true);
    await choice(ui.draw(), 'Preview').props.onClick();
    toggle = nodes(ui.draw()).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'Show safe zone');
    toggle.props.onCheckedChange(true);
    let tree = ui.draw();
    assert.deepEqual(nodes(tree).filter(n => n.props?.['data-cutroom-unsafe']), [], 'No overlay before the video size is known');
    const video = nodes(tree).find(n => n.type === 'video');
    assert.equal(typeof video.props.onLoadedMetadata, 'function');
    video.props.onLoadedMetadata({ currentTarget: { duration: 10 } });
    tree = ui.draw();
    const boxes = nodes(tree).filter(n => n.props?.['data-cutroom-unsafe']);
    assert.deepEqual(boxes.map(n => n.props['data-cutroom-unsafe']).sort(), ['bottom', 'left', 'right', 'top']);
    const top = boxes.find(n => n.props['data-cutroom-unsafe'] === 'top');
    assert.equal(top.props.style.height, '14%', 'Reels zone of the render, not the TikTok setting');
    assert.equal(boxes.find(n => n.props['data-cutroom-unsafe'] === 'bottom').props.style.height, '35%');
    assert.equal(boxes.find(n => n.props['data-cutroom-unsafe'] === 'left').props.style.width, '6%');
    assert.match(String(top.props.style.background), /^var\(--ui-/);
    assert.match(text(tree), /Instagram Reels safe zone/);
    assert.ok(nodes(tree).find(n => n.type === 'video'), 'The player stays visible under the overlay');
    // A render without a recorded platform was made by the custom profile.
    ui = await studio(media, { settings: { platform: 'tiktok', aspect: 'portrait' }, artifacts: { preview: 'preview.mp4' }, artifact_lineage: { preview: { job_id: 'j'.repeat(32) } } });
    await choice(ui.draw(), 'Preview').props.onClick();
    nodes(ui.draw()).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'Show safe zone').props.onCheckedChange(true);
    nodes(ui.draw()).find(n => n.type === 'video').props.onLoadedMetadata({ currentTarget: { duration: 10 } });
    assert.deepEqual(nodes(ui.draw()).filter(n => n.props?.['data-cutroom-unsafe']), [], 'Custom renders get no platform overlay');
    ui = await studio(media, { settings: { aspect: 'source' }, artifacts: { preview: 'preview.mp4' } });
    toggle = nodes(ui.draw()).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'Show safe zone');
    assert.equal(toggle.props.disabled, true, 'Custom projects have no platform safe zone');
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; }
});

test('chooses caption style cards including Off and saves accent colour and one-word position', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, { settings: { aspect: 'source', brand: {} } });
  let tree = await ui.step('Style');
  const group = role(tree, 'radiogroup', 'Caption style');
  assert.deepEqual(nodes(group).filter(n => n.props?.role === 'radio').map(n => n.props['data-value']), ['off', 'classic', 'highlight', 'pop', 'one_word']);
  assert.equal(radio(tree, 'Caption style', 'off').props['aria-checked'], true, 'Captions are off until chosen');
  assert.match(text(radio(tree, 'Caption style', 'highlight')), /Your words/, 'Cards show a text preview');
  assert.match(source, /`caption-style:\$\{value\}`/, 'Style keys are namespaced');
  radio(tree, 'Caption style', 'highlight').props.onClick();
  tree = ui.draw();
  type(field(tree, 'caption_highlight_color'), '#00FF88');
  type(field(ui.draw(), 'caption_word_y'), '0.4');
  await ui.flush();
  const saved = ui.patches().at(-1).options.body.changes.settings;
  assert.equal(saved.caption_style, 'highlight');
  assert.equal(saved.captions, true);
  assert.equal(saved.caption_highlight_color, '#00FF88');
  assert.equal(saved.caption_word_y, 0.4);
  const preview = nodes(radio(ui.draw(), 'Caption style', 'highlight')).find(n => n.props?.style?.color === '#00FF88');
  assert.ok(preview, 'The preview uses the chosen colour');
  radio(ui.draw(), 'Caption style', 'off').props.onClick();
  await ui.flush();
  assert.deepEqual(ui.patches().at(-1).options.body.changes.settings, { captions: false });
});

test('rejects invalid caption colours and positions before saving', async () => {
  jobRows = [];
  const ui = await studio(async () => selectedProject, { settings: { caption_style: 'one_word', captions: true, brand: {} } });
  await ui.step('Style');
  type(field(ui.draw(), 'caption_highlight_color'), 'yellow');
  await ui.flush();
  assert.equal(ui.patches().length, 0);
  assert.match(text(ui.draw()), /six-digit hex/i);
  type(field(ui.draw(), 'caption_highlight_color'), '#00FF88');
  type(field(ui.draw(), 'caption_word_y'), '2');
  await ui.flush();
  assert.equal(ui.patches().length, 1, 'Only the valid colour is sent');
  assert.equal(ui.patches()[0].options.body.changes.settings.caption_word_y, undefined);
  assert.match(text(ui.draw()), /between 0 and 1/i);
});

test('blank caption colour and position fall back to the defaults instead of failing or moving text', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, { settings: { caption_style: 'one_word', captions: true, caption_highlight_color: '#00FF88', caption_word_y: 0.3, brand: {} } });
  await ui.step('Style');
  type(field(ui.draw(), 'caption_highlight_color'), '');
  type(field(ui.draw(), 'caption_word_y'), '');
  await ui.flush();
  const patches = ui.patches();
  assert.equal(patches.length, 1, 'A blank optional field must not block saving');
  const saved = patches[0].options.body.changes.settings;
  assert.equal(saved.caption_highlight_color, null, 'Blank colour is sent as null so the backend restores the default accent');
  assert.equal(saved.caption_word_y, null, 'Blank position is sent as null (default 0.8), not 0 (top edge)');
});

test('choosing YouTube turns burned captions off; the person can choose a style again', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, { settings: { platform: 'instagram_reels', captions: true, caption_style: 'pop', brand: {} } });
  let tree = await ui.step('Style');
  assert.equal(radio(tree, 'Caption style', 'pop').props['aria-checked'], true);
  radio(tree, 'Platform', 'youtube').props.onClick();
  tree = ui.draw();
  assert.equal(radio(tree, 'Caption style', 'off').props['aria-checked'], true, 'YouTube delivers sidecar captions; burn-in becomes opt-in');
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.captions, false);
  radio(ui.draw(), 'Caption style', 'classic').props.onClick();
  await ui.flush();
  const saved = ui.patches().at(-1).options.body.changes.settings;
  assert.equal(saved.captions, true, 'An explicit choice is kept');
  assert.equal(selectedProject.settings.platform, 'youtube');
});

test('face track needs a face analysis and offers to run it', async () => {
  jobRows = [];
  const ui = await studio(async (path, options) => options?.method === 'POST' ? { id: 'v' } : patchApplies(path, options), { settings: { framing: 'face_track', face_model: 'C:/m/face.task', brand: {} } });
  const tree = await ui.step('Style');
  assert.equal(radio(tree, 'Framing', 'face_track').props['aria-checked'], true);
  assert.match(text(tree), /needs a face analysis/i);
  await button(tree, 'Analyse faces').props.onClick();
  assert.deepEqual(ui.calls.at(-1).options.body, { action: 'vision', options: {} });
});

test('sound: music file, one level slider in words, ducking, voice clean-up; nothing sent for legacy projects', async () => {
  jobRows = [];
  const ui = await studio(patchApplies);
  let tree = await ui.step('Sound');
  assert.ok(field(tree, 'music.path'), 'Music path control');
  assert.ok(field(tree, 'cut_sfx.path'), 'Cut sound path control under More sound options');
  assert.equal(field(tree, 'music.level').props.disabled, true, 'Level waits for a music file');
  type(field(tree, 'music.path'), 'C:/audio/bed.wav');
  tree = ui.draw();
  const level = field(tree, 'music.level');
  assert.equal(level.props.type, 'range');
  assert.match(level.props['aria-valuetext'], /Background/);
  type(level, '-30');
  assert.match(text(ui.draw()), /Quiet/);
  type(field(ui.draw(), 'music.duck_db'), '18');
  type(field(ui.draw(), 'music.source_note'), 'Own recording');
  nodes(role(ui.draw(), 'group', 'Voice clean-up')).find(n => n.type === 'Button' && text(n) === 'Light').props.onClick();
  await ui.flush();
  const settings = ui.patches().map(c => c.options.body.changes.settings).reduce((a, b) => ({ ...a, ...b }), {});
  assert.equal(settings.music.path, 'C:/audio/bed.wav');
  assert.equal(settings.music.volume_db, -30);
  assert.equal(settings.music.duck_db, 18);
  assert.equal(settings.music.source_note, 'Own recording');
  assert.equal(settings.music.loop, true);
  assert.equal(settings.music.duck, true);
  assert.equal(settings.voice_cleanup, 'light');
  assert.equal(settings.cut_sfx, undefined, 'An untouched cut sound is not sent');
  for (const label of ['Loop music', 'Duck music during speech']) assert.ok(labelled(ui.draw(), label));
  assert.match(text(ui.draw()), /loudness/i);
});

test('a blank path removes a saved sound, computed fields are not sent back, and out-of-range numbers are refused', async () => {
  jobRows = [];
  const music = { path: 'C:/audio/bed.wav', volume_db: -18, duck_db: 12, fade_in: 0.5, fade_out: 0.5, start_offset: 0, loop: false, duck: true, source_note: 'Own', sha256: 'a'.repeat(64), duration: 20, format: 'wav' };
  const cut_sfx = { path: 'C:/audio/click.wav', volume_db: -12, sha256: 'b'.repeat(64), duration: 0.2, format: 'wav' };
  const ui = await studio(patchApplies, { settings: { aspect: 'source', brand: {}, music, cut_sfx, voice_cleanup: 'strong' } });
  await ui.step('Sound');
  assert.equal(field(ui.draw(), 'music.path').props.value, 'C:/audio/bed.wav', 'Saved music is shown');
  assert.equal(labelled(ui.draw(), 'Loop music').props.checked, false, 'Saved loop setting is shown');
  type(field(ui.draw(), 'music.duck_db'), '40');
  await ui.flush();
  assert.equal(ui.patches().length, 0, 'Out-of-range ducking is not sent');
  assert.match(text(nodes(ui.draw()).find(n => n.props.role === 'alert')), /music\.duck_db must be between 12 and 36/);
  type(field(ui.draw(), 'music.duck_db'), '');
  type(field(ui.draw(), 'cut_sfx.path'), '  ');
  await ui.flush();
  const saved = ui.patches().at(-1).options.body.changes.settings;
  assert.equal(saved.cut_sfx, null, 'Blank path removes the saved cut sound');
  assert.equal(saved.music.duck_db, undefined, 'Blank number falls back to the default');
  assert.equal(saved.music.loop, false);
  for (const key of ['sha256', 'duration', 'format']) assert.equal(saved.music[key], undefined, `${key} is recomputed by the backend`);
  assert.equal(saved.voice_cleanup, undefined, 'Voice clean-up is untouched');
});

test('selects reframing and adds a program-time pin from playback with a horizontal slider', async () => {
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  URL.createObjectURL = () => 'blob:framing'; URL.revokeObjectURL = () => {};
  try {
    jobRows = [];
    const ui = await studio(async (path, options) => {
      if (path.includes('/media/')) return { data: btoa('abc'), offset: 0, next_offset: 3, total: 3, mime: 'video/mp4', version: 'v1' };
      return patchApplies(path, options);
    }, { settings: { framing: 'fit', brand: {} }, segments: [{ start: 2, end: 10 }], artifacts: { preview: 'preview.mp4' } });
    let tree = await ui.step('Style');
    assert.equal(nodes(role(tree, 'radiogroup', 'Framing')).filter(n => n.props?.role === 'radio').length, 4);
    radio(tree, 'Framing', 'center_crop').props.onClick();
    await ui.flush();
    assert.equal(ui.patches().at(-1).options.body.changes.settings.framing, 'center_crop');
    await choice(ui.draw(), 'Preview').props.onClick();
    ui.draw(); tree = ui.draw();
    nodes(tree).find(n => n.type === 'video').props.onTimeUpdate({ currentTarget: { currentTime: 2.5 } });
    tree = ui.draw();
    const slider = field(tree, 'framing.x');
    assert.ok(slider); assert.equal(slider.props.type, 'range');
    slider.props.onChange({ target: { value: '0.35' } });
    await button(ui.draw(), 'Add framing keyframe').props.onClick();
    await ui.flush();
    assert.deepEqual(ui.patches().at(-1).options.body.changes.settings.framing_keyframes, [{ time: 2.5, x: 0.35 }]);
    assert.match(source, /`framing-mode:\$\{value\}`/);
    assert.match(source, /`framing-key:\$\{key.time\}`/);
    tree = ui.draw();
    assert.match(text(tree), /program time/i);
    await button(tree, 'Remove framing keyframe').props.onClick();
    await ui.flush();
    assert.deepEqual(ui.patches().at(-1).options.body.changes.settings.framing_keyframes, []);
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; }
});

test('style: pacing saves punch-ins, shorter pauses and transitions in plain words', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, { settings: { brand: {} } });
  await ui.step('Style');
  const press = (group, label) => nodes(role(ui.draw(), 'group', group)).find(n => n.type === 'Button' && text(n) === label).props.onClick();
  assert.ok(nodes(ui.draw()).find(n => n.type === 'h3' && text(n) === 'Pacing'), 'Pacing heading');
  assert.equal(field(ui.draw(), 'pacing.max_pause').props.disabled, true, 'The pause slider waits for the switch');
  press('Punch-ins', 'On');
  labelled(ui.draw(), 'Shorten long pauses').props.onCheckedChange(true);
  const slider = field(ui.draw(), 'pacing.max_pause');
  assert.equal(slider.props.type, 'range');
  assert.equal(slider.props.disabled, false);
  assert.match(slider.props['aria-valuetext'], /0\.6 seconds/);
  type(slider, '0.5');
  press('Transition', 'Crossfade');
  assert.ok(disclosure(ui.draw(), 'More pacing options'), 'Zoom amounts live under More pacing options');
  labelled(ui.draw(), 'Slow push-in on long shots').props.onCheckedChange(true);
  type(field(ui.draw(), 'pacing.punch_in_zoom'), '1.2');
  await ui.flush();
  const pacing = ui.patches().at(-1).options.body.changes.settings.pacing;
  assert.deepEqual({ ...pacing }, { punch_in: 'alternate', max_pause: 0.5, transition: 'crossfade', push_in: true, punch_in_zoom: 1.2 });
  const count = ui.patches().length;
  type(field(ui.draw(), 'pacing.punch_in_zoom'), '1.5');
  await ui.flush();
  assert.equal(ui.patches().length, count, 'An out-of-range zoom is not sent');
  assert.match(text(ui.draw()), /between 1\.05 and 1\.3/);
  type(field(ui.draw(), 'pacing.punch_in_zoom'), '');
  labelled(ui.draw(), 'Shorten long pauses').props.onCheckedChange(false);
  press('Transition', 'Dip to black');
  await ui.flush();
  const last = ui.patches().at(-1).options.body.changes.settings.pacing;
  assert.equal(last.max_pause, null, 'Turning the switch off sends no limit');
  assert.equal(last.punch_in_zoom, undefined, 'A blank zoom uses the default');
  assert.equal(last.transition, 'dip');
  for (const name of ['pacing_upscale', 'pacing_face', 'pacing_transitions', 'pacing_max_pause']) assert.ok(source.includes(`  ${name}: ['`), `${name} reads as a sentence`);
});

test('pacing undo restores the previous settings, and legacy projects send nothing', async () => {
  jobRows = [];
  const ui = await studio(patchApplies, { settings: { brand: {} } });
  await ui.step('Style');
  await ui.flush();
  assert.equal(ui.patches().length, 0, 'Opening Style does not write pacing');
  nodes(role(ui.draw(), 'group', 'Punch-ins')).find(n => n.type === 'Button' && text(n) === 'On').props.onClick();
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.pacing.punch_in, 'alternate');
  await button(ui.draw(), 'Undo').props.onClick();
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.pacing, null, 'Undo removes pacing again');
});

test('chat card shows a compact video summary, opens the Studio and never approves', async () => {
  const module = await load();
  const entries = [];
  sdk.TOOL_MEDIA_RENDERER_AREA = 'tool.media';
  const calls = [];
  module.default.register({ register: x => entries.push(x), storage: { get: (key, fallback) => fallback, set() {} }, setTimeout: () => () => {}, rest: async (path, options) => { calls.push({ path, options }); return selectedProject; } });
  delete sdk.TOOL_MEDIA_RENDERER_AREA;
  const renderer = entries.find(x => x.area === 'tool.media');
  assert.deepEqual(renderer.data.tools, ['cutroom_job', 'cutroom_project']);
  const resolved = [];
  const file = { path: '/x/final.mp4', name: 'final.mp4', kind: 'video', mime: 'video/mp4', resolveUrl: async () => { resolved.push(1); return 'blob:chat'; } };
  const media = { path: '/x/final.mp4', kind: 'video', project_id: 'p9', project_name: 'Sandra', platform: 'instagram_reels', duration: 39.4, width: 1080, height: 1920,
    qa: { status: 'warning', passed: false, failed: 0, warnings: 1, total: 12 }, approved: false };
  const card = { render: () => renderer.data.render({ file, result: { media }, args: {}, fallback: 'FALLBACK', sessionId: 's1' }) };
  hookStores.clear();
  draw(card);
  await tick();
  let tree = draw(card);
  assert.equal(resolved.length, 1);
  assert.equal(nodes(tree).find(n => n.type === 'video').props.src, 'blob:chat');
  const all = text(tree);
  for (const part of ['Sandra', 'Instagram Reels', '0:39', 'Ready, with 1 note', 'Not approved yet']) assert.match(all, new RegExp(part));
  assert.equal(nodes(tree).find(n => n.type === 'Button' && text(n).trim().startsWith('Approve')), undefined, 'No approve button in chat');
  button(tree, 'Review and approve').props.onClick();
  assert.equal(navigation.at(-1), '/cutroom');
  // The Studio opens that project on the Review step.
  hookStores.clear(); jobRows = []; queries.length = 0;
  selectedProject = { id: 'p9', name: 'Sandra', revision: 2, source: 'in.mp4', settings: {}, artifacts: {}, source_info: { duration: 40 } };
  projectRows = [selectedProject];
  const route = entries.find(x => x.area === sdk.ROUTES_AREA);
  draw(route);
  tree = draw(route);
  assert.ok(nodes(role(tree, 'tablist')).find(n => n.props?.['aria-selected'] === true && text(n).includes('Review')), 'Review step is open');
  assert.ok(queries.some(q => q.queryKey.includes('project') && q.queryKey.includes('p9')));
  assert.ok(!calls.some(c => c.path.endsWith('/approve')));
  // Tolerates a JSON string result, missing fields, and returns the fallback for other files.
  hookStores.clear();
  tree = draw({ render: () => renderer.data.render({ file, result: JSON.stringify({ media: { kind: 'video' } }), fallback: 'FALLBACK' }) });
  assert.match(text(tree), /Not checked yet/);
  hookStores.clear();
  assert.equal(draw({ render: () => renderer.data.render({ file: { ...file, kind: 'image' }, result: {}, fallback: 'FALLBACK' }) }), 'FALLBACK');
  hookStores.clear();
  assert.doesNotThrow(() => draw({ render: () => renderer.data.render({ file, result: null, fallback: 'FALLBACK' }) }));
});

const chunk = (path, total = 3) => {
  const offset = Number(new URL(path, 'https://test').searchParams.get('offset') || 0);
  return { data: btoa('abc'), offset, next_offset: offset + 3, total, mime: 'video/mp4', version: 'v1' };
};
async function withBlobs(body) {
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  let count = 0;
  URL.createObjectURL = () => `blob:auto-${++count}`; URL.revokeObjectURL = () => {};
  try { await body(); } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; posterData = null; }
}

test('opens with the video loaded: the current preview, else the original, when it is small', async () => withBlobs(async () => {
  const preview = currentPreview();
  jobRows = preview.jobs;
  let ui = await studio(async path => path.includes('/artifact-info/') ? { path: 'x', name: 'x.mp4', size: 6 } : path.includes('/media/') ? chunk(path, 6) : selectedProject, preview.project);
  ui.draw(); await tick();
  let tree = ui.draw();
  assert.match(String(nodes(tree).find(n => n.type === 'video')?.props.src), /^blob:/, 'The player loads without a click');
  assert.ok(ui.calls.some(c => c.path === '/projects/p1/artifact-info/preview'), 'Size comes from a metadata call');
  assert.ok(ui.calls.some(c => c.path.startsWith('/projects/p1/media/preview')));
  assert.ok(!ui.calls.some(c => c.path.includes('/media/source')), 'A current preview wins over the original');
  assert.equal(choice(tree, 'Preview').props['aria-pressed'], true);
  assert.doesNotMatch(text(tree), /Nothing loaded/);
  for (const label of ['Load source', 'Unload media', 'Download']) assert.equal(button(tree, label), undefined, `${label} is not in the player`);
  jobRows = [];
  ui = await studio(async path => path.includes('/artifact-info/') ? { path: 'x', name: 'x.mp4', size: 1024 } : path.includes('/media/') ? chunk(path) : selectedProject, { artifacts: { preview: 'old.mp4' } });
  ui.draw(); await tick();
  tree = ui.draw();
  assert.ok(nodes(tree).find(n => n.type === 'video'), 'Without a current preview the original loads');
  assert.ok(ui.calls.some(c => c.path === '/projects/p1/artifact-info/source'));
  assert.ok(!ui.calls.some(c => c.path.includes('/media/preview')), 'A stale preview is not loaded');
  assert.equal(choice(tree, 'Original').props['aria-pressed'], true);
}));

test('a large video shows its poster frame and one Load button with its size', async () => withBlobs(async () => {
  jobRows = [];
  posterData = { mime: 'image/jpeg', data_url: 'data:image/jpeg;base64,AAAA', time: 3.6 };
  const ui = await studio(async path => path.includes('/artifact-info/') ? { path: 'x', name: 'x.mp4', size: 100 * 1048576 } : path.includes('/media/') ? chunk(path) : selectedProject);
  ui.draw(); await tick();
  let tree = ui.draw();
  assert.ok(!ui.calls.some(c => c.path.includes('/media/')), 'Large files are not loaded without a click');
  assert.equal(nodes(tree).find(n => n.type === 'video'), undefined);
  assert.ok(nodes(tree).some(n => n.type === 'img' && n.props.src === posterData.data_url), 'The poster frame stands in for the video');
  const load = button(tree, 'Load video (100 MB)');
  assert.ok(load, 'One button names the size');
  await load.props.onClick();
  tree = ui.draw();
  assert.ok(ui.calls.some(c => c.path.includes('/media/source')));
  assert.ok(nodes(tree).find(n => n.type === 'video'));
  assert.equal(button(tree, 'Load video'), undefined);
}));

test('the platform safe area is shown by default and can be turned off', async () => withBlobs(async () => {
  jobRows = [];
  const ui = await studio(async path => path.includes('/artifact-info/') ? { size: 3 } : path.includes('/media/') ? chunk(path) : selectedProject, { settings: { platform: 'instagram_reels', aspect: 'portrait' } });
  ui.draw(); await tick();
  let tree = ui.draw();
  nodes(tree).find(n => n.type === 'video').props.onLoadedMetadata({ currentTarget: { duration: 12 } });
  tree = ui.draw();
  const toggle = nodes(tree).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'Show safe zone');
  assert.equal(toggle.props.checked, true, 'On by default');
  assert.deepEqual(nodes(tree).filter(n => n.props?.['data-cutroom-unsafe']).map(n => n.props['data-cutroom-unsafe']).sort(), ['bottom', 'left', 'right', 'top']);
  assert.equal(labelled(tree, 'Instagram Reels frame').props.style.aspectRatio, '9 / 16', 'The stage frames the platform shape');
  assert.match(String(labelled(tree, 'Video stage').props.style.background), /^color-mix\(in srgb, var\(--ui-/, 'A theme-derived dark stage');
  toggle.props.onCheckedChange(false);
  assert.deepEqual(nodes(ui.draw()).filter(n => n.props?.['data-cutroom-unsafe']), []);
}));

const captionProject = (settings = {}) => ({ ...transcriptProject(), excluded_word_ids: ['w2'],
  settings: { platform: 'instagram_reels', aspect: 'portrait', captions: true, caption_style: 'highlight', caption_highlight_color: '#112233', ...settings } });
const captionNode = tree => nodes(tree).find(n => n.props?.['data-cutroom-caption']);

test('playing the original skips removed words, like the finished video', async () => withBlobs(async () => {
  jobRows = [];
  const media = async path => path.includes('/artifact-info/') ? { size: 3 } : path.includes('/media/') ? chunk(path) : selectedProject;
  const ui = await studio(media, captionProject());
  ui.draw(); await tick();
  const tree = ui.draw();
  const video = nodes(tree).find(n => n.type === 'video');
  const fake = { currentTime: 0.35, paused: false, duration: 12 };
  video.props.ref.current = fake;
  video.props.onTimeUpdate({ currentTarget: fake });
  const removed = captionProject().transcript.words.find(w => captionProject().excluded_word_ids.includes(w.id));
  assert.ok(fake.currentTime >= removed.end, 'Playback jumps over the removed word');
  fake.currentTime = 0.1; fake.paused = true;
  nodes(ui.draw()).find(n => n.type === 'video').props.onTimeUpdate({ currentTarget: fake });
  assert.equal(fake.currentTime, 0.1, 'A paused or seeking player is left where the person put it');
}));

test('the caption preview uses the rendered default highlight colour', async () => withBlobs(async () => {
  jobRows = [];
  const project = captionProject();
  const settings = { ...project.settings };
  delete settings.caption_highlight_color;
  const media = async path => path.includes('/artifact-info/') ? { size: 3 } : path.includes('/media/') ? chunk(path) : selectedProject;
  const ui = await studio(media, { ...project, settings });
  ui.draw(); await tick();
  nodes(ui.draw()).find(n => n.type === 'video').props.onTimeUpdate({ currentTarget: { currentTime: 0.65 } });
  const active = nodes(captionNode(ui.draw())).find(n => n.props?.['data-active']);
  assert.equal(active.props.style.color, '#FFCC00');
}));

test('draws an approximate live caption over the original, from words that are not removed', async () => withBlobs(async () => {
  jobRows = [];
  const media = async path => path.includes('/artifact-info/') ? { size: 3 } : path.includes('/media/') ? chunk(path) : selectedProject;
  let ui = await studio(media, { ...captionProject(), artifacts: { preview: 'p.mp4' } });
  ui.draw(); await tick();
  let tree = ui.draw();
  nodes(tree).find(n => n.type === 'video').props.onTimeUpdate({ currentTarget: { currentTime: 0.65 } });
  tree = ui.draw();
  const cue = captionNode(tree);
  assert.ok(cue, 'Caption overlay while the original plays');
  assert.match(text(cue), /My/); assert.match(text(cue), /is/);
  assert.doesNotMatch(text(cue), /name/, 'Removed words are not captioned');
  const active = nodes(cue).find(n => n.props?.['data-active']);
  assert.equal(text(active), 'is');
  assert.equal(active.props.style.color, '#112233', 'Highlight colour from settings');
  assert.equal(cue.props.style.fontSize, '3.5cqh', 'Readable size for vertical video');
  assert.match(text(tree), /Approximate caption preview\. The rendered preview shows the exact result\./);
  assert.equal(text(tree).match(/Approximate caption preview/g).length, 1, 'Labelled once');
  // The Captions toggle hides it.
  nodes(tree).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'Show captions').props.onCheckedChange(false);
  assert.equal(captionNode(ui.draw()), undefined);
  nodes(ui.draw()).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'Show captions').props.onCheckedChange(true);
  // Rendered media already has its captions burned in.
  await choice(ui.draw(), 'Preview').props.onClick();
  tree = ui.draw();
  nodes(tree).find(n => n.type === 'video').props.onTimeUpdate({ currentTarget: { currentTime: 0.65 } });
  assert.equal(captionNode(ui.draw()), undefined, 'No overlay on a rendered preview');
  // One word: only the spoken word, twice as large, at the one-word position.
  ui = await studio(media, captionProject({ caption_style: 'one_word', caption_word_y: 0.5, platform: 'youtube', aspect: 'landscape' }));
  ui.draw(); await tick();
  nodes(ui.draw()).find(n => n.type === 'video').props.onTimeUpdate({ currentTarget: { currentTime: 1.1 } });
  tree = ui.draw();
  assert.equal(text(captionNode(tree)).trim(), 'when');
  assert.equal(captionNode(tree).props.style.fontSize, '12.5cqh', 'One word is twice the landscape size');
  // Captions off: nothing drawn.
  ui = await studio(media, captionProject({ captions: false }));
  ui.draw(); await tick();
  nodes(ui.draw()).find(n => n.type === 'video').props.onTimeUpdate({ currentTarget: { currentTime: 0.65 } });
  assert.equal(captionNode(ui.draw()), undefined);
}));

test('poster frames come from the poster route for home cards, the player and caption cards', async () => withBlobs(async () => {
  posterData = { mime: 'image/jpeg', data_url: 'data:image/jpeg;base64,BBBB', time: 1 };
  jobRows = [];
  const ui = await studio(async path => selectedProject, captionProject());
  let tree = ui.draw();
  const poster = queries.find(q => q.queryKey.includes('poster'));
  assert.ok(poster, 'A poster query');
  assert.ok(poster.queryKey.includes('host-a') || poster.queryKey.includes(connectionId), 'Scoped to the connection');
  assert.ok(!poster.queryKey.includes('cutroom') || poster.queryKey[0] !== 'cutroom', 'Saves do not refetch posters');
  await poster.queryFn();
  assert.ok(ui.calls.some(c => c.path === '/projects/p1/poster'), 'Fetched from the poster route');
  assert.ok(nodes(tree).some(n => n.type === 'img' && n.props.src === posterData.data_url), 'Player poster');
  tree = await ui.step('Style');
  const card = radio(tree, 'Caption style', 'highlight');
  assert.ok(nodes(card).some(n => String(n.props?.style?.backgroundImage || '').includes(posterData.data_url)), 'Caption cards sit on the poster');
  assert.match(text(card), /Your words|here/);
  // Home: each recent project shows its poster.
  hookStores.clear(); queries.length = 0;
  projectRows = [{ id: 'p1', name: 'Local demo', revision: 1, settings: {}, artifacts: {} }];
  const entries = [];
  (await load()).default.register({ register: x => entries.push(x), storage: { get: (key, fallback) => fallback, set() {} }, rest: async () => posterData });
  tree = draw(entries.find(x => x.area === sdk.ROUTES_AREA));
  assert.ok(nodes(tree).some(n => n.type === 'img' && n.props.src === posterData.data_url), 'Home thumbnail');
}));

const longTalk = (extra = {}) => ({ ...transcriptProject(), source_info: { duration: 1063 }, base_segments: [{ start: 0, end: 1063 }], segments: [{ start: 0, end: 1063 }], ...extra });
const clipCandidates = { settings: { min_s: 20, max_s: 60, count: 8, platform: 'youtube_shorts' }, mode: 'punctuation', energy: true, candidates: [
  { id: 'clip-12000-48000', rank: 1, start: 12, end: 48, duration: 36, score: 77, hook: 'Why do cities flood?', text: 'Why do cities flood? Water runs downhill.', reasons: [{ text: 'Opens with a question', points: 12 }, { text: 'Starts mid-thought: "And"', points: -15 }] },
  { id: 'clip-600000-655000', rank: 2, start: 600, end: 655, duration: 55, score: 61, hook: 'Here is the truth.', text: 'Here is the truth.', reasons: [{ text: 'Steady speaking pace', points: 6 }] },
] };

test('clip cards stay compact: a small poster beside the text, two strongest reasons and every penalty, the rest folded', async () => {
  jobRows = [];
  posterData = { mime: 'image/jpeg', data_url: 'data:image/jpeg;base64,CCCC', time: 12 };
  const ui = await studio(async (path, options) => {
    if (path.endsWith('/find-clips')) { selectedProject = { ...selectedProject, clip_candidates: clipCandidates }; return clipCandidates; }
    if (path.endsWith('/clips')) return { ...selectedProject, id: 'clip-child', revision: 1, derived_from: { project_id: 'p1', revision: 7, range: { start: 12, end: 48 } } };
    return selectedProject;
  }, longTalk());
  let tree = ui.draw();
  const finder = role(tree, 'region', 'Find clips');
  assert.ok(finder, 'A labelled Find clips area on the Edit step');
  assert.match(text(finder), /sentence/i, 'Says clips start and end on whole sentences');
  await button(finder, 'Find clips').props.onClick();
  const call = ui.calls.find(c => c.path === '/projects/p1/find-clips');
  assert.deepEqual(call.options, { method: 'POST', body: { platform: 'youtube_shorts' }, timeoutMs: 180000 });
  assert.ok(invalidations.length >= 1);
  tree = ui.draw();
  const list = role(tree, 'list', 'Clip candidates');
  assert.ok(list, 'Candidates are a list');
  const items = nodes(list).filter(n => n.props?.role === 'listitem');
  assert.equal(items.length, 2);
  const card = items[0];
  const fold = nodes(card).find(n => n.type === 'details' && /Why this score/.test(text(n)));
  assert.ok(fold, 'All reasons sit under Why this score');
  const outside = nodes(card).filter(n => n.type === 'li' && !nodes(fold).includes(n));
  assert.equal(outside.length, 0, 'No long bullet list outside the fold');
  const line = nodes(card).find(n => n.props?.['data-clip-reasons']);
  assert.ok(line, 'One short reasons line');
  assert.match(text(line), /Opens with a question/);
  assert.match(text(line), /Starts mid-thought/, 'Penalties stay visible');
  const grid = nodes(card).find(n => n.type === 'article');
  assert.equal(grid.props.style.display, 'grid');
});

test('long videos offer Find clips; candidates show poster, range, score and reasons, and Make clip opens the new project', async () => {
  jobRows = [];
  posterData = { mime: 'image/jpeg', data_url: 'data:image/jpeg;base64,CCCC', time: 12 };
  const ui = await studio(async (path, options) => {
    if (path.endsWith('/find-clips')) { selectedProject = { ...selectedProject, clip_candidates: clipCandidates }; return clipCandidates; }
    if (path.endsWith('/clips')) return { ...selectedProject, id: 'clip-child', revision: 1, derived_from: { project_id: 'p1', revision: 7, range: { start: 12, end: 48 } } };
    return selectedProject;
  }, longTalk());
  let tree = ui.draw();
  const finder = role(tree, 'region', 'Find clips');
  assert.ok(finder, 'A labelled Find clips area on the Edit step');
  assert.match(text(finder), /sentence/i, 'Says clips start and end on whole sentences');
  await button(finder, 'Find clips').props.onClick();
  const call = ui.calls.find(c => c.path === '/projects/p1/find-clips');
  assert.deepEqual(call.options, { method: 'POST', body: { platform: 'youtube_shorts' }, timeoutMs: 180000 });
  assert.ok(invalidations.length >= 1);
  tree = ui.draw();
  const list = role(tree, 'list', 'Clip candidates');
  assert.ok(list, 'Candidates are a list');
  const items = nodes(list).filter(n => n.props?.role === 'listitem');
  assert.equal(items.length, 2);
  assert.match(text(items[0]), /0:12–0:48/);
  assert.match(text(items[0]), /36 s/);
  assert.match(text(items[0]), /77/);
  assert.match(text(items[0]), /Opens with a question/);
  assert.match(text(items[0]), /Starts mid-thought/);
  assert.match(text(items[0]), /Why do cities flood\?/);
  assert.ok(nodes(items[0]).some(n => n.type === 'img' && n.props.src === posterData.data_url && n.props.alt === ''), 'Poster frame of the clip');
  const poster = queries.find(q => q.queryKey.includes('poster') && q.queryKey.includes(12 / 1063));
  assert.ok(poster, 'Poster of the clip start');
  await poster.queryFn();
  assert.ok(ui.calls.some(c => c.path === `/projects/p1/poster?at=${12 / 1063}`), 'Poster route with at=');
  const play = nodes(items[0]).find(n => n.type === 'Button' && n.props['aria-label'] === 'Play clip 1, 0:12 to 0:48');
  assert.ok(play, 'An accessible Play button');
  play.props.onClick();
  // Platform for the new clip, then Make clip.
  const platform = nodes(tree).find(n => n.type === 'select' && n.props.name === 'clip.platform');
  assert.ok(platform, 'A platform choice');
  assert.equal(platform.props.value, 'youtube_shorts');
  platform.props.onChange({ target: { value: 'instagram_reels' } });
  tree = ui.draw();
  const make = nodes(role(tree, 'list', 'Clip candidates')).find(n => n.type === 'Button' && text(n).includes('Make clip'));
  await make.props.onClick();
  assert.deepEqual(ui.calls.find(c => c.path === '/projects/p1/clips').options, { method: 'POST', body: { candidate_id: 'clip-12000-48000', platform: 'instagram_reels' } });
  assert.equal(ui.stored.at(-1)[1], 'clip-child', 'Opens the new clip project');
  assert.ok(!ui.calls.some(c => c.path.endsWith('/approve')), 'Making a clip never approves');
  posterData = null;
});

test('short videos and clip projects do not offer Find clips; a clip says which part it uses', async () => {
  jobRows = [];
  let ui = await studio(async () => selectedProject, transcriptProject());
  assert.equal(role(ui.draw(), 'region', 'Find clips'), undefined);
  ui = await studio(async () => selectedProject, longTalk({ derived_from: { project_id: 'p0', revision: 2, range: { start: 12, end: 48 } } }));
  const tree = ui.draw();
  assert.equal(role(tree, 'region', 'Find clips'), undefined);
  assert.match(text(tree), /Clip of 0:12–0:48 from the original/);
  // Home cards show a clip's own first frame.
  hookStores.clear(); queries.length = 0;
  projectRows = [{ id: 'c1', name: 'Clip', revision: 1, settings: {}, artifacts: {}, source_info: { duration: 1063 }, derived_from: { project_id: 'p0', range: { start: 106.3, end: 140 } } }];
  const entries = [];
  (await load()).default.register({ register: x => entries.push(x), storage: { get: (key, fallback) => fallback, set() {} }, rest: async () => null });
  draw(entries.find(x => x.area === sdk.ROUTES_AREA));
  assert.ok(queries.some(q => q.queryKey.includes('poster') && q.queryKey.some(v => typeof v === 'number' && Math.abs(v - 0.1) < 1e-8)), 'Clip card poster at its range start');
});

test('Play loads the original, seeks on metadata, ignores kept cuts and stops at the candidate end', async () => withBlobs(async () => {
  jobRows = [];
  const ui = await studio(async path => path.includes('/media/') ? chunk(path) : selectedProject,
    longTalk({ clip_candidates: clipCandidates, segments: [{ start: 0, end: 10 }, { start: 100, end: 1063 }] }));
  const play = () => nodes(role(ui.draw(), 'list', 'Clip candidates')).find(n => n.type === 'Button' && n.props['aria-label']?.startsWith('Play clip 1,'));
  await play().props.onClick(); await tick();
  const tree = ui.draw();
  const video = nodes(tree).find(n => n.type === 'video');
  const fake = { currentTime: 0, duration: 1063, paused: true, play() { this.paused = false; return Promise.resolve(); }, pause() { this.paused = true; } };
  video.props.ref.current = fake;
  video.props.onLoadedMetadata({ currentTarget: fake });
  assert.equal(fake.currentTime, 12);
  assert.equal(fake.paused, false);
  fake.currentTime = 20;
  nodes(ui.draw()).find(n => n.type === 'video').props.onTimeUpdate({ currentTarget: fake });
  assert.equal(fake.currentTime, 20, 'Candidate playback is source-range playback, not the edited program');
  fake.currentTime = 48.1;
  nodes(ui.draw()).find(n => n.type === 'video').props.onTimeUpdate({ currentTarget: fake });
  assert.equal(fake.paused, true);
  await play().props.onClick();
  assert.equal(fake.currentTime, 12, 'An already loaded original seeks immediately');
  assert.equal(fake.paused, false);
}));

test('clip finder keeps empty and error states visible and never opens a failed clip', async () => {
  jobRows = [];
  let fail = false;
  const ui = await studio(async path => {
    if (path.endsWith('/find-clips')) return { candidates: [] };
    if (path.endsWith('/clips')) throw new Error('This candidate is no longer available; Find clips again');
    if (fail) throw new Error('Transcribe first');
    return selectedProject;
  }, longTalk({ clip_candidates: clipCandidates }));
  const make = nodes(role(ui.draw(), 'list', 'Clip candidates')).find(n => n.type === 'Button' && text(n) === 'Make clip');
  await make.props.onClick();
  assert.match(text(ui.draw()), /no longer available/);
  assert.equal(ui.stored.length, 0);
  await button(role(ui.draw(), 'region', 'Find clips'), 'Find clips').props.onClick();
  assert.match(text(ui.draw()), /No whole-sentence clips/);
  assert.equal(role(ui.draw(), 'list', 'Clip candidates'), undefined);
  fail = true;
  selectedProject = { ...selectedProject, clip_candidates: clipCandidates, transcript: { ...selectedProject.transcript, words: [{ id: 0, text: 'New.', start: 1, end: 2 }] } };
  assert.equal(role(ui.draw(), 'list', 'Clip candidates')?.props.children.length, 2, 'A different transcript does not reuse the local empty result');
});

test('finding clips flushes autosave first and blocks on a save conflict', async () => {
  jobRows = [];
  const ui = await studio(async (path, options) => {
    if (options?.method === 'PATCH') throw new Error('Revision changed; reload first');
    if (path.endsWith('/find-clips')) return clipCandidates;
    return selectedProject;
  }, longTalk());
  type(field(ui.draw(), 'project.name'), 'Unsaved talk');
  await button(role(ui.draw(), 'region', 'Find clips'), 'Find clips').props.onClick();
  assert.equal(ui.patches().length, 1);
  assert.ok(!ui.calls.some(c => c.path.endsWith('/find-clips')));
  assert.match(text(ui.draw()), /saved|Revision changed/);
});

test('uses only public SDK/React imports and no renderer or polling bypasses', async () => {
  await load();
  assert.ok(imports.length > 0);
  for (const [, , specifier] of imports) assert.ok(['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'].includes(specifier));
  assert.doesNotMatch(source, /window\.|hermesDesktop|__HERMES|\beval\(|new Function|(?<!ctx\.)\bsetInterval\(|(?<!ctx\.)\bsetTimeout\(|\bfetch\(|document\./);
  // One exception: the caption preview's default highlight is a video colour and must equal the burned default.
  const captionDefault = source.match(/^const CAPTION_DEFAULT_HIGHLIGHT = '(#[0-9A-Fa-f]{6})';$/m);
  assert.ok(captionDefault, 'The caption default is declared once');
  const rendered = (await readFile(new URL('../cutroom/captions.py', import.meta.url), 'utf8')).match(/^DEFAULT_HIGHLIGHT = "(#[0-9A-Fa-f]{6})"/m);
  assert.equal(captionDefault[1], rendered[1], 'Preview and render use the same default highlight');
  assert.doesNotMatch(source.replace(captionDefault[0], ''), /#[0-9a-fA-F]{3,8}\b|rgb\(/);
  assert.doesNotMatch(source, /'progress'/, 'Themed progress bars only');
  assert.match(source, /prefers-reduced-motion/);
  assert.match(source, /focus-visible/);
});

// Long-form YouTube: chapters, thumbnail, subtitles file and end-screen space.
const youtubeProject = (settings = {}) => ({ source_info: { duration: 200 }, base_segments: [{ start: 0, end: 200 }], segments: [{ start: 0, end: 200 }], excluded_word_ids: [],
  settings: { platform: 'youtube', aspect: 'landscape', ...settings } });
const longformRest = extra => async (path, options) => {
  if (path === '/projects/p1/chapters/suggest') return { chapters: [{ start: 0, title: 'Coal plants', reason: 'start' }, { start: 62, title: 'Ocean ice', reason: 'pause' }, { start: 124, title: 'Solar power', reason: 'pause' }], problems: [], duration: 200 };
  if (path.startsWith('/projects/p1/thumbnail-preview')) return { mime: 'image/jpeg', data_url: 'data:image/jpeg;base64,AAAA', time: 5, text: 'Simple', width: 1280, height: 720 };
  if (extra) { const value = extra(path, options); if (value !== undefined) return value; }
  return patchApplies(path, options);
};

test('export: YouTube chapters editor suggests, edits, validates in plain words and saves program times', async () => {
  jobRows = [];
  const ui = await studio(longformRest(), youtubeProject());
  let tree = await ui.step('Export');
  assert.ok(nodes(tree).find(n => n.type === 'h3' && text(n) === 'Chapters'), 'Chapters heading');
  await button(tree, 'Suggest chapters').props.onClick();
  await ui.flush();
  assert.ok(ui.calls.some(c => c.path === '/projects/p1/chapters/suggest' && c.options?.method === 'POST'));
  let chapters = ui.patches().at(-1).options.body.changes.settings.chapters;
  assert.deepEqual(chapters.map(c => [c.start, c.title]), [[0, 'Coal plants'], [62, 'Ocean ice'], [124, 'Solar power']]);
  tree = ui.draw();
  assert.equal(field(tree, 'chapters.1.time').props.value, '1:02', 'Times read as minutes and seconds');
  assert.equal(field(tree, 'chapters.1.title').props.value, 'Ocean ice');
  type(field(tree, 'chapters.1.title'), 'Melting ice');
  type(field(ui.draw(), 'chapters.2.time'), '2:10');
  await ui.flush();
  chapters = ui.patches().at(-1).options.body.changes.settings.chapters;
  assert.deepEqual(chapters.map(c => [c.start, c.title]), [[0, 'Coal plants'], [62, 'Melting ice'], [130, 'Solar power']]);
  const count = ui.patches().length;
  type(field(ui.draw(), 'chapters.2.time'), 'soon');
  await ui.flush();
  assert.equal(ui.patches().length, count, 'An unreadable time is not saved');
  assert.match(text(ui.draw()), /Write the time as minutes:seconds/);
  await labelled(ui.draw(), 'Remove chapter 3').props.onClick();
  await ui.flush();
  tree = ui.draw();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.chapters.length, 2);
  const status = role(tree, 'status', 'Chapter check');
  assert.ok(status, 'Problems are announced');
  assert.match(text(status), /at least three chapters/);
  await button(tree, 'Add chapter').props.onClick();
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.chapters.length, 3);
  type(field(ui.draw(), 'chapters.1.time'), '0:05');
  await ui.flush();
  assert.match(text(role(ui.draw(), 'status', 'Chapter check')), /“Coal plants” \(0:00\) is 5 s long/);
  type(field(ui.draw(), 'chapters.0.time'), '0:03');
  await ui.flush();
  assert.match(text(role(ui.draw(), 'status', 'Chapter check')), /first chapter must start at 0:00/);
});

test('export: thumbnail card previews the chosen frame and text; subtitles file and end screen toggles', async () => {
  jobRows = [];
  const ui = await studio(longformRest(), youtubeProject());
  let tree = await ui.step('Export');
  assert.ok(nodes(tree).find(n => n.type === 'h3' && text(n) === 'Thumbnail'));
  type(field(tree, 'thumbnail.text'), 'Simple');
  type(field(ui.draw(), 'thumbnail.time'), '0:05');
  await ui.flush();
  assert.deepEqual({ ...ui.patches().at(-1).options.body.changes.settings.thumbnail }, { text: 'Simple', time: 5 });
  await button(ui.draw(), 'Preview thumbnail').props.onClick();
  tree = ui.draw();
  const call = ui.calls.find(c => c.path.startsWith('/projects/p1/thumbnail-preview'));
  assert.ok(call, 'The preview route is called');
  assert.ok(nodes(tree).some(n => n.type === 'img' && n.props.src === 'data:image/jpeg;base64,AAAA' && /Thumbnail preview/.test(n.props.alt)));
  assert.match(text(tree), /1280 × 720/);
  type(field(ui.draw(), 'thumbnail.time'), '');
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.thumbnail.time, undefined, 'Blank time picks the frame automatically');
  const subtitles = labelled(ui.draw(), 'Make a subtitles file (SRT)');
  assert.equal(subtitles.props.checked, true, 'On by default for YouTube');
  subtitles.props.onCheckedChange(false);
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.subtitles_file, false);
  labelled(ui.draw(), 'Leave room for an end screen').props.onCheckedChange(true);
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.end_screen_s, 20);
  const count = ui.patches().length;
  type(field(ui.draw(), 'end_screen_s'), '30');
  await ui.flush();
  assert.equal(ui.patches().length, count, 'Out-of-range seconds are not sent');
  assert.match(text(ui.draw()), /between 5 and 20 seconds/);
  type(field(ui.draw(), 'end_screen_s'), '12');
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.end_screen_s, 12);
  labelled(ui.draw(), 'Leave room for an end screen').props.onCheckedChange(false);
  await ui.flush();
  assert.equal(ui.patches().at(-1).options.body.changes.settings.end_screen_s, null);
  for (const name of ['chapters', 'subtitles_file', 'thumbnail', 'end_screen']) assert.ok(source.includes(`  ${name}: ['`), `${name} reads as a sentence`);
});

test('long-form controls appear only for YouTube projects', async () => {
  jobRows = [];
  const ui = await studio(longformRest(), { ...youtubeProject(), settings: { platform: 'tiktok', aspect: 'portrait' } });
  const tree = await ui.step('Export');
  assert.equal(nodes(tree).find(n => n.type === 'h3' && text(n) === 'Chapters'), undefined);
  assert.equal(button(tree, 'Suggest chapters'), undefined);
});

test('the stage marks the end-screen space during the last seconds', async () => withBlobs(async () => {
  const preview = currentPreview();
  jobRows = preview.jobs;
  const project = { ...youtubeProject({ end_screen_s: 10 }), ...preview.project, artifact_lineage: { preview: { job_id: 'pj', platform: 'youtube' } } };
  const ui = await studio(async path => path.includes('/artifact-info/') ? { path: 'x', name: 'x.mp4', size: 3 } : path.includes('/media/') ? chunk(path) : selectedProject, project);
  ui.draw(); await tick();
  let tree = ui.draw();
  const video = nodes(tree).find(n => n.type === 'video');
  video.props.onLoadedMetadata({ currentTarget: { duration: 200 } });
  video.props.onTimeUpdate({ currentTarget: { currentTime: 100, paused: true } });
  tree = ui.draw();
  assert.equal(nodes(tree).find(n => n.props?.['data-cutroom-endscreen']), undefined, 'Not before the last 10 s');
  nodes(tree).find(n => n.type === 'video').props.onTimeUpdate({ currentTarget: { currentTime: 195, paused: true } });
  tree = ui.draw();
  const zone = nodes(tree).find(n => n.props?.['data-cutroom-endscreen']);
  assert.ok(zone, 'The end-screen space is shown');
  assert.match(text(zone), /End screen/);
}));

// Delivery packages (F7): post text with live counters, Make package, the folder and Check package.
const packageResult = { name: 'instagram_reels-20261113-101500', directory: 'C:/ws/projects/p1/packages/instagram_reels-20261113-101500', platform: 'instagram_reels', posted: false,
  notice: 'Nothing has been posted. Upload these files yourself.',
  files: [{ name: 'README.txt', size: 512, sha256: 'a'.repeat(64) }, { name: 'cover.jpg', size: 204800, sha256: 'b'.repeat(64) }, { name: 'post.txt', size: 300, sha256: 'c'.repeat(64) }, { name: 'video.mp4', size: 5242880, sha256: 'd'.repeat(64) }] };
const postStatus = (platform = 'instagram_reels') => ({ platform, label: platform === 'youtube' ? 'YouTube' : 'Instagram Reels', suggested: true, problems: [], chapters_text: platform === 'youtube' ? '0:00 Intro\n0:12 Waves\n0:24 End\n' : '',
  post: { title: 'Demo', caption: 'Hello', hashtags: [] },
  limits: platform === 'youtube'
    ? { fields: ['title', 'description'], title: { max: 100, unit: 'characters', required: true }, description: { max: 5000, unit: 'bytes' }, hashtags: { max: 60 }, mentions: null, forbidden: '<>' }
    : { fields: ['caption'], caption: { max: 2200, unit: 'characters' }, hashtags: { max: 30 }, mentions: { max: 20 }, forbidden: '' } });
const approvedFinal = (platform = 'instagram_reels') => {
  jobRows = [{ id: 'pj', action: 'preview', status: 'completed', revision: 7, progress: 1 }, { id: 'fj', action: 'final', status: 'completed', revision: 7, progress: 1 }];
  return { status: 'approved', approval: { digest: 'e'.repeat(64), revision: 7 }, settings: { platform, aspect: platform === 'youtube' ? 'landscape' : 'portrait' },
    artifacts: { preview: 'preview.mp4', final: 'final.mp4' }, artifact_lineage: { preview: { job_id: 'pj', platform }, final: { job_id: 'fj', platform } } };
};
const packageRest = (platform = 'instagram_reels', extra = () => undefined) => async (path, options) => {
  const handled = extra(path, options);
  if (handled !== undefined) return handled;
  if (path.endsWith('/review')) return { digest: 'e'.repeat(64), project: selectedProject, notice: '' };
  if (path.endsWith('/post')) return postStatus(platform);
  if (path.endsWith('/packages') && options?.method === 'POST') return packageResult;
  if (path.endsWith('/packages')) return [];
  if (path.endsWith('/verify')) return { ok: true, checked: 4, problems: [] };
  return selectedProject;
};
const packageCard = tree => nodes(tree).find(n => n.props?.['aria-labelledby'] === 'cutroom-package');

test('delivery package: post text with live counters, then Make package and Check package', async () => {
  const ui = await studio(packageRest(), approvedFinal());
  await ui.step('Export'); await tick(); ui.draw(); await tick();
  let tree = ui.draw();
  const card = packageCard(tree);
  assert.ok(card, 'The delivery package card is shown after approval and export');
  assert.ok(card.props['data-cutroom-post'], 'Typing post text does not clear the approval');
  assert.match(text(card), /Nothing is posted/);
  assert.equal(field(tree, 'post.caption').props.value, 'Hello');
  assert.match(text(tree), /5 \/ 2,200 characters/);
  type(field(tree, 'post.caption'), 'x'.repeat(2201));
  tree = ui.draw();
  assert.match(text(tree), /2,201 \/ 2,200 characters/);
  assert.match(text(tree), /1 too many/);
  assert.equal(button(tree, 'Make package').props.disabled, true, 'Text over a limit cannot be packaged');
  type(field(ui.draw(), 'post.caption'), 'Waves all day.');
  type(field(ui.draw(), 'post.hashtags'), 'ocean #sea');
  tree = ui.draw();
  assert.match(text(tree), /2 \/ 30 hashtags/);
  const counter = nodes(tree).find(n => n.props?.id === 'cutroom-post-caption-count');
  assert.ok(counter && field(tree, 'post.caption').props['aria-describedby'].includes('cutroom-post-caption-count'), 'Counters are tied to their fields');
  await button(tree, 'Make package').props.onClick();
  const made = ui.calls.find(c => c.path === '/projects/p1/packages' && c.options?.method === 'POST');
  assert.deepEqual(made.options.body, { post: { title: 'Demo', caption: 'Waves all day.', hashtags: ['#ocean', '#sea'] } });
  tree = ui.draw();
  assert.match(text(tree), /instagram_reels-20261113-101500/);
  assert.match(text(tree), /video\.mp4/);
  assert.match(text(tree), /5\.0 MB/);
  assert.match(text(tree), /Nothing has been posted\. Upload these files yourself\./);
  await button(tree, 'Check package').props.onClick();
  assert.ok(ui.calls.some(c => c.path === '/projects/p1/packages/instagram_reels-20261113-101500/verify' && c.options?.method === 'POST'));
  assert.match(text(ui.draw()), /All 4 files match/);
  // The approval survives typing in the package card.
  const workspace = nodes(ui.draw()).find(n => n.props?.['aria-label'] === 'Project editing workspace');
  workspace.props.onChangeCapture({ target: { closest: selector => (selector.includes('data-cutroom-post') ? {} : null) } });
  assert.ok(button(ui.draw(), 'Make package'), 'Still approved');
});

test('delivery package: a changed file is reported in plain words', async () => {
  const ui = await studio(packageRest('instagram_reels', path => (path.endsWith('/packages') ? [packageResult] : path.endsWith('/verify') ? { ok: false, checked: 4, problems: [{ file: 'video.mp4', problem: 'contents changed (checksum differs)' }] } : undefined)), approvedFinal());
  await ui.step('Export'); await tick(); ui.draw(); await tick();
  const tree = ui.draw();
  assert.match(text(tree), /instagram_reels-20261113-101500/, 'The latest package is listed');
  await button(tree, 'Check package').props.onClick();
  assert.match(text(ui.draw()), /video\.mp4: contents changed/);
});

test('delivery package: YouTube asks for a title and counts the description in bytes with chapters', async () => {
  const ui = await studio(packageRest('youtube'), approvedFinal('youtube'));
  await ui.step('Export'); await tick(); ui.draw(); await tick();
  let tree = ui.draw();
  assert.ok(field(tree, 'post.title'));
  assert.match(text(tree), /4 \/ 100 characters/);
  // "Hello", a blank line and three chapter lines: 5 + 2 + 30 bytes.
  assert.match(text(tree), /37 \/ 5,000 bytes/);
  type(field(tree, 'post.caption'), '\u00e9'.repeat(10));
  assert.match(text(ui.draw()), /52 \/ 5,000 bytes/);
  type(field(ui.draw(), 'post.title'), 'A <b> title');
  tree = ui.draw();
  assert.match(text(tree), /cannot contain < or >/);
  assert.equal(button(tree, 'Make package').props.disabled, true);
  type(field(ui.draw(), 'post.title'), '');
  assert.equal(button(ui.draw(), 'Make package').props.disabled, true, 'YouTube needs a title');
});

test('delivery package waits for an approved, exported final', async () => {
  jobRows = currentPreview().jobs;
  const ui = await studio(packageRest(), { ...currentPreview().project, settings: { platform: 'instagram_reels' } });
  await ui.step('Export'); await tick();
  assert.equal(button(ui.draw(), 'Make package'), undefined);
  assert.match(text(ui.draw()), /After you approve and export the final video/);
  assert.ok(!ui.calls.some(c => c.path.endsWith('/post')), 'Nothing is read before it can be used');
});
