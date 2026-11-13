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
const zone = (top, bottom, left, right) => ({ top, bottom, left, right, source: 'https://example.test/spec', checked: '2026-11-12' });
const frames = portrait => ({ preview: portrait ? [1080, 1920] : [1920, 1080], final: portrait ? { 1080: [1080, 1920], 2160: [2160, 3840] } : { 1080: [1920, 1080], 2160: [3840, 2160] }, default_final: '1080' });
const platformRows = [
  { name: 'custom', label: 'Custom', short_label: 'Custom', orientation: null, frame: null, safe_zone: null },
  { name: 'instagram_reels', label: 'Instagram Reels', short_label: 'Reels', orientation: 'portrait', frame: frames(true), safe_zone: zone(0.14, 0.35, 0.06, 0.06), max_duration_s: { value: 1200 } },
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
  const kind = options.queryKey.find(x => ['projects', 'project', 'jobs', 'platforms', 'activity'].includes(x));
  return { data: options.enabled === false ? undefined : kind === 'projects' ? projectRows : kind === 'project' ? selectedProject : kind === 'platforms' ? platformRows : jobRows,
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
    await button(tree, 'Load source').props.onClick();
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
    assert.ok(button(ui.draw(), 'Load source'));
    await button(ui.draw(), 'Load preview').props.onClick();
    const tree = ui.draw();
    assert.equal(nodes(tree).find(n => n.type === 'video').props.src, 'blob:test-1');
    assert.equal(created[0].size, 6);
    assert.ok(ui.calls.some(c => c.path.includes('version=v1')));
    await button(tree, 'Unload media').props.onClick();
    assert.deepEqual(revoked, ['blob:test-1']);
    oversize = true;
    const before = ui.calls.length;
    await button(ui.draw(), 'Load source').props.onClick();
    assert.equal(ui.calls.length, before + 1);
    assert.match(text(ui.draw()), /256 MiB/);
    assert.equal(created.length, 1);
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; }
});

test('space plays and pauses unless focus is in a text field', async () => {
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  URL.createObjectURL = () => 'blob:space'; URL.revokeObjectURL = () => {};
  try {
    jobRows = [];
    const ui = await studio(async path => path.includes('/media/') ? { data: btoa('abc'), offset: 0, next_offset: 3, total: 3, mime: 'video/mp4', version: 'v1' } : selectedProject);
    await button(ui.draw(), 'Load source').props.onClick();
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
    await button(ui.draw(), 'Load preview').props.onClick();
    ui.draw();
    selectedProject = { ...selectedProject, revision: 8 };
    ui.draw();
    assert.deepEqual(revoked, ['blob:revision-1']);
    assert.equal(nodes(ui.draw()).find(n => n.type === 'video'), undefined);
    // The source never changes with a revision, so editing does not stop it.
    await button(ui.draw(), 'Load source').props.onClick();
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
  assert.match(text(tree), /180 s/);
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
    await button(ui.draw(), 'Load preview').props.onClick();
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
    await button(ui.draw(), 'Load preview').props.onClick();
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
  assert.match(text(radio(tree, 'Caption style', 'highlight')), /came from/, 'Cards show a text preview');
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
    await button(ui.draw(), 'Load preview').props.onClick();
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

test('uses only public SDK/React imports and no renderer or polling bypasses', async () => {
  await load();
  assert.ok(imports.length > 0);
  for (const [, , specifier] of imports) assert.ok(['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'].includes(specifier));
  assert.doesNotMatch(source, /window\.|hermesDesktop|__HERMES|\beval\(|new Function|(?<!ctx\.)\bsetInterval\(|(?<!ctx\.)\bsetTimeout\(|\bfetch\(|document\./);
  assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|rgb\(/);
  assert.doesNotMatch(source, /'progress'/, 'Themed progress bars only');
  assert.match(source, /prefers-reduced-motion/);
  assert.match(source, /focus-visible/);
});
