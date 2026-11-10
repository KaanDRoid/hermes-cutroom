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
const sdk = {
  ROUTES_AREA: 'routes', SIDEBAR_NAV_AREA: 'sidebar.nav', PALETTE_AREA: 'palette',
  host: { navigate: path => navigation.push(path), state: { profile: { get: () => 'default' } } },
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
  const replaced = source.replace(/import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"];?/g,
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

test('uses only public SDK/React imports and no renderer or polling bypasses', async () => {
  await load();
  assert.ok(imports.length > 0);
  for (const [, , specifier] of imports) assert.ok(['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'].includes(specifier));
  assert.doesNotMatch(source, /window\.|hermesDesktop|__HERMES|\beval\(|new Function|\bsetInterval\(|\bsetTimeout\(|\bfetch\(|document\./);
  assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|rgb\(/);
});
