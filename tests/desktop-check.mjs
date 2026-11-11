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
  const kind = options.queryKey.find(x => ['projects', 'project', 'jobs'].includes(x));
  return { data: options.enabled === false ? undefined : kind === 'projects' ? projectRows : kind === 'project' ? selectedProject : jobRows,
    isPending: false, isFetching: false, error: null, refetch: () => options.queryFn() };
};
sdk.useQueryClient = () => ({ invalidateQueries: options => invalidations.push(options), setQueryData: () => {} });
sdk.useMutation = options => ({ isPending: false, error: null, reset() {},
  mutateAsync: async input => { const result = await options.mutationFn(input); await options.onSuccess?.(result, input); return result; } });
function render(node, path = 'root') {
  if (node == null || typeof node !== 'object') return node;
  if (Array.isArray(node)) return node.map((n, i) => render(n, `${path}.${i}`));
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
  if (node == null) return '';
  if (typeof node !== 'object') return String(node);
  if (Array.isArray(node)) return node.map(text).join(' ');
  return text(node.props?.children);
}
function draw(route) { const tree = render(route.render()); while (effects.length) effects.shift()(); return tree; }
function button(tree, label) { return nodes(tree).find(n => n.type === 'Button' && text(n).includes(label)); }
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

test('registers a native route, sidebar entry and palette command', async () => {
  const module = await load();
  const ctx = { register: record => records.push(record) };
  module.default.register(ctx);
  assert.equal(module.default.id, 'cutroom');
  const route = records.find(record => record.area === sdk.ROUTES_AREA);
  assert.equal(route.data.path, '/cutroom');
  assert.equal(typeof route.render, 'function');
  assert.ok(records.some(record => record.area === sdk.SIDEBAR_NAV_AREA && record.data.path === '/cutroom'));
  records.find(record => record.area === sdk.PALETTE_AREA).data.run();
  assert.equal(navigation.at(-1), '/cutroom');
});

test('imports a local path, selects the result and scopes cached queries to the profile', async () => {
  hookStores.clear(); queries.length = 0;
  const calls = [];
  projectRows = [{ id: 'p1', name: 'Local demo', revision: 1, source: 'input.mp4', settings: {}, artifacts: {} }];
  selectedProject = projectRows[0];
  const module = await load();
  const registrations = [];
  module.default.register({ register: entry => registrations.push(entry),
    storage: { get: (_key, fallback) => fallback, set() {} },
    rest: async (path, options) => { calls.push({ path, options }); return selectedProject; } });
  const route = registrations.find(r => r.area === sdk.ROUTES_AREA);
  let tree = draw(route);
  assert.match(text(tree), /Local demo/);
  const input = nodes(tree).find(n => n.type === 'Input' && n.props.name === 'source');
  assert.ok(input, 'Local source path input is rendered');
  input.props.onChange({ target: { value: 'C:/raw/demo.mp4' } });
  tree = draw(route);
  await button(tree, 'Import video').props.onClick();
  assert.equal(calls[0].path, '/projects');
  assert.deepEqual(calls[0].options.body, { source: 'C:/raw/demo.mp4' });
  tree = draw(route);
  assert.match(text(tree), /Revision 1/);
  assert.ok(queries.some(q => q.queryKey.includes('default') && q.queryKey.includes('project') && q.queryKey.includes('p1')));
  assert.ok(queries.some(q => q.queryKey.includes('jobs') && q.refetchInterval >= 2000));
});

test('edits timed words, reviews fillers, selects grounded hooks and saves local settings', async () => {
  hookStores.clear(); jobRows = [];
  selectedProject = { id: 'p1', name: 'Demo', revision: 7, source: 'in.mp4', source_info: { duration: 12, width: 1920, height: 1080 },
    settings: { aspect: 'source', brand: {} }, artifacts: {}, excluded_word_ids: [],
    transcript: { words: [{ id: 'w1', text: 'um', start: 0, end: 0.4 }, { id: 'w2', text: 'Hello', start: 1, end: 2 }],
      fillers: [{ text: 'um', word_ids: ['w1'], start: 0, end: 0.4 }] },
    story: { hooks: [{ text: 'First', start: 0, end: 2 }, { text: 'Second', start: 2, end: 4 }, { text: 'Third', start: 4, end: 6 }], storyboard: [{ source_start: 0, source_end: 2, text: 'Hello' }] },
    analysis: { sampled_frames: 2, coverage: { complete: false, mode: 'sampled' }, frames: [{ time: 0, face_count: 1, gaze_score: 0.7 }], intervals: [] } };
  projectRows = [selectedProject];
  const calls = [];
  const entries = [];
  (await load()).default.register({ register: item => entries.push(item), storage: { get: () => 'p1', set() {} }, rest: async (path, options) => {
    calls.push({ path, options });
    if (options?.method === 'PATCH') selectedProject = { ...selectedProject, ...options.body.changes, revision: selectedProject.revision + 1 };
    return selectedProject;
  } });
  const route = entries.find(item => item.area === sdk.ROUTES_AREA);
  let tree = draw(route);
  assert.match(text(tree), /Fillers/);
  assert.match(text(tree), /not verified eye contact/i);
  const word = nodes(tree).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'Include word w1');
  assert.ok(word, 'Timed word inclusion is editable');
  await word.props.onCheckedChange(false);
  assert.deepEqual(calls.find(call => call.options?.method === 'PATCH').options.body, { revision: 7, changes: { excluded_word_ids: ['w1'] } });
  tree = draw(route);
  await button(tree, 'Use hook 2').props.onClick();
  assert.ok(calls.some(call => call.options?.body?.changes?.selected_hook === 1));
  tree = draw(route);
  nodes(tree).find(n => n.type === 'Input' && n.props.name === 'whisper_model').props.onChange({ target: { value: 'C:/models/whisper.bin' } });
  tree = draw(route);
  await button(tree, 'Save settings').props.onClick();
  assert.ok(calls.some(call => call.options?.body?.changes?.settings?.whisper_model === 'C:/models/whisper.bin'));
});

async function studio(rest, extra = {}) {
  hookStores.clear(); queries.length = 0; invalidations.length = 0;
  selectedProject = { id: 'p1', name: 'Demo', revision: 7, source: 'in.mp4', settings: {}, artifacts: {}, source_info: { duration: 12 }, ...extra };
  projectRows = [selectedProject];
  const entries = [], calls = [];
  (await load()).default.register({ register: x => entries.push(x), storage: { get: () => 'p1', set() {} }, rest: async (path, options) => { calls.push({ path, options }); return rest(path, options); } });
  const route = entries.find(x => x.area === sdk.ROUTES_AREA);
  return { calls, draw: () => draw(route) };
}

test('submits allowlisted jobs, exposes failures, retries and cancels running work', async () => {
  jobRows = [{ id: 'j1', action: 'vision', status: 'running', progress: 0.25 }, { id: 'j2', action: 'transcribe', status: 'failed', error: 'Missing model', options: {} }];
  const ui = await studio(async () => ({ id: 'new-job' }));
  let tree = ui.draw();
  assert.match(text(tree), /Missing model/);
  assert.equal(nodes(tree).find(n => n.type === 'progress').props.value, 0.25);
  assert.equal(button(tree, 'Run final').props.disabled, true);
  await button(tree, 'Run preview').props.onClick();
  assert.deepEqual(ui.calls.at(-1), { path: '/projects/p1/jobs', options: { method: 'POST', body: { action: 'preview', options: {} } } });
  await button(ui.draw(), 'Cancel vision').props.onClick();
  assert.equal(ui.calls.at(-1).path, '/jobs/j1/cancel');
  await button(ui.draw(), 'Retry transcribe').props.onClick();
  assert.equal(ui.calls.at(-1).options.body.action, 'transcribe');
  assert.ok(invalidations.length >= 3);
  assert.ok(queries.some(q => q.queryKey.includes('jobs') && q.refetchInterval >= 2000));
  assert.equal(button(ui.draw(), 'Run publish'), undefined);
});

test('requires exact human confirmation, rereads review and blocks stale approval callbacks', async () => {
  jobRows = [];
  const digest = 'a'.repeat(64);
  let changed = false;
  const ui = await studio(async (path, options) => {
    if (path.endsWith('/review')) return { digest: changed ? 'b'.repeat(64) : digest, project: selectedProject, notice: 'Review every cut' };
    if (path.endsWith('/approve')) { selectedProject = { ...selectedProject, approval: { digest, revision: 7 } }; return selectedProject; }
    return selectedProject;
  });
  let tree = ui.draw();
  await button(tree, 'Review current revision').props.onClick();
  tree = ui.draw();
  assert.match(text(tree), /Review every cut/);
  assert.equal(button(tree, 'Approve reviewed digest').props.disabled, true);
  nodes(tree).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'I reviewed this exact digest').props.onCheckedChange(true);
  await button(ui.draw(), 'Approve reviewed digest').props.onClick();
  assert.deepEqual(ui.calls.find(c => c.path.endsWith('/approve')).options.body, { digest, confirmed: true });
  tree = ui.draw();
  assert.equal(button(tree, 'Run final').props.disabled, false);
  const staleFinal = button(tree, 'Run final').props.onClick;
  nodes(tree).find(n => n.props['aria-label'] === 'Project editing workspace').props.onChangeCapture();
  await staleFinal();
  assert.ok(!ui.calls.some(c => c.options?.body?.action === 'final'));
  assert.equal(button(ui.draw(), 'Run final').props.disabled, true);
  await button(ui.draw(), 'Review current revision').props.onClick();
  nodes(ui.draw()).find(n => n.type === 'Checkbox' && n.props['aria-label'] === 'I reviewed this exact digest').props.onCheckedChange(true);
  changed = true;
  const before = ui.calls.filter(c => c.path.endsWith('/approve')).length;
  await button(ui.draw(), 'Approve reviewed digest').props.onClick();
  assert.equal(ui.calls.filter(c => c.path.endsWith('/approve')).length, before);
  assert.match(text(ui.draw()), /changed/i);
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
    let tree = ui.draw();
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

test('downloads canonical artifacts through a read-scoped native save action', async () => {
  const saves = [], order = [];
  sdk.captureGatewayFileDownload = () => { order.push('capture'); return async (...args) => saves.push(args); };
  const ui = await studio(async path => { order.push(path); return { path: 'server/persisted/result.srt', name: 'result.srt', mime: 'text/plain', size: 12, version: 'v1' }; }, { artifacts: { captions_srt: 'x', captions_vtt: 'x', quality: 'x', cover: 'x' } });
  await button(ui.draw(), 'Download SRT').props.onClick();
  assert.deepEqual(order, ['capture', '/projects/p1/artifact-info/captions_srt']);
  assert.deepEqual(saves, [['server/persisted/result.srt', 'result.srt']]);
  for (const label of ['Download VTT', 'Download report', 'Download cover']) assert.ok(button(ui.draw(), label));
  delete sdk.captureGatewayFileDownload;
  await button(ui.draw(), 'Download VTT').props.onClick();
  assert.match(text(ui.draw()), /does not support native downloads/);
});

test('edits timed captions and manual ranges without erasing word metadata or exclusions', async () => {
  jobRows = [];
  const transcript = { language: 'en', engine: 'whisper', status: 'ok', text: 'Helo world', words: [{ id: 0, text: 'Helo', start: 1, end: 2, probability: 0.9 }, { id: 1, text: 'world', start: 3, end: 4, probability: 0.8 }] };
  const ui = await studio(async (_path, options) => { if (options?.method === 'PATCH') selectedProject = { ...selectedProject, ...options.body.changes, revision: selectedProject.revision + 1 }; return selectedProject; }, { transcript, base_segments: [{ start: 1, end: 8 }], segments: [{ start: 1, end: 8 }], excluded_word_ids: [1] });
  let tree = ui.draw();
  const correction = nodes(tree).find(n => n.type === 'Input' && n.props.name === 'caption.0');
  assert.ok(correction, 'Timed caption text can be corrected');
  correction.props.onChange({ target: { value: 'Hello' } });
  await button(ui.draw(), 'Save caption corrections').props.onClick();
  const updated = ui.calls.find(c => c.options?.body?.changes?.transcript).options.body.changes;
  assert.equal(updated.transcript.words[0].text, 'Hello');
  assert.equal(updated.transcript.words[0].probability, 0.9);
  assert.equal(updated.transcript.words[1].id, 1);
  assert.equal(updated.excluded_word_ids, undefined);
  tree = ui.draw();
  nodes(tree).find(n => n.type === 'Input' && n.props.name === 'range.0.end').props.onChange({ target: { value: '7' } });
  await button(ui.draw(), 'Save manual ranges').props.onClick();
  assert.deepEqual(ui.calls.find(c => c.options?.body?.changes?.segments).options.body.changes, { segments: [{ start: 1, end: 7 }] });
  nodes(ui.draw()).find(n => n.type === 'Input' && n.props.name === 'brand.title_size').props.onChange({ target: { value: '2' } });
  const before = ui.calls.length;
  await button(ui.draw(), 'Save settings').props.onClick();
  assert.equal(ui.calls.length, before);
  assert.match(text(ui.draw()), /12.*120/);
});

test('submits only supported action options and rejects invalid silence input', async () => {
  jobRows = [];
  const ui = await studio(async () => ({ id: 'j1' }));
  let tree = ui.draw();
  const field = name => nodes(ui.draw()).find(n => n.type === 'Input' && n.props.name === name);
  assert.ok(field('job.language'));
  field('job.language').props.onChange({ target: { value: 'en' } });
  await button(ui.draw(), 'Run transcribe').props.onClick();
  assert.deepEqual(ui.calls.at(-1).options.body.options, { language: 'en' });
  field('job.noise_db').props.onChange({ target: { value: '-32' } });
  field('job.min_duration').props.onChange({ target: { value: '0.5' } });
  await button(ui.draw(), 'Run silence').props.onClick();
  assert.deepEqual(ui.calls.at(-1).options.body.options, { noise_db: -32, min_duration: 0.5 });
  field('job.min_duration').props.onChange({ target: { value: '-1' } });
  const before = ui.calls.length;
  await button(ui.draw(), 'Run silence').props.onClick();
  assert.equal(ui.calls.length, before);
  assert.match(text(ui.draw()), /positive/);
  assert.equal(field('job.model_path'), undefined, 'Model paths come from saved settings only');
  field('job.language').props.onChange({ target: { value: 'English' } });
  const rejected = ui.calls.length;
  await button(ui.draw(), 'Run transcribe').props.onClick();
  assert.equal(ui.calls.length, rejected);
  assert.match(text(ui.draw()), /two- or three-letter/);
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
  ui = await studio(async () => selectedProject, { selected_hook: 1, story: { hooks, storyboard: [{ source_start: 0, source_end: 1, text: 'One' }], selected_hook: 1, opening_hook: hooks[1] } });
  assert.match(text(ui.draw()), /Opening hook: Two/);
});

test('keeps selected project fresh after a job finishes and releases player URLs on revision changes', async () => {
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
  const revoked = [];
  URL.createObjectURL = () => 'blob:revision-test';
  URL.revokeObjectURL = value => revoked.push(value);
  try {
    jobRows = [{ id: 'done', action: 'preview', status: 'completed', progress: 1 }];
    const ui = await studio(async () => ({ data: btoa('abc'), offset: 0, next_offset: 3, total: 3, mime: 'video/mp4', version: 'v1' }));
    ui.draw();
    assert.ok(queries.some(query => query.queryKey.includes('project') && query.enabled && query.refetchInterval >= 2000), 'Completion must not stop project refresh before artifacts arrive');
    await button(ui.draw(), 'Load source').props.onClick();
    ui.draw();
    selectedProject = { ...selectedProject, revision: 8 };
    ui.draw();
    assert.deepEqual(revoked, ['blob:revision-test']);
    assert.equal(nodes(ui.draw()).find(n => n.type === 'video'), undefined);
  } finally { URL.createObjectURL = create; URL.revokeObjectURL = revoke; }
});

test('uses only public SDK/React imports and no renderer or polling bypasses', async () => {
  await load();
  assert.ok(imports.length > 0);
  for (const [, , specifier] of imports) assert.ok(['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'].includes(specifier));
  assert.doesNotMatch(source, /window\.|hermesDesktop|__HERMES|\beval\(|new Function|\bsetInterval\(|\bsetTimeout\(|\bfetch\(|document\./);
  assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|rgb\(/);
});
