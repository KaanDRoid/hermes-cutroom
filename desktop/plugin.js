import { host, ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA, useValue, useQuery, useMutation, useQueryClient, Button, Input, Textarea, Checkbox, Badge, GlyphSpinner } from '@hermes/plugin-sdk';
import { useState, useRef, useEffect } from 'react';
import { jsx, jsxs } from 'react/jsx-runtime';
import * as SDK from '@hermes/plugin-sdk';

// Static child arrays go through jsxs so React does not ask for keys on them.
const el = (type, props = {}, key) => (Array.isArray(props.children) ? jsxs : jsx)(type, props, key);
const enc = encodeURIComponent;

const row = { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 };
const stack = { display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 };
const panel = { ...stack, padding: 16, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 10 };
const muted = { color: 'var(--ui-text-secondary)', fontSize: 12, margin: 0 };
const h2s = { fontSize: 15, fontWeight: 600, margin: 0 };
const h3s = { fontSize: 13, fontWeight: 600, margin: 0 };
const alertStyle = { ...muted, color: 'var(--ui-text-primary)' };
const hidden = { position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' };
const summaryStyle = { cursor: 'pointer', fontWeight: 600, fontSize: 13 };
// Visible keyboard focus and no motion for people who ask for less of it.
const CSS = '[data-cutroom] :focus-visible{outline:2px solid var(--ui-accent);outline-offset:2px}'
  + '@media (prefers-reduced-motion: reduce){[data-cutroom] *{transition:none !important;animation:none !important;scroll-behavior:auto !important}}';

// The host's unchecked checkbox border can match the page background; outline it with a theme token.
const Tick = props => jsx(Checkbox, { ...props, style: props.checked ? props.style : { borderColor: 'var(--ui-text-tertiary)', ...props.style } });
const errorText = error => error?.message || String(error || '');
const seconds = value => Number.isFinite(value) ? `${value.toFixed(2)}s` : '—';
const clock = value => {
  if (!Number.isFinite(value)) return '—';
  const total = Math.max(0, Math.round(value));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
};
const clamp01 = value => Math.max(0, Math.min(1, Number(value) || 0));
const pct = value => Math.round(clamp01(value) * 100);
const percent = value => `${+(value * 100).toFixed(2)}%`;
const round3 = value => Math.round(value * 1000) / 1000;
const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
const newest = list => [...list].sort((a, b) => (b.completed_at || b.created_at || 0) - (a.completed_at || a.created_at || 0));
const HEX = /^#[0-9a-f]{6}$/i;
const VIDEO_FILE = /\.(mp4|mov|m4v|webm|mkv|avi)$/i;
const AUDIO_FILE = /\.(wav|mp3|m4a|flac|ogg|aac)$/i;

function useLive(initial) {
  const [value, setValue] = useState(initial);
  const ref = useRef(value);
  ref.current = value;
  const set = next => {
    ref.current = typeof next === 'function' ? next(ref.current) : next;
    setValue(ref.current);
  };
  return [value, set, ref];
}

function Notice({ error }) {
  return error ? jsx('p', { role: 'alert', style: alertStyle, children: errorText(error) }) : null;
}

// A labelled input that keeps what the person typed (and the cursor) while saves echo back.
// onCommit returns an error string to refuse a value; refused text stays in the box.
function Field({ label, name, value, onCommit, type = 'text', placeholder = '', hint = '', disabled = false, multiline = false, hideLabel = false, style }) {
  const shown = value == null ? '' : String(value);
  const [text, setText, textRef] = useLive(shown);
  const seen = useRef(shown);
  const [problem, setProblem] = useState(null);
  let display = text;
  if (shown !== seen.current) {
    // The saved value changed elsewhere (a job, another window or an undo): show it.
    seen.current = shown;
    if (shown !== textRef.current) { display = shown; setText(shown); setProblem(null); }
  }
  const change = event => {
    const next = event.target.value;
    setText(next);
    const result = onCommit ? onCommit(next) : undefined;
    setProblem(typeof result === 'string' ? result : null);
  };
  const control = jsx(multiline ? Textarea : Input, { name, value: display, type: multiline ? undefined : type, placeholder, disabled, onChange: change, 'aria-invalid': problem ? true : undefined, 'aria-label': hideLabel ? label : undefined, style });
  return el('label', { style: { ...stack, gap: 4, fontSize: 12, ...(hideLabel ? { flex: '1 1 200px' } : {}) }, children: [
    hideLabel ? null : el('span', { children: label }),
    control,
    hint ? el('span', { style: muted, children: hint }) : null,
    problem ? el('span', { role: 'alert', style: alertStyle, children: problem }) : null,
  ] });
}

function Bar({ value, label }) {
  const now = pct(value);
  return el('div', { role: 'progressbar', 'aria-label': label, 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': now, style: { flex: '0 0 120px', height: 6, borderRadius: 3, background: 'var(--ui-stroke-secondary)', overflow: 'hidden' },
    children: el('div', { style: { width: `${now}%`, height: '100%', background: 'var(--ui-accent)' } }) });
}

const cardStyle = (checked, disabled) => ({ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 6, textAlign: 'left', padding: 10, borderRadius: 10, font: 'inherit', color: 'inherit', background: 'transparent',
  border: `${checked ? 2 : 1}px solid ${checked ? 'var(--ui-accent)' : 'var(--ui-stroke-secondary)'}`, cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.5 : 1, minWidth: 0 });

// Cards that behave as one radio group: one tab stop, arrow keys move and select.
function RadioCards({ label, value, options, onChange, disabled = false, min = 140 }) {
  const refs = useRef({});
  const enabled = options.filter(option => !option.disabled && !disabled);
  const known = options.some(option => option.value === value);
  const move = (event, option) => {
    const steps = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    const index = enabled.findIndex(item => item.value === option.value);
    let target = null;
    if (event.key in steps && enabled.length) target = enabled[(index + steps[event.key] + enabled.length) % enabled.length];
    else if (event.key === 'Home') target = enabled[0];
    else if (event.key === 'End') target = enabled.at(-1);
    if (!target) return;
    event.preventDefault?.();
    onChange(target.value);
    refs.current[target.value]?.focus?.();
  };
  return el('div', { role: 'radiogroup', 'aria-label': label, style: { display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${min}px, 1fr))`, gap: 8 }, children: options.map((option, index) => {
    const checked = option.value === value;
    const off = disabled || option.disabled;
    return el('button', { type: 'button', role: 'radio', 'aria-checked': checked, 'data-value': option.value, disabled: off, tabIndex: checked || (!known && index === 0) ? 0 : -1,
      ref: node => { refs.current[option.value] = node; }, onClick: () => onChange(option.value), onKeyDown: event => move(event, option), style: cardStyle(checked, off), children: [
        el('span', { style: { ...row, justifyContent: 'space-between', width: '100%', gap: 4 }, children: [el('strong', { style: { fontSize: 13 }, children: option.title }), checked ? el('span', { 'aria-hidden': true, children: '✓' }) : null] }),
        option.preview || null,
        option.detail ? el('span', { style: muted, children: option.detail }) : null,
      ] }, option.key || option.value);
  }) });
}

// Off / Light / Strong style choices: the native segmented control when the host has it.
function Choice({ label, value, options, onChange }) {
  if (typeof SDK.SegmentedControl === 'function') return el('div', { role: 'group', 'aria-label': label, children: jsx(SDK.SegmentedControl, { options: options.map(([id, text]) => ({ id, label: text })), value, onChange }) });
  return el('div', { role: 'group', 'aria-label': label, style: row, children: options.map(([id, text]) => jsx(Button, { variant: value === id ? 'secondary' : 'ghost', 'aria-pressed': value === id, onClick: () => onChange(id), children: text }, `choice:${id}`)) });
}

function Disclosure({ title, children, open = false }) {
  return el('details', { open: open || undefined, style: { ...stack, gap: 10 }, children: [el('summary', { style: summaryStyle, children: title }), ...(Array.isArray(children) ? children : [children])] });
}

const joinPath = (folder, relative) => {
  const separator = folder.includes('\\') && !folder.includes('/') ? '\\' : '/';
  return `${folder.replace(/[\\/]+$/, '')}${separator}${relative}`;
};

// Lists matching files in a folder the person grants through the app's own picker.
function Browse({ ctx, pattern, onPick, noun }) {
  const [list, setList] = useState(null);
  const [error, setError] = useState(null);
  if (typeof ctx.files?.requestFolder !== 'function' || typeof ctx.files?.list !== 'function') return null;
  const open = async () => {
    setError(null);
    try {
      const picked = await ctx.files.requestFolder();
      if (!picked?.ok || !picked.folder) { if (picked?.message) setError(new Error(picked.message)); return; }
      const listing = await ctx.files.list(picked.folder.id, '');
      if (!listing?.ok) throw new Error(listing?.message || 'That folder could not be listed');
      setList({ folder: picked.folder, entries: (listing.entries || []).filter(entry => !entry.isDirectory && pattern.test(entry.name)).slice(0, 200) });
    } catch (failure) { setError(failure); }
  };
  return el('div', { style: { ...stack, gap: 6 }, children: [
    jsx(Button, { variant: 'secondary', onClick: open, children: 'Browse…' }),
    list ? el('div', { role: 'group', 'aria-label': `${noun} in ${list.folder.name || 'the folder'}`, style: { ...stack, gap: 4, maxHeight: 220, overflow: 'auto' }, children: [
      list.entries.length ? null : el('p', { style: muted, children: `No ${noun.toLowerCase()} in this folder.` }),
      ...list.entries.map(entry => jsx(Button, { variant: 'ghost', onClick: () => { onPick(joinPath(list.folder.path, entry.path || entry.name)); setList(null); }, children: entry.name }, `file:${entry.path || entry.name}`)),
      jsx(Button, { variant: 'ghost', onClick: () => setList(null), children: 'Close list' }, 'close'),
    ] }) : null,
    jsx(Notice, { error }),
  ] });
}

const ACTIVE = ['queued', 'running'];
const jobActions = ['transcribe', 'silence', 'vision', 'segment', 'storyboard', 'preview', 'final', 'cover', 'qa'];
const JOB_WORDS = {
  inspect: ['Reading the video', 'Video check'], transcribe: ['Transcribing', 'Transcript'], silence: ['Finding pauses', 'Pause search'],
  vision: ['Analysing faces', 'Face analysis'], segment: ['Separating the background', 'Background layer'], storyboard: ['Building the story', 'Story'],
  preview: ['Making preview', 'Preview'], final: ['Exporting final video', 'Final video'], cover: ['Making cover', 'Cover'], qa: ['Checking the video', 'Video check'],
};
const jobWords = action => JOB_WORDS[action] || [action, action];
const STEPS = [['edit', 'Edit'], ['style', 'Style'], ['sound', 'Sound'], ['review', 'Review'], ['export', 'Export']];
const CAPTION_STYLES = [['off', 'Off', 'No captions on the video'], ['classic', 'Classic', 'Full lines'], ['highlight', 'Highlight', 'The spoken word lights up'], ['pop', 'Pop', 'Each word pops in'], ['one_word', 'One word', 'One large word at a time']];
const TRANSITIONS = [['cut', 'Cut'], ['crossfade', 'Crossfade'], ['dip', 'Dip to black']];
const PACING_KEYS = ['punch_in', 'punch_in_zoom', 'max_upscale', 'push_in', 'push_in_zoom', 'max_pause', 'transition', 'transition_duration'];
// [low, high, label] for the numbers under More pacing options; blank uses the backend default.
const PACING_BOUNDS = { punch_in_zoom: [1.05, 1.3, 'Punch-in zoom'], push_in_zoom: [1.02, 1.15, 'Push-in zoom'], max_upscale: [1, 4, 'Most enlargement'], transition_duration: [0.04, 0.5, 'Transition length'] };
const FRAMINGS = [['fit', 'Fit', 'Whole picture, bars around it'], ['blur_fill', 'Blur fill', 'Whole picture on a soft background'], ['center_crop', 'Center crop', 'Fills the frame from the middle'], ['face_track', 'Face track', 'Follows the speaker']];
const PLATFORM_NAMES = { custom: 'Custom', instagram_reels: 'Instagram Reels', youtube_shorts: 'YouTube Shorts', tiktok: 'TikTok', youtube: 'YouTube' };
const ratioOf = shape => ({ portrait: '9:16', landscape: '16:9', square: '1:1' }[shape] || 'Original');
const minutes = value => value >= 60 ? `${Math.round(value / 60)} min` : `${value} s`;

// Plain sentences for quality checks; [what it checks, note when it needs a look].
const CHECK_TEXT = {
  probe: ['The file can be opened'], decode: ['The whole video plays without errors'], duration: ['The length matches the edit'],
  resolution: ['The picture size is as expected'], frame_timing: ['Frames play at an even pace'], signalstats: ['Picture levels look normal'],
  black_frames: ['No unexpected black frames', 'Some frames are black; check that this is intended.'],
  freeze_frames: ['No frozen picture', 'The picture stands still for a moment; check that this is intended.'],
  audio: ['The sound track is present'], audio_clipping: ['No distorted sound', 'Some loud moments may sound distorted.'],
  audio_gaps: ['No unexpected silent gaps', 'There are silent gaps; check that they are intended.'],
  audio_loudness: ['Speech volume is even'], mix_loudness: ['Music and voice are balanced', 'The music may be too loud or too quiet next to the voice.'],
  music: ['Music is mixed in correctly'], captions: ['Captions are present'], caption_bounds: ['Captions fit on screen'],
  caption_timing: ['Each word appears on time'], safe_area: ['Text stays clear of the edges'], safe_zone: ['Captions stay clear of app buttons', 'Some text may sit under the app\u2019s buttons.'],
  platform_duration: ['The length fits the platform', 'The video is longer than the platform recommends.'], platform_frame: ['The frame size fits the platform'],
  platform_fps: ['The frame rate fits the platform'], platform_loudness: ['Loudness fits the platform', 'The sound is louder or quieter than the platform expects.'],
  platform_upscale: ['Picture sharpness', 'The picture is enlarged from a smaller source, so it may look slightly softer.'],
  framing_upscale: ['Picture sharpness', 'The picture is enlarged from a smaller source, so it may look slightly softer.'],
  framing_frames: ['Every frame of the crop is in place'],
  framing_smoothness: ['The crop moves smoothly', 'The crop moves faster than it should in places.'],
  framing_face_safe_zone: ['The face stays in the safe area', 'The face leaves the safe area in some frames, or no face was found to check.'],
  framing_face_coverage: ['A face is found through most of the video', 'A face was found in less than half of the video, so the crop may stay in the centre.'],
  pacing_upscale: ['Zooms stay within the sharpness limit', 'A zoom enlarges the picture more than allowed, or the framing already enlarges it so much that zooms were left out.'],
  pacing_face: ['Zoomed shots keep the face in the safe area', 'In some zoomed shots the face sits outside the safe area.'],
  pacing_transitions: ['Every cut has its transition', 'Some cuts kept a plain cut because a piece of the edit is very short.'],
  pacing_max_pause: ['No pause is longer than you chose', 'Some pauses are longer than the limit you set.'],
};
const STATUS_MARK = { pass: ['✓', 'OK'], warning: ['!', 'Note'], fail: ['✕', 'Problem'], skip: ['–', 'Not checked'] };

// The headline comes from check statuses: a warning sets `passed` false but does not block approval.
function qaHeadline(checks) {
  const list = Array.isArray(checks) ? checks : [];
  const fails = list.filter(check => check?.status === 'fail').length;
  const notes = list.filter(check => check?.status === 'warning').length;
  if (fails) return { text: 'Needs attention', detail: `${plural(fails, 'problem')}${notes ? ` and ${plural(notes, 'note')}` : ''}. Fix them, or approve only if you are sure.` };
  if (notes) return { text: `Ready, with ${plural(notes, 'note')}`, detail: 'Nothing blocks approval. Read the notes below.' };
  return { text: 'Ready to approve', detail: 'Every check passed.' };
}

function chatQa(qa) {
  if (!qa || typeof qa !== 'object') return 'Not checked yet';
  const failed = Number(qa.failed) || 0, warnings = Number(qa.warnings) || 0;
  if (failed || qa.status === 'fail') return 'Needs attention';
  if (warnings || qa.status === 'warning') return `Ready, with ${plural(warnings || 1, 'note')}`;
  return qa.status === 'pass' ? 'All checks passed' : 'Not checked yet';
}

function plainStatus(project, jobs) {
  const job = jobs.find(item => item.project_id === project.id && ACTIVE.includes(item.status));
  if (job) return `${jobWords(job.action)[0]} · ${pct(job.progress)}%`;
  if (project.artifacts?.final) return 'Exported';
  if (project.status === 'approved') return 'Approved';
  if (project.artifacts?.preview) return 'Ready to review';
  if (project.transcript?.words?.length) return 'Editing';
  return 'Not transcribed yet';
}

const platformOf = (platforms, project) => platforms.find(item => item.name === (project.settings?.platform || 'custom')) || null;

const readDefaults = ctx => {
  const value = ctx.storage?.get?.('defaults', {});
  return value && typeof value === 'object' ? value : {};
};

// Settings a new Desktop project gets from Settings → Plugins → Cutroom, or null.
function defaultSettings(defaults) {
  const settings = {};
  for (const key of ['whisper_model', 'face_model', 'segmentation_model']) if (typeof defaults[key] === 'string' && defaults[key].trim()) settings[key] = defaults[key].trim();
  if (defaults.platform && defaults.platform !== 'custom' && defaults.platform in PLATFORM_NAMES) settings.platform = defaults.platform;
  // Highlighted word captions are the default for new videos until the person picks another style.
  const style = defaults.caption_style || 'highlight';
  if (style === 'off') settings.captions = false;
  else if (CAPTION_STYLES.some(([value]) => value === style)) { settings.caption_style = style; settings.captions = true; }
  // Long-form YouTube delivers sidecar captions; burn-in stays opt-in.
  if (settings.platform === 'youtube') settings.captions = false;
  return Object.keys(settings).length ? settings : null;
}

// Chat cards ask the Studio to open a project; module state is reset on dispose.
const opener = { pending: null, listeners: new Set() };
function requestOpen(id, step) {
  opener.pending = { id, step };
  for (const listener of opener.listeners) listener();
  host.navigate('/cutroom');
}

function StudioPage({ ctx }) {
  const profile = useValue(host.state.profile);
  // Two hosts can share a profile name; the connection id keeps their caches apart.
  const connection = host.state.connectionId ? useValue(host.state.connectionId) || 'local' : 'local';
  return jsx(StudioScope, { ctx, profile, connection }, `${connection}\u0000${profile}`);
}

function StudioScope({ ctx, profile, connection }) {
  const scope = ['cutroom', connection, profile];
  const storageKey = `lastProject:${connection}:${profile}`;
  const [selected, select] = useState(() => ctx.storage.get(storageKey, ''));
  const [step, setStep] = useState('edit');
  const [opened, setOpened] = useState(0);
  const [error, setError] = useState(null);
  const projects = useQuery({ queryKey: [...scope, 'projects'], queryFn: () => ctx.rest('/projects'), refetchInterval: 5000 });
  const activity = useQuery({ queryKey: [...scope, 'activity'], queryFn: () => ctx.rest('/jobs'), enabled: !selected, refetchInterval: 5000 });
  // Keep polling while a job runs even if the window is hidden, so a finished render is not shown as queued.
  const working = useRef(false);
  const jobs = useQuery({ queryKey: [...scope, 'jobs', selected], queryFn: () => ctx.rest(`/jobs?project_id=${enc(selected)}`), enabled: Boolean(selected), refetchInterval: 2500, refetchIntervalInBackground: working.current });
  working.current = Array.isArray(jobs.data) && jobs.data.some(job => ACTIVE.includes(job.status));
  const project = useQuery({ queryKey: [...scope, 'project', selected], queryFn: () => ctx.rest(`/projects/${enc(selected)}`), enabled: Boolean(selected), refetchInterval: 2500, refetchIntervalInBackground: working.current });
  // Sourced platform profiles drive the cards, derive buttons and safe-zone overlay.
  const platforms = useQuery({ queryKey: [...scope, 'platforms'], queryFn: () => ctx.rest('/platforms'), staleTime: 300000 });
  const choose = (id, next = 'edit') => { select(id); setStep(next); ctx.storage.set(storageKey, id); setError(null); };
  useEffect(() => {
    const listener = () => setOpened(count => count + 1);
    opener.listeners.add(listener);
    return () => { opener.listeners.delete(listener); };
  }, []);
  useEffect(() => {
    const request = opener.pending;
    if (!request) return;
    opener.pending = null;
    choose(request.id, request.step);
  }, [opened]);
  const platformList = Array.isArray(platforms.data) ? platforms.data : [];
  let body;
  if (!selected) body = jsx(Home, { ctx, scope, projects: Array.isArray(projects.data) ? projects.data : [], jobs: Array.isArray(activity.data) ? activity.data : [], platforms: platformList, choose, report: setError, loading: projects.isPending }, 'home');
  else if (project.data) body = jsx(ProjectEditor, { ctx, scope, project: project.data, jobs: Array.isArray(jobs.data) ? jobs.data : [], platforms: platformList, step, setStep, open: choose, back: () => choose('') }, project.data.id);
  else body = el('div', { style: stack, children: [project.error ? null : jsx(GlyphSpinner, {}), jsx(Button, { variant: 'ghost', onClick: () => choose(''), children: '‹ Projects' })] }, 'loading');
  return el('main', { 'aria-label': 'Cutroom', 'data-cutroom': '', style: { ...stack, padding: 16, overflow: 'auto', height: '100%', boxSizing: 'border-box', color: 'var(--ui-text-primary)' }, children: [
    el('style', { children: CSS }, 'css'),
    jsx(Notice, { error: error || projects.error || project.error || jobs.error }, 'notice'),
    body,
  ] });
}

function Home({ ctx, scope, projects, jobs, platforms, choose, report, loading }) {
  const client = useQueryClient();
  const [source, setSource, sourceRef] = useLive('');
  const [error, setError] = useState(null);
  const create = useMutation({ mutationFn: path => ctx.rest('/projects', { method: 'POST', body: { source: path }, timeoutMs: 120000 }) });
  const importVideo = async () => {
    const path = sourceRef.current.trim();
    if (!path) return;
    setError(null);
    try {
      const created = await create.mutateAsync(path);
      const settings = defaultSettings(readDefaults(ctx));
      let problem = null;
      if (settings && created?.id) {
        try { await ctx.rest(`/projects/${enc(created.id)}`, { method: 'PATCH', body: { changes: { settings }, revision: created.revision } }); }
        catch (failure) { problem = new Error(`The video was imported, but your default settings could not be applied: ${errorText(failure)}`); }
      }
      setSource('');
      client.invalidateQueries({ queryKey: scope });
      choose(created.id);
      if (problem) report(problem);
    } catch (failure) { setError(failure); }
  };
  const label = item => platforms.find(entry => entry.name === (item.settings?.platform || 'custom'))?.label || PLATFORM_NAMES[item.settings?.platform || 'custom'] || 'Custom';
  const when = item => (typeof SDK.relativeTime === 'function' && Number.isFinite(item.modified_at) ? SDK.relativeTime(item.modified_at * 1000) : '');
  const sorted = [...projects].sort((a, b) => (b.modified_at || 0) - (a.modified_at || 0));
  return el('div', { style: { ...stack, gap: 20, maxWidth: 880, width: '100%', margin: '0 auto' }, children: [
    el('header', { style: { ...stack, gap: 4 }, children: [el('h1', { style: { fontSize: 22, fontWeight: 600, margin: 0 }, children: 'Cutroom' }), el('p', { style: muted, children: 'Cut a talking video by editing its words, style it for a platform, then review and export.' })] }, 'head'),
    el('section', { 'aria-labelledby': 'cutroom-make', style: panel, children: [
      el('h2', { id: 'cutroom-make', style: h2s, children: 'Make a video' }),
      el('label', { htmlFor: 'cutroom-source', style: muted, children: 'Video file on the computer that runs Cutroom' }),
      el('div', { style: { ...row, alignItems: 'flex-start' }, children: [
        jsx(Input, { id: 'cutroom-source', name: 'source', value: source, placeholder: 'C:/Videos/interview.mp4', style: { flex: '1 1 280px' }, onChange: event => setSource(event.target.value), onKeyDown: event => { if (event.key === 'Enter') importVideo(); } }),
        jsx(Browse, { ctx, pattern: VIDEO_FILE, noun: 'Videos', onPick: setSource }),
        jsx(Button, { disabled: create.isPending || !source.trim(), onClick: importVideo, children: create.isPending ? 'Importing…' : 'Import video' }),
      ] }),
      el('p', { style: muted, children: 'Cutroom never changes the original file. Browse lists files on this computer, so use it when Cutroom runs here too.' }),
      jsx(Notice, { error }),
    ] }, 'make'),
    el('section', { 'aria-labelledby': 'cutroom-recent', style: stack, children: [
      el('h2', { id: 'cutroom-recent', style: h2s, children: 'Recent projects' }),
      loading ? jsx(GlyphSpinner, {}) : null,
      sorted.length ? el('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }, children: sorted.map(item => el(Button, { variant: 'ghost', onClick: () => choose(item.id), style: { ...panel, gap: 4, padding: 12, height: 'auto', alignItems: 'flex-start', textAlign: 'left', whiteSpace: 'normal' }, children: [
        el('strong', { children: item.name }),
        el('span', { style: muted, children: [label(item), plainStatus(item, jobs), when(item)].filter(Boolean).join(' · ') }),
      ] }, item.id)) }) : el('p', { style: muted, children: loading ? '' : 'No projects yet. Import a video above to start.' }),
    ] }, 'recent'),
    el('p', { style: muted, children: 'Tip: you can also ask in Hermes chat to prepare a video. It appears here, ready for you to watch and approve.' }, 'tip'),
  ] });
}

// Shallow merge of pending patches; settings merge key by key.
function mergeChanges(a, b) {
  if (!a) return b || null;
  if (!b) return a;
  const out = { ...a, ...b };
  if (a.settings && b.settings) out.settings = { ...a.settings, ...b.settings };
  return out;
}

function overlay(project, changes) {
  if (!changes) return project;
  const out = { ...project, ...changes };
  if (changes.settings) {
    out.settings = { ...(project.settings || {}) };
    for (const [key, value] of Object.entries(changes.settings)) { if (value === null) delete out.settings[key]; else out.settings[key] = value; }
  }
  if (changes.segments) out.base_segments = changes.segments;
  return out;
}

const SOUND_KEYS = { music: ['path', 'volume_db', 'duck_db', 'fade_in', 'fade_out', 'start_offset', 'loop', 'duck', 'source_note'], cut_sfx: ['path', 'volume_db'] };
// Only the fields a person sets; hashes, durations and formats are recomputed by the backend.
const soundSpec = (group, item) => {
  if (!item || typeof item !== 'object') return null;
  const spec = {};
  for (const key of SOUND_KEYS[group]) if (item[key] !== undefined) spec[key] = item[key];
  return spec;
};
const TOP_DEFAULTS = { excluded_word_ids: [], gaze_exclusions: [], brief: '', voice: 'neutral' };
const SETTING_DEFAULTS = { platform: 'custom', caption_style: 'classic', captions: false, framing: 'fit', voice_cleanup: 'off', music: null, cut_sfx: null, caption_highlight_color: null, caption_word_y: null,
  framing_keyframes: [], pacing: null, aspect: 'source', brand: {}, title: '', normalize_audio: false, use_segmented: false, final_resolution: '1080' };

// The values an undo sends back; null when a change cannot be undone.
function previousOf(changes, view) {
  const out = {};
  for (const [key, value] of Object.entries(changes)) {
    if (key === 'settings') {
      out.settings = {};
      for (const name of Object.keys(value)) {
        const old = view.settings?.[name];
        if (old === undefined) {
          if (!(name in SETTING_DEFAULTS)) return null;
          out.settings[name] = SETTING_DEFAULTS[name];
        } else out.settings[name] = name === 'music' || name === 'cut_sfx' ? soundSpec(name, old) : old;
      }
    } else {
      const old = key === 'segments' ? view.base_segments || view.segments : view[key];
      if (old === undefined || old === null) {
        if (!(key in TOP_DEFAULTS)) return null;
        out[key] = TOP_DEFAULTS[key];
      } else out[key] = old;
    }
  }
  return out;
}

const SOUND_BOUNDS = { music: { volume_db: [-60, 0], duck_db: [12, 36], fade_in: [0, 30], fade_out: [0, 30], start_offset: [0, 86400] }, cut_sfx: { volume_db: [-60, 0] } };

// Blank numbers fall back to backend defaults; computed fields (hash, duration) are recomputed on save.
function audioSettings(value, saved = {}) {
  const result = { ...value };
  for (const group of ['music', 'cut_sfx']) {
    if (!(group in value)) continue;
    const item = value[group] || {};
    const path = typeof item.path === 'string' ? item.path.trim() : '';
    if (!path) { if (saved?.[group]) result[group] = null; else delete result[group]; continue; }
    const clean = { path };
    for (const [key, [min, max]] of Object.entries(SOUND_BOUNDS[group])) {
      if (item[key] === '' || item[key] == null) continue;
      if (!Number.isFinite(item[key]) || item[key] < min || item[key] > max) return new Error(`${group}.${key} must be between ${min} and ${max}`);
      clean[key] = item[key];
    }
    if (group === 'music') {
      if (item.source_note) clean.source_note = String(item.source_note);
      clean.loop = item.loop !== false; clean.duck = item.duck !== false;
    }
    result[group] = clean;
  }
  return result;
}

const baseSegments = view => view.base_segments || view.segments || [{ start: 0, end: view.source_info?.duration || 0 }];

function cutRange(segments, start, end) {
  const out = [];
  for (const segment of segments) {
    if (end <= segment.start || start >= segment.end) { out.push({ start: segment.start, end: segment.end }); continue; }
    if (start - segment.start > 0.05) out.push({ start: segment.start, end: start });
    if (segment.end - end > 0.05) out.push({ start: end, end: segment.end });
  }
  return out;
}

const normal = value => String(value || '').toLowerCase().replace(/[^\p{L}\p{N}']+/gu, '');

// Suggested cuts: long pauses, a word said twice in a row, and pauses the pause finder found.
function findSuggestions(view, silences = []) {
  const excluded = new Set(view.excluded_word_ids || []);
  const words = (view.transcript?.words || []).filter(word => Number.isFinite(word.start) && Number.isFinite(word.end) && !excluded.has(word.id)).sort((a, b) => a.start - b.start);
  const segments = baseSegments(view);
  const inside = time => segments.some(segment => time > segment.start && time < segment.end);
  const out = [];
  for (let index = 1; index < words.length; index++) {
    const a = words[index - 1], b = words[index];
    const gap = b.start - a.end;
    if (gap >= 0.6 && inside((a.end + b.start) / 2)) {
      const start = round3(a.end + 0.15), end = round3(b.start - 0.15);
      if (end - start >= 0.3) out.push({ key: `pause:${a.id}:${b.id}`, text: `Long pause, ${gap.toFixed(1)} s, before “${b.text}”`, cut: [start, end] });
    }
    if (normal(a.text) && normal(a.text) === normal(b.text) && gap < 1) out.push({ key: `repeat:${a.id}:${b.id}`, text: `Repeated word “${a.text} ${b.text}”`, word: a.id });
  }
  for (const gap of silences) {
    if (!(gap.end - gap.start >= 0.3) || !inside((gap.start + gap.end) / 2) || out.some(item => item.cut && item.cut[0] < gap.end && item.cut[1] > gap.start)) continue;
    out.push({ key: `silence:${round3(gap.start)}`, text: `Silence, ${(gap.end - gap.start).toFixed(1)} s, at ${clock(gap.start)}`, cut: [round3(gap.start), round3(gap.end)] });
  }
  return out;
}

function combineSuggestions(view, items) {
  const changes = {};
  const ids = [...(view.excluded_word_ids || [])];
  let segments = null;
  for (const item of items) {
    if (item.word !== undefined && !ids.includes(item.word)) ids.push(item.word);
    if (item.cut) segments = cutRange(segments || baseSegments(view), item.cut[0], item.cut[1]);
  }
  if (items.some(item => item.word !== undefined)) changes.excluded_word_ids = ids;
  if (segments) changes.segments = segments;
  return changes;
}

function ProjectEditor({ ctx, scope, project, jobs, platforms = [], step, setStep, open = () => {}, back = () => {} }) {
  const client = useQueryClient();
  const current = useRef(project);
  current.current = project;
  const busy = useRef(false);
  // Approval protocol: review the exact digest, confirm, approve, then re-verify. Any edit clears it.
  const [review, setReview, reviewRef] = useLive(null);
  const [confirmed, setConfirmed, confirmedRef] = useLive(false);
  const [approval, setApproval, approvalRef] = useLive(null);
  const [editedAfter, setEditedAfter] = useState(false);
  const epoch = useRef(0);
  const dirtyRevision = useRef(null);
  const clearApproval = () => {
    if (approvalRef.current) setEditedAfter(true);
    epoch.current++; dirtyRevision.current = current.current.revision;
    setReview(null); setConfirmed(false); setApproval(null);
  };
  const canFinal = () => Boolean(approvalRef.current && approvalRef.current.revision === current.current.revision && approvalRef.current.digest === reviewRef.current?.digest);
  const [error, setError] = useState(null);

  // Autosave: edits merge into one pending patch, sent ~500 ms after the last change against the latest revision.
  const pending = useRef(null);
  const inflight = useRef(null);
  const saved = useRef(null);
  const timer = useRef(null);
  const [save, setSave] = useState({ state: 'idle', error: null });
  const [undo, setUndo, undoRef] = useLive([]);
  const base = () => (saved.current && saved.current.id === current.current.id && saved.current.revision > current.current.revision ? saved.current : current.current);
  const computeView = () => overlay(base(), mergeChanges(inflight.current, pending.current));
  const view = computeView();
  const saving = () => Boolean(pending.current || inflight.current);
  const flush = async () => {
    if (timer.current) { timer.current(); timer.current = null; }
    if (inflight.current || !pending.current) return;
    // The API accepts six fields per patch; the rest follow in the next one.
    const all = pending.current;
    const keys = Object.keys(all);
    const changes = keys.length > 6 ? Object.fromEntries(keys.slice(0, 6).map(key => [key, all[key]])) : all;
    pending.current = keys.length > 6 ? Object.fromEntries(keys.slice(6).map(key => [key, all[key]])) : null;
    inflight.current = changes;
    setSave({ state: 'saving', error: null });
    try {
      const latest = base();
      const result = await ctx.rest(`/projects/${enc(latest.id)}`, { method: 'PATCH', body: { changes, revision: latest.revision } });
      if (result && Number.isInteger(result.revision) && result.id === latest.id) saved.current = result;
      inflight.current = null;
      client.invalidateQueries({ queryKey: scope });
      if (pending.current) return flush();
      setSave({ state: 'saved', error: null });
    } catch (failure) {
      // Never drop an edit: put it back under anything typed since, and wait for Retry or the next change.
      pending.current = mergeChanges(changes, pending.current);
      inflight.current = null;
      setSave({ state: 'error', error: failure });
    }
  };
  const schedule = () => {
    if (timer.current) timer.current();
    timer.current = null;
    if (typeof ctx.setTimeout === 'function') timer.current = ctx.setTimeout(() => { timer.current = null; flush(); }, 500);
    else flush();
  };
  const edit = (changes, label = 'Edit', group = null, record = true) => {
    if (record) {
      const previous = previousOf(changes, computeView());
      const history = undoRef.current;
      if (previous && !(group && history.at(-1)?.group === group)) setUndo([...history.slice(-49), { label, group, changes: previous }]);
    }
    clearApproval();
    pending.current = mergeChanges(pending.current, changes);
    setSave({ state: 'pending', error: null });
    schedule();
  };
  const undoLast = () => {
    const stack = undoRef.current;
    if (!stack.length) return;
    const last = stack.at(-1);
    setUndo(stack.slice(0, -1));
    edit(last.changes, last.label, null, false);
  };
  useEffect(() => () => { if (pending.current && !inflight.current) flush(); }, []);
  const leave = async () => {
    await flush();
    if (pending.current) { setSave(old => ({ ...old, state: 'error', error: old.error || new Error('Your last change is not saved yet') })); return; }
    back();
  };

  const reviewOperation = useMutation({ mutationFn: async approve => {
    const version = epoch.current;
    const path = `/projects/${enc(current.current.id)}`;
    const expected = reviewRef.current;
    if (approve && (!confirmedRef.current || !expected)) throw new Error('Confirm that you watched this version first');
    const fresh = await ctx.rest(`${path}/review`);
    if (epoch.current !== version || fresh.project.revision !== current.current.revision) throw new Error('The project changed; review it again');
    if (!approve) { setApproval(null); setConfirmed(false); setReview(fresh); return; }
    if (fresh.digest !== expected.digest) { clearApproval(); throw new Error('This version changed since you checked it; review it again'); }
    const result = await ctx.rest(`${path}/approve`, { method: 'POST', body: { digest: expected.digest, confirmed: true } });
    const verified = await ctx.rest(path);
    if (epoch.current !== version || result.approval?.digest !== expected.digest || verified.approval?.digest !== expected.digest || verified.revision !== fresh.project.revision) throw new Error('Approval changed; review again');
    setApproval(verified.approval);
    setEditedAfter(false);
    client.invalidateQueries({ queryKey: scope });
  } });
  const reviewNow = async approve => {
    if (busy.current) return;
    if (saving()) { setError(new Error('Your latest changes are still saving. Try again in a moment.')); return; }
    busy.current = true; setError(null);
    try { await reviewOperation.mutateAsync(approve); } catch (failure) { setApproval(null); setConfirmed(false); setError(failure); }
    finally { busy.current = false; }
  };

  // Renders are current when the job that made them ran on this revision.
  const jobById = id => jobs.find(job => job.id === id);
  const renderCurrent = kind => {
    const lineage = project.artifact_lineage?.[kind];
    if (!project.artifacts?.[kind] || !lineage) return false;
    const job = jobById(lineage.job_id);
    if (job) return job.revision === project.revision;
    return Boolean(review && lineage.digest && review.digest === lineage.digest && review.project?.revision === project.revision);
  };
  const previewCurrent = renderCurrent('preview');
  const qaFor = kind => newest(jobs.filter(job => job.action === 'qa' && job.status === 'completed' && job.revision === project.revision && (job.upstream === kind || job.result?.video === kind) && Array.isArray(job.result?.checks)))[0]?.result || null;

  // A saved approval is shown again only after rereading the same review; this never approves.
  const restored = useRef(null);
  useEffect(() => {
    const stored = project.approval;
    if (!['review', 'export'].includes(step) || approvalRef.current || !stored || stored.revision !== project.revision) return;
    if (restored.current === project.revision || dirtyRevision.current === project.revision || saving()) return;
    restored.current = project.revision;
    const version = epoch.current;
    Promise.resolve().then(() => ctx.rest(`/projects/${enc(project.id)}/review`)).then(fresh => {
      const now = current.current;
      if (epoch.current !== version || !fresh?.project || fresh.project.revision !== now.revision) return;
      if (!now.approval || now.approval.digest !== fresh.digest || now.approval.revision !== fresh.project.revision) return;
      setReview(fresh); setApproval(now.approval);
    }, () => {});
  }, [step, project.revision, project.approval?.digest]);
  // Opening Review on a current preview reads the review (read-only), so approval is one tick away.
  useEffect(() => {
    if (step !== 'review' || !previewCurrent || reviewRef.current || project.approval?.revision === project.revision) return;
    reviewNow(false);
  }, [step, project.revision, previewCurrent]);

  // Jobs: an allowlist, saved edits first, and final only for the approved version.
  const chain = useRef({});
  const jobLock = useRef(false);
  const [jobError, setJobError] = useState(null);
  const [jobOptions, setJobOptions, jobOptionsRef] = useLive({ language: '', noise_db: '', min_duration: '' });
  const submit = async (action, options = {}, then = null) => {
    if (!jobActions.includes(action)) throw new Error('Unsupported local action');
    if (action === 'final' && !canFinal()) throw new Error('Approve this version in Review first');
    const result = await ctx.rest(`/projects/${enc(current.current.id)}/jobs`, { method: 'POST', body: { action, options } });
    if (then?.length && result?.id) chain.current[result.id] = then;
    client.invalidateQueries({ queryKey: scope });
    return result;
  };
  const run = async (action, options = {}, then = null) => {
    if (jobLock.current) return;
    jobLock.current = true; setJobError(null);
    try {
      if (action === 'final' && !canFinal()) throw new Error('Approve this version in Review first');
      if (saving()) await flush();
      if (saving()) throw new Error('Your latest change is not saved yet. Retry saving first.');
      await submit(action, options, then);
    } catch (failure) { setJobError(failure); }
    finally { jobLock.current = false; }
  };
  const runAction = action => {
    const values = jobOptionsRef.current;
    const options = {};
    try {
      if (action === 'transcribe' && values.language.trim()) {
        const language = values.language.trim();
        if (!/^[a-z]{2,3}$/.test(language)) throw new Error('Language must be a lowercase two- or three-letter code, for example en or tr');
        options.language = language;
      }
      if (action === 'silence') for (const key of ['noise_db', 'min_duration']) if (values[key].trim()) {
        const value = Number(values[key]);
        if (!Number.isFinite(value) || (key === 'min_duration' && value <= 0)) throw new Error('Pause length must be positive and options must be numbers');
        options[key] = value;
      }
    } catch (failure) { setJobError(failure); return; }
    return run(action, options);
  };
  const cancel = async job => {
    setJobError(null);
    try { await ctx.rest(`/jobs/${enc(job.id)}/cancel`, { method: 'POST' }); client.invalidateQueries({ queryKey: scope }); } catch (failure) { setJobError(failure); }
  };
  const signature = jobs.map(job => `${job.id}:${job.status}`).join('|');
  const seen = useRef({});
  const lastNotice = useRef(0);
  useEffect(() => {
    for (const job of jobs) {
      const before = seen.current[job.id];
      seen.current[job.id] = job.status;
      const next = chain.current[job.id];
      if (next && job.status === 'completed') {
        delete chain.current[job.id];
        submit(next[0], {}, next.slice(1)).catch(failure => setJobError(failure));
      } else if (next && !ACTIVE.includes(job.status)) delete chain.current[job.id];
      // Native notice when a long job ends; the host only shows it while the window is in the background.
      if (!ACTIVE.includes(before) || !['completed', 'failed'].includes(job.status) || !['preview', 'final', 'transcribe'].includes(job.action)) continue;
      const now = Date.now();
      if (now - lastNotice.current < 10000 || typeof ctx.os?.notify !== 'function') continue;
      lastNotice.current = now;
      try { ctx.os.notify({ title: `${jobWords(job.action)[1]} ${job.status === 'completed' ? 'is ready' : 'failed'}`, body: current.current.name, activate: '/cutroom' }); } catch { /* Notifications are optional. */ }
    }
  }, [signature]);

  // Player state lives here so the transcript can seek and framing pins can read the playhead.
  const videoRef = useRef(null);
  const player = useRef(null);
  const [playback, setPlayback, playbackRef] = useLive({ kind: null, time: null });
  const seek = time => {
    const video = videoRef.current;
    if (!video || playbackRef.current.kind !== 'source' || !Number.isFinite(time)) return;
    try { video.currentTime = time; } catch { /* Seeking before metadata is harmless. */ }
  };
  const togglePlay = () => {
    const video = videoRef.current;
    if (!video) return false;
    if (video.paused) video.play?.(); else video.pause?.();
    return true;
  };
  const onKeyDown = event => {
    const tag = String(event?.target?.tagName || '').toUpperCase();
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || event?.target?.isContentEditable;
    if ((event.ctrlKey || event.metaKey) && !event.shiftKey && String(event.key).toLowerCase() === 'z' && !typing) { event.preventDefault?.(); undoLast(); return; }
    if (event.key === ' ' && !typing && !['BUTTON', 'A', 'SUMMARY'].includes(tag) && togglePlay()) event.preventDefault?.();
  };

  const correctWord = (id, text) => {
    const transcript = computeView().transcript || {};
    const words = (transcript.words || []).map(word => (word.id === id ? { ...word, text } : word));
    edit({ transcript: { ...transcript, words, text: words.map(word => word.text).join(' ') } }, 'Fix word', `word:${id}`);
  };
  const sound = (group, key, value) => {
    const latest = computeView();
    const next = { ...(soundSpec(group, latest.settings?.[group]) || {}), [key]: value };
    const result = audioSettings({ [group]: next }, base().settings);
    if (result instanceof Error) return result.message;
    if (group in result) edit({ settings: { [group]: result[group] } }, 'Sound', `${group}.${key}`);
    return undefined;
  };
  const silences = (() => {
    const job = newest(jobs.filter(item => item.action === 'silence' && item.status === 'completed' && Array.isArray(item.result?.segments)))[0];
    if (!job) return [];
    const keep = [...job.result.segments].sort((a, b) => a.start - b.start);
    const gaps = [];
    let cursor = 0;
    for (const segment of keep) { if (segment.start > cursor) gaps.push({ start: cursor, end: segment.start }); cursor = Math.max(cursor, segment.end); }
    const total = project.source_info?.duration;
    if (Number.isFinite(total) && total > cursor) gaps.push({ start: cursor, end: total });
    return gaps;
  })();

  const profile = platformOf(platforms, view);
  const shape = profile?.orientation || view.settings?.aspect || 'source';
  const kit = { ctx, scope, project, view, jobs, platforms, profile, edit, run, runAction, submit, cancel, seek, playback, setStep, open, correctWord, sound,
    jobOptions, setJobOptions, silences, review, confirmed, setConfirmed, approved: canFinal(), reviewNow, reviewPending: reviewOperation.isPending, previewCurrent,
    qa: qaFor('preview'), editedAfter, watch: () => player.current?.load('preview'), exportFinal: () => run('final', {}, ['cover', 'qa']), saving };
  const kept = (view.segments || baseSegments(view)).reduce((sum, segment) => sum + Math.max(0, segment.end - segment.start), 0);
  const index = STEPS.findIndex(([id]) => id === step);
  const next = STEPS[index + 1];
  const stepNode = { edit: EditStep, style: StyleStep, sound: SoundStep, review: ReviewStep, export: ExportStep }[step] || EditStep;
  const saveText = { pending: 'Saving…', saving: 'Saving…', error: "Couldn't save" }[save.state] || '✓ Saved';
  return el('div', { 'aria-label': 'Project editing workspace', onChangeCapture: event => { if (!event?.target?.closest?.('[data-cutroom-confirm]')) clearApproval(); }, onKeyDown, style: { ...stack, gap: 12 }, children: [
    el('header', { style: { ...row, justifyContent: 'space-between', paddingBottom: 8, borderBottom: '1px solid var(--ui-stroke-secondary)' }, children: [
      el('div', { style: { ...row, flex: '1 1 360px' }, children: [
        jsx(Button, { variant: 'ghost', 'aria-label': 'Back to projects', onClick: leave, children: '‹ Projects' }),
        jsx(Field, { label: 'Project name', hideLabel: true, name: 'project.name', value: view.name, onCommit: value => {
          const name = value.trim();
          if (!name) return 'A name cannot be empty';
          if (name.length > 200) return 'Use at most 200 characters';
          edit({ name }, 'Rename', 'name');
          return undefined;
        } }),
        el('span', { role: 'status', 'aria-live': 'polite', style: muted, children: saveText }),
        save.state === 'error' ? jsx(Button, { variant: 'secondary', onClick: () => flush(), children: 'Retry' }) : null,
      ] }),
      el('div', { style: row, children: [
        jsx(Button, { variant: 'ghost', disabled: !undo.length, onClick: undoLast, title: undo.length ? `Undo ${undo.at(-1).label.toLowerCase()} (Ctrl+Z)` : 'Nothing to undo', 'aria-keyshortcuts': 'Control+Z', children: '↶ Undo' }),
        jsx(Badge, { children: `${profile?.short_label || profile?.label || 'Custom'} · ${ratioOf(shape)}` }),
      ] }),
    ] }, 'top'),
    save.state === 'error' ? jsx(Notice, { error: new Error(`Couldn't save: ${errorText(save.error)}. Your change is kept; select Retry.`) }, 'save-error') : null,
    jsx(Notice, { error }, 'error'),
    el('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16, alignItems: 'start' }, children: [
      el('section', { 'aria-label': 'Player', style: stack, children: jsx(MediaPanel, { ctx, project, platforms, profile, videoRef, api: player, onPlayback: setPlayback }) }, 'player'),
      el('section', { 'aria-label': 'Steps', style: stack, children: [
        jsx(StepTabs, { step, setStep }, 'tabs'),
        el('div', { role: 'tabpanel', id: `cutroom-panel-${step}`, 'aria-labelledby': `cutroom-tab-${step}`, tabIndex: 0, style: { ...stack, minHeight: 200 }, children: [
          jsx(Notice, { error: jobError }, 'job-error'),
          jsx(stepNode, { kit }, `step:${step}`),
        ] }, 'panel'),
        el('div', { style: { ...row, justifyContent: 'space-between' }, children: [
          el('span', { style: muted, children: `${clock(project.source_info?.duration)} → ${clock(kept)} after cuts` }),
          next ? jsx(Button, { onClick: () => setStep(next[0]), children: `Next: ${next[1]}` }) : null,
        ] }, 'footer'),
        jsx(MoreTools, { kit }, 'more'),
      ] }, 'steps'),
    ] }, 'body'),
    jsx(Activity, { jobs, cancel, retry: job => run(job.action, job.options || {}) }, 'activity'),
  ] });
}

function StepTabs({ step, setStep }) {
  const refs = useRef({});
  const go = (event, index) => {
    const targets = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: STEPS.length - 1 };
    if (!(event.key in targets)) return;
    event.preventDefault?.();
    const target = STEPS[(targets[event.key] + STEPS.length) % STEPS.length][0];
    setStep(target);
    refs.current[target]?.focus?.();
  };
  return el('div', { role: 'tablist', 'aria-label': 'Steps', style: { display: 'grid', gridTemplateColumns: `repeat(${STEPS.length}, 1fr)`, borderBottom: '1px solid var(--ui-stroke-secondary)' }, children: STEPS.map(([id, label], index) => {
    const selected = step === id;
    return el('button', { type: 'button', role: 'tab', id: `cutroom-tab-${id}`, 'aria-selected': selected, 'aria-controls': `cutroom-panel-${id}`, tabIndex: selected ? 0 : -1,
      ref: node => { refs.current[id] = node; }, onClick: () => setStep(id), onKeyDown: event => go(event, index),
      style: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2, padding: '8px 4px', background: 'transparent', color: selected ? 'var(--ui-text-primary)' : 'var(--ui-text-secondary)', font: 'inherit', fontSize: 12, fontWeight: selected ? 600 : 400, border: 'none', borderBottom: `2px solid ${selected ? 'var(--ui-accent)' : 'transparent'}`, cursor: 'pointer' },
      children: [el('span', { 'aria-hidden': true, style: { fontSize: 11, width: 18, height: 18, lineHeight: '16px', borderRadius: 9, border: '1px solid currentColor', textAlign: 'center' }, children: String(index + 1) }), label] }, `tab:${id}`);
  }) });
}

function Activity({ jobs, cancel, retry }) {
  const active = newest(jobs.filter(job => ACTIVE.includes(job.status)));
  const job = active.at(-1);
  const finished = newest(jobs.filter(item => !ACTIVE.includes(item.status)));
  const last = finished.find(item => !item.completed_at || Date.now() / 1000 - item.completed_at < 600);
  const [verb] = job ? jobWords(job.action) : [''];
  return el('footer', { 'aria-label': 'Activity', 'aria-live': 'polite', style: { ...row, gap: 12, padding: '8px 0', borderTop: '1px solid var(--ui-stroke-secondary)', fontSize: 12 }, children: [
    job ? el('div', { style: row, children: [
      el('span', { children: `${verb}${job.cancel_requested ? ' · stopping' : ''}` }),
      jsx(Bar, { value: job.progress, label: `${verb} progress` }),
      el('span', { children: `${pct(job.progress)}%` }),
      active.length > 1 ? el('span', { style: muted, children: `+${active.length - 1} more waiting` }) : null,
      jsx(Button, { variant: 'ghost', disabled: Boolean(job.cancel_requested), 'aria-label': `Cancel ${verb.toLowerCase()}`, onClick: () => cancel(job), children: 'Cancel' }),
    ] }, 'active') : null,
    last ? el('div', { style: row, children: [
      el('span', { style: muted, children: `${jobWords(last.action)[1]} ${last.status === 'completed' ? 'done' : last.status === 'cancelled' ? 'stopped' : 'failed'}` }),
      last.status === 'failed' ? jsx(Notice, { error: last.error || 'Something went wrong' }) : null,
      last.status === 'failed' && jobActions.includes(last.action) && last.action !== 'final' ? jsx(Button, { variant: 'ghost', onClick: () => retry(last), children: 'Try again' }) : null,
    ] }, 'last') : null,
    !job && !last ? el('span', { style: muted, children: 'Nothing running' }, 'idle') : null,
  ] });
}

function SafeZoneOverlay({ zone }) {
  const shade = { position: 'absolute', background: 'var(--ui-stroke-secondary)', opacity: 0.6, pointerEvents: 'none' };
  const middle = 100 - (zone.top + zone.bottom) * 100;
  return [
    jsx('div', { 'data-cutroom-unsafe': 'top', style: { ...shade, left: 0, right: 0, top: 0, height: percent(zone.top) } }, 'unsafe:top'),
    jsx('div', { 'data-cutroom-unsafe': 'bottom', style: { ...shade, left: 0, right: 0, bottom: 0, height: percent(zone.bottom) } }, 'unsafe:bottom'),
    jsx('div', { 'data-cutroom-unsafe': 'left', style: { ...shade, left: 0, top: percent(zone.top), height: `${+middle.toFixed(2)}%`, width: percent(zone.left) } }, 'unsafe:left'),
    jsx('div', { 'data-cutroom-unsafe': 'right', style: { ...shade, right: 0, top: percent(zone.top), height: `${+middle.toFixed(2)}%`, width: percent(zone.right) } }, 'unsafe:right'),
  ];
}

// Explicit, authenticated, bounded media loads; downloads never load the file into memory.
async function downloadArtifact(ctx, project, kind) {
  if (typeof SDK.captureGatewayFileDownload !== 'function') throw new Error('This host does not support native downloads. Update Hermes Desktop; no unauthenticated fallback is used.');
  const save = SDK.captureGatewayFileDownload();
  const metadata = await ctx.rest(`/projects/${enc(project.id)}/artifact-info/${kind}`);
  if (typeof metadata.path !== 'string' || !metadata.path || typeof metadata.name !== 'string' || !metadata.name) throw new Error('File details are incomplete');
  await save(metadata.path, metadata.name);
}

function MediaPanel({ ctx, project, profile = null, platforms = [], videoRef, api, onPlayback = () => {} }) {
  const [overlay, setOverlay] = useState(false);
  const [ready, setReady] = useState(false);
  const [media, setMedia, mediaRef] = useLive(null);
  const [duration, setDuration] = useState(null);
  const [time, setTime] = useState(null);
  const [playing, setPlaying] = useState(false);
  // A loaded render shows the zone of the profile it was rendered with (recorded in its lineage), not the current setting.
  const rendered = media && media.kind !== 'source';
  const shown = rendered ? platformOf(platforms, { settings: { platform: project.artifact_lineage?.[media.kind]?.platform || 'custom' } }) : profile;
  const zone = shown?.safe_zone || null;
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const generation = useRef(0);
  const loading = useRef(null);
  const url = useRef(null);
  const lock = useRef(false);
  const release = () => {
    generation.current++; lock.current = false; loading.current = null;
    if (url.current) URL.revokeObjectURL(url.current);
    url.current = null; setMedia(null); setProgress(null); setReady(false); setTime(null); setPlaying(false);
    onPlayback({ kind: null, time: null });
  };
  useEffect(() => () => { generation.current++; if (url.current) URL.revokeObjectURL(url.current); url.current = null; }, [project.id]);
  // Renders belong to a revision; the source never changes, so editing does not stop it.
  useEffect(() => {
    const kind = mediaRef.current?.kind || loading.current;
    if (kind && kind !== 'source') release();
  }, [project.revision, project.artifacts?.preview, project.artifacts?.final]);
  const load = async kind => {
    if (lock.current) return;
    release(); lock.current = true; loading.current = kind; setError(null);
    const token = generation.current;
    try {
      const parts = [];
      let offset = 0, total = null, version = null, mime = null;
      do {
        const chunk = await ctx.rest(`/projects/${enc(project.id)}/media/${kind}?offset=${offset}&length=1048576${version ? `&version=${enc(version)}` : ''}`);
        if (token !== generation.current) return;
        if (!Number.isSafeInteger(chunk.total) || chunk.total < 1 || chunk.total > 268435456) throw new Error('Native playback is limited to 256 MiB; render a smaller preview or download the file.');
        if (chunk.offset !== offset || !Number.isSafeInteger(chunk.next_offset) || chunk.next_offset <= offset || chunk.next_offset > chunk.total || chunk.next_offset - offset > 1048576 || typeof chunk.data !== 'string' || chunk.data.length > 1398104 || typeof chunk.version !== 'string' || !chunk.version || typeof chunk.mime !== 'string' || !chunk.mime.startsWith('video/')) throw new Error('Invalid or unsupported media chunk');
        if (version && (version !== chunk.version || total !== chunk.total || mime !== chunk.mime)) throw new Error('Media changed while loading; reload the player');
        version = chunk.version; total = chunk.total; mime = chunk.mime;
        const binary = atob(chunk.data);
        if (binary.length !== chunk.next_offset - offset) throw new Error('Incomplete media chunk');
        parts.push(Uint8Array.from(binary, character => character.charCodeAt(0)));
        offset = chunk.next_offset; setProgress(offset / total);
      } while (offset < total);
      if (token !== generation.current) return;
      url.current = URL.createObjectURL(new Blob(parts, { type: mime }));
      setMedia({ url: url.current, kind });
      onPlayback({ kind, time: null });
    } catch (failure) { if (token === generation.current) setError(failure); }
    finally { if (token === generation.current) { lock.current = false; loading.current = null; setProgress(null); } }
  };
  if (api) api.current = { load, release };
  const portrait = (shown?.orientation || project.settings?.aspect) === 'portrait';
  const showZone = overlay && zone && ready && media && media.kind !== 'source';
  const player = media ? jsx('video', { ref: videoRef, src: media.url, preload: 'metadata', controls: true, 'aria-label': `${media.kind === 'source' ? 'Source' : media.kind === 'preview' ? 'Preview' : 'Final video'} player`,
    style: { display: 'block', maxWidth: '100%', maxHeight: '62vh', ...(showZone ? {} : { width: '100%' }) },
    onTimeUpdate: event => { const now = event.currentTarget.currentTime; setTime(now); onPlayback({ kind: media.kind, time: now }); },
    onPlay: () => setPlaying(true), onPause: () => setPlaying(false),
    onLoadedMetadata: event => { setReady(true); const length = event?.currentTarget?.duration; if (Number.isFinite(length)) setDuration(length); },
    onError: () => { setError(new Error('This host cannot play this file. Download it or make a compatible MP4 preview.')); release(); } }, 'player:video') : null;
  return el('div', { style: stack, children: [
    el('div', { 'aria-label': shown ? `${shown.label} frame` : 'Video frame', style: { display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 240, padding: 8, borderRadius: 10, border: '1px solid var(--ui-stroke-secondary)', background: 'var(--ui-bg-tertiary)' }, children:
      media ? (showZone
        // Drawn once the frame size is known; the wrapper shrinks to the video box, so percentages follow the rendered frame.
        ? el('div', { 'aria-label': 'Safe zone overlay', style: { position: 'relative', display: 'inline-block', maxWidth: '100%' }, children: [player, ...SafeZoneOverlay({ zone })] })
        : player)
        : el('div', { style: { ...stack, alignItems: 'center', textAlign: 'center', gap: 6, aspectRatio: portrait ? '9 / 16' : '16 / 9', maxHeight: '50vh', justifyContent: 'center', padding: 16 }, children: [
          el('strong', { style: { fontSize: 13 }, children: 'Nothing loaded' }),
          el('span', { style: muted, children: 'Load the source to edit by text, or a preview to check the result.' }),
        ] }) }, 'frame'),
    progress !== null ? el('div', { style: row, children: [el('span', { style: muted, children: 'Loading video…' }), jsx(Bar, { value: progress, label: 'Media loading progress' }), el('span', { style: muted, children: `${pct(progress)}%` })] }, 'progress-row') : null,
    el('div', { style: { ...row, justifyContent: 'space-between' }, children: [
      el('div', { style: row, children: [
        jsx(Button, { variant: 'secondary', disabled: !media, 'aria-label': playing ? 'Pause' : 'Play', onClick: () => { const video = videoRef?.current; if (video) { if (video.paused) video.play?.(); else video.pause?.(); } }, children: playing ? '❚❚' : '▶' }),
        el('span', { style: muted, children: `${clock(time ?? 0)} / ${clock(duration ?? (media?.kind === 'source' ? project.source_info?.duration : NaN))}` }),
      ] }),
      el('label', { style: { ...row, fontSize: 12 }, children: [jsx(Tick, { 'aria-label': 'Show safe zone', checked: overlay && Boolean(zone), disabled: !zone, onCheckedChange: checked => setOverlay(checked === true) }),
        zone ? `Show ${shown.label} safe zone on previews (shaded areas may be covered by the app)` : rendered ? 'Safe zone: this preview was made without a platform' : 'Safe zone: choose a platform in Style'] }),
    ] }, 'transport'),
    el('div', { style: row, children: [
      ...['source', 'preview', 'final'].map(kind => jsx(Button, { variant: 'ghost', disabled: progress !== null || (kind !== 'source' && !project.artifacts?.[kind]), onClick: () => load(kind), children: `Load ${kind}` }, `load:${kind}`)),
      jsx(Button, { variant: 'ghost', disabled: !media && progress === null, onClick: release, children: 'Unload media' }, 'unload'),
    ] }, 'loads'),
    jsx(Notice, { error }, 'error'),
  ] });
}

function EditStep({ kit }) {
  const { view, jobs } = kit;
  const words = view.transcript?.words || [];
  const transcribing = jobs.find(job => job.action === 'transcribe' && ACTIVE.includes(job.status));
  const intro = el('div', { style: { ...stack, gap: 4 }, children: [
    el('h2', { style: h2s, children: 'Edit by text' }),
    el('p', { style: muted, children: 'Click a word to jump there. Drag across words or Shift-click to select, then press Delete. Removed parts are skipped in the video. Double-click a word to fix its spelling.' }),
  ] });
  if (!words.length) {
    const silent = view.transcript?.status === 'no_audio';
    return el('div', { style: stack, children: [intro, el('div', { style: { ...panel, alignItems: 'flex-start' }, children: [
      el('p', { style: { margin: 0 }, children: silent ? 'This video has no sound, so there are no words to edit.' : transcribing ? `Transcribing… ${pct(transcribing.progress)}%` : 'This video has no transcript yet. Transcribe it to edit by text.' }),
      silent ? null : jsx(Button, { disabled: Boolean(transcribing), onClick: () => kit.runAction('transcribe'), children: 'Transcribe' }),
      el('p', { style: muted, children: 'Transcription runs on the computer that runs Cutroom, with the speech model from Settings → Plugins → Cutroom.' }),
    ] })] });
  }
  return el('div', { style: stack, children: [intro, jsx(Suggestions, { kit }, 'suggestions'), jsx(Transcript, { kit }, 'transcript')] });
}

function Suggestions({ kit }) {
  const { view, ctx, edit } = kit;
  const key = `dismissed:${view.id}`;
  const [dismissed, setDismissed] = useState(() => { const value = ctx.storage?.get?.(key, []); return Array.isArray(value) ? value : []; });
  const list = findSuggestions(view, kit.silences).filter(item => !dismissed.includes(item.key));
  const keep = item => { const next = [...dismissed, item.key].slice(-500); setDismissed(next); ctx.storage?.set?.(key, next); };
  const apply = items => edit(combineSuggestions(kit.view, items), items.length > 1 ? 'Apply suggestions' : 'Apply suggestion');
  if (!list.length) return el('p', { style: muted, children: 'No suggested cuts right now.' });
  return el('section', { 'aria-label': 'Suggestions', style: { ...panel, gap: 6, padding: 12 }, children: [
    el('div', { style: { ...row, justifyContent: 'space-between' }, children: [el('span', { children: [el('strong', { children: plural(list.length, 'suggestion') }, 'n'), el('span', { style: muted, children: ' · pauses and repeats' }, 'k')] }), jsx(Button, { variant: 'secondary', onClick: () => apply(list), children: 'Apply all' })] }, 'head'),
    ...list.slice(0, 50).map(item => el('div', { 'data-suggestion': item.key, style: { ...row, justifyContent: 'space-between', borderTop: '1px solid var(--ui-stroke-secondary)', paddingTop: 6 }, children: [
      el('span', { style: { flex: '1 1 180px', fontSize: 13 }, children: item.text }),
      el('span', { style: row, children: [jsx(Button, { variant: 'secondary', onClick: () => apply([item]), children: 'Apply' }, 'apply'), jsx(Button, { variant: 'ghost', onClick: () => keep(item), children: 'Keep' }, 'keep')] }),
    ] }, `suggestion:${item.key}`)),
  ] });
}

function Transcript({ kit }) {
  const { view, edit, seek, playback } = kit;
  const words = [...(view.transcript?.words || [])].sort((a, b) => a.start - b.start);
  const excluded = new Set(view.excluded_word_ids || []);
  const [anchor, setAnchor, anchorRef] = useLive(null);
  const [focus, setFocus, focusRef] = useLive(null);
  const [fixing, setFixing] = useState(null);
  const drag = useRef(null);
  const low = anchor == null || focus == null ? -1 : Math.min(anchor, focus);
  const high = anchor == null || focus == null ? -2 : Math.max(anchor, focus);
  const selection = low >= 0 ? words.slice(low, high + 1) : [];
  const allRemoved = selection.length > 0 && selection.every(word => excluded.has(word.id));
  const toggle = () => {
    const a = anchorRef.current, b = focusRef.current;
    if (a == null || b == null) return;
    const chosen = words.slice(Math.min(a, b), Math.max(a, b) + 1);
    const latest = kit.view.excluded_word_ids || [];
    const removed = new Set(latest);
    const restore = chosen.every(word => removed.has(word.id));
    const ids = restore ? latest.filter(id => !chosen.some(word => word.id === id)) : [...latest, ...chosen.filter(word => !removed.has(word.id)).map(word => word.id)];
    edit({ excluded_word_ids: ids }, restore ? 'Restore words' : 'Remove words');
  };
  const pick = (index, event) => {
    if (drag.current?.moved) { drag.current = null; return; }
    drag.current = null;
    if (event?.shiftKey && anchorRef.current != null) { setFocus(index); return; }
    setAnchor(index); setFocus(index);
    seek(words[index]?.start);
  };
  const keys = event => {
    const last = words.length - 1;
    const at = focusRef.current ?? -1;
    const moves = { ArrowRight: Math.min(last, at + 1), ArrowLeft: Math.max(0, at - 1), Home: 0, End: last };
    if (event.key in moves) {
      event.preventDefault?.();
      const target = moves[event.key];
      if (!(event.shiftKey && anchorRef.current != null)) setAnchor(target);
      setFocus(target);
    } else if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault?.(); toggle(); }
    else if (event.key === 'Enter' && at >= 0) { event.preventDefault?.(); seek(words[at].start); }
    else if (event.key === 'Escape') { setAnchor(null); setFocus(null); }
  };
  const fixWord = fixing == null ? null : words.find(word => word.id === fixing);
  const playhead = playback.kind === 'source' ? playback.time : null;
  return el('div', { style: { ...stack, gap: 8 }, children: [
    selection.length ? el('div', { style: { ...row, justifyContent: 'space-between' }, children: [
      el('span', { style: muted, children: `${plural(selection.length, 'word')} selected` }),
      el('span', { style: row, children: [
        jsx(Button, { variant: 'secondary', onClick: toggle, children: allRemoved ? 'Restore' : 'Remove' }, 'toggle'),
        jsx(Button, { variant: 'ghost', onClick: () => setFixing(selection[0].id), children: 'Fix a word' }, 'fix'),
        jsx(Button, { variant: 'ghost', onClick: () => { setAnchor(null); setFocus(null); }, children: 'Clear selection' }, 'clear'),
      ] }),
    ] }, 'toolbar') : null,
    fixWord ? el('div', { style: { ...row, alignItems: 'flex-end' }, children: [
      jsx(Field, { label: `Fix “${fixWord.text}” (${seconds(fixWord.start)})`, name: `fix.${fixWord.id}`, value: fixWord.text, onCommit: value => {
        if (!value.trim()) return 'A word cannot be empty';
        kit.correctWord(fixWord.id, value);
        return undefined;
      } }, `fix:${fixWord.id}`),
      jsx(Button, { variant: 'ghost', onClick: () => setFixing(null), children: 'Done' }, 'done'),
    ] }, 'fixer') : null,
    playback.kind === 'source' ? null : el('p', { style: muted, children: 'Load the source in the player to jump to a word when you click it.' }, 'hint'),
    el('div', { role: 'listbox', 'aria-label': 'Transcript', 'aria-multiselectable': true, tabIndex: 0, 'aria-activedescendant': focus != null ? `cutroom-word-${focus}` : undefined,
      onKeyDown: keys, onMouseLeave: () => { drag.current = null; },
      style: { lineHeight: 1.9, fontSize: 14, maxHeight: '48vh', overflow: 'auto', padding: 8, borderRadius: 8, border: '1px solid var(--ui-stroke-secondary)', userSelect: 'none' },
      children: words.map((word, index) => {
        const removed = excluded.has(word.id);
        const selected = index >= low && index <= high;
        const current = playhead != null && playhead >= word.start && playhead < word.end;
        return el('span', { id: `cutroom-word-${index}`, role: 'option', 'aria-selected': selected, 'data-word-id': String(word.id), 'aria-label': removed ? `${word.text}, removed` : undefined,
          onMouseDown: event => { if (!event?.shiftKey) drag.current = { start: index, moved: false }; },
          onMouseEnter: () => { if (drag.current && index !== drag.current.start) { drag.current.moved = true; setAnchor(drag.current.start); setFocus(index); } },
          onClick: event => pick(index, event), onDoubleClick: () => setFixing(word.id),
          style: { padding: '1px 2px', borderRadius: 3, cursor: 'pointer', textDecoration: removed ? 'line-through' : current ? 'underline' : 'none', textDecorationColor: current ? 'var(--ui-accent)' : undefined,
            color: removed ? 'var(--ui-text-tertiary)' : 'inherit', outline: selected ? '1px solid var(--ui-accent)' : 'none', background: selected ? 'color-mix(in srgb, var(--ui-accent) 22%, transparent)' : 'transparent' },
          children: word.text }, `word:${word.id}`);
      }).flatMap((node, index) => (index ? [' ', node] : [node])) }, 'words'),
  ] });
}

function StyleStep({ kit }) {
  const { view, edit, platforms } = kit;
  const settings = view.settings || {};
  const selected = platforms.find(item => item.name === (settings.platform || 'custom')) || null;
  const fixed = Boolean(selected?.frame);
  const resolution = settings.final_resolution || selected?.frame?.default_final || '1080';
  const choosePlatform = name => {
    const item = platforms.find(entry => entry.name === name);
    if (!item) return;
    const next = { platform: name };
    // Long-form YouTube delivers sidecar SRT/VTT; burn-in stays available as an explicit choice.
    if (name === 'youtube' && settings.platform !== 'youtube') next.captions = false;
    if (item.orientation) { next.aspect = item.orientation; next.brand = { ...(settings.brand || {}), aspect: item.orientation }; }
    edit({ settings: next }, 'Platform');
  };
  const summary = () => {
    if (!fixed) return 'Custom: the frame follows the shape below. No platform limits are checked.';
    const final = selected.frame.final[resolution] || [];
    const limit = selected.max_duration_s?.value;
    return `${selected.label}: video size ${final.join(' × ')} · ${limit ? `up to ${limit} s` : 'no length limit'} · text kept clear of the app\u2019s buttons.`;
  };
  const captionValue = settings.captions === true ? settings.caption_style || 'classic' : 'off';
  const colour = HEX.test(settings.caption_highlight_color || '') ? settings.caption_highlight_color : null;
  const sample = value => {
    const accent = colour || 'var(--ui-accent)';
    const box = { display: 'inline-block', padding: '4px 6px', borderRadius: 4, background: 'var(--ui-bg-tertiary)', fontWeight: 700, fontSize: 12 };
    if (value === 'off') return el('span', { 'aria-hidden': true, style: { ...box, fontWeight: 400 }, children: 'No text' });
    if (value === 'one_word') return el('span', { 'aria-hidden': true, style: { ...box, fontSize: 15 }, children: el('span', { style: { color: accent }, children: 'Guyana' }) });
    if (value === 'classic') return el('span', { 'aria-hidden': true, style: box, children: 'I came from Guyana' });
    return el('span', { 'aria-hidden': true, style: box, children: ['I came from ', el('span', { style: { color: accent, fontSize: value === 'pop' ? 14 : 12 }, children: 'Guyana' }, 'word')] });
  };
  const faceReady = Boolean(view.analysis?.face_samples);
  const vision = kit.jobs.find(job => job.action === 'vision' && ACTIVE.includes(job.status));
  const colourField = value => {
    if (value === '') { edit({ settings: { caption_highlight_color: null } }, 'Caption colour', 'caption-colour'); return undefined; }
    if (!HEX.test(value)) return 'Caption colour must be a six-digit hex value, like the code a colour picker shows';
    edit({ settings: { caption_highlight_color: value } }, 'Caption colour', 'caption-colour');
    return undefined;
  };
  const positionField = value => {
    if (value === '') { edit({ settings: { caption_word_y: null } }, 'Word position', 'word-y'); return undefined; }
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0 || number > 1) return 'One-word position must be between 0 and 1';
    edit({ settings: { caption_word_y: number } }, 'Word position', 'word-y');
    return undefined;
  };
  return el('div', { style: { ...stack, gap: 16 }, children: [
    el('h2', { style: h2s, children: 'Style' }),
    el('section', { 'aria-labelledby': 'cutroom-platform', style: stack, children: [
      el('h3', { id: 'cutroom-platform', style: h3s, children: 'Where will you post it?' }),
      jsx(RadioCards, { label: 'Platform', value: settings.platform || 'custom', onChange: choosePlatform, options: platforms.map(item => ({ key: `platform:${item.name}`, value: item.name, title: item.label,
        detail: item.frame ? `${ratioOf(item.orientation)}${item.max_duration_s?.value ? ` · up to ${minutes(item.max_duration_s.value)}` : ''}` : 'Your own frame' })) }),
      el('p', { role: 'status', style: muted, children: summary() }),
      jsx(RadioCards, { label: 'Final size', value: fixed ? resolution : null, disabled: !fixed, min: 120, onChange: value => edit({ settings: { final_resolution: value } }, 'Final size'),
        options: [['1080', 'HD', '1080 lines'], ['2160', '4K', '2160 lines, larger files']].map(([value, title, detail]) => ({ key: `resolution:${value}`, value, title, detail })) }),
      fixed ? null : jsx(RadioCards, { label: 'Frame shape', value: settings.aspect || 'source', min: 110, onChange: value => edit({ settings: { aspect: value, brand: { ...(settings.brand || {}), aspect: value } } }, 'Frame shape'),
        options: [['source', 'Original'], ['portrait', 'Tall 9:16'], ['landscape', 'Wide 16:9'], ['square', 'Square']].map(([value, title]) => ({ key: `aspect:${value}`, value, title })) }),
    ] }),
    el('section', { 'aria-labelledby': 'cutroom-captions', style: stack, children: [
      el('h3', { id: 'cutroom-captions', style: h3s, children: 'Captions' }),
      jsx(RadioCards, { label: 'Caption style', value: captionValue, min: 120, onChange: value => edit({ settings: value === 'off' ? { captions: false } : { caption_style: value, captions: true } }, 'Caption style'),
        options: CAPTION_STYLES.map(([value, title, detail]) => ({ key: `caption-style:${value}`, value, title, detail, preview: sample(value) })) }),
      jsx(Disclosure, { title: 'More caption options', children: [
        el('div', { style: { ...row, alignItems: 'flex-end' }, children: [
          jsx(Field, { label: 'Highlight colour (hex; blank uses the theme accent)', name: 'caption_highlight_color', value: settings.caption_highlight_color, onCommit: colourField }),
          el('span', { 'aria-hidden': true, style: { width: 24, height: 24, borderRadius: 4, border: '1px solid var(--ui-stroke-secondary)', background: colour || 'var(--ui-accent)' } }),
        ] }, 'colour'),
        jsx(Field, { label: 'One-word position (0 top – 1 bottom; blank = 0.8, below the face)', name: 'caption_word_y', type: 'number', value: settings.caption_word_y, onCommit: positionField }, 'word-y'),
      ] }),
    ] }),
    el('section', { 'aria-labelledby': 'cutroom-framing', style: stack, children: [
      el('h3', { id: 'cutroom-framing', style: h3s, children: 'Framing' }),
      jsx(RadioCards, { label: 'Framing', value: settings.framing || 'fit', min: 120, onChange: value => edit({ settings: { framing: value } }, 'Framing'),
        options: FRAMINGS.map(([value, title, detail]) => ({ key: `framing-mode:${value}`, value, title, detail })) }),
      settings.framing === 'face_track' && !faceReady ? el('div', { style: { ...panel, padding: 12, gap: 8 }, children: [
        el('p', { style: { margin: 0, fontSize: 13 }, children: 'Face tracking needs a face analysis first. It runs on this project once.' }),
        settings.face_model ? jsx(Button, { variant: 'secondary', disabled: Boolean(vision), onClick: () => kit.run('vision', {}), children: vision ? `Analysing faces… ${pct(vision.progress)}%` : 'Analyse faces' })
          : el('p', { style: muted, children: 'Add a face model file in Settings → Plugins → Cutroom, or under More tools → Project model paths.' }),
      ] }) : null,
      el('p', { style: muted, children: 'Cropping enlarges the picture, so a small source can look softer. The Review step tells you when that happens.' }),
    ] }),
    jsx(PacingGroup, { kit }),
    jsx(Disclosure, { title: 'Create versions for other platforms', children: jsx(PlatformVersions, { kit }) }),
  ] });
}

function PacingGroup({ kit }) {
  const { view, edit } = kit;
  const pacing = view.settings?.pacing || {};
  // One undo step for a run of pacing changes; the whole object is sent each time.
  const set = (changes, label) => {
    const next = {};
    for (const key of PACING_KEYS) if (pacing[key] !== undefined) next[key] = pacing[key];
    for (const [key, value] of Object.entries(changes)) { if (value === undefined) delete next[key]; else next[key] = value; }
    edit({ settings: { pacing: next } }, label, 'pacing');
  };
  const shorten = Number.isFinite(pacing.max_pause);
  const pause = shorten ? pacing.max_pause : 0.6;
  const number = key => value => {
    const [low, high, label] = PACING_BOUNDS[key];
    if (value === '') { set({ [key]: undefined }, label); return undefined; }
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < low || parsed > high) return `${label} must be between ${low} and ${high}`;
    set({ [key]: parsed }, label);
    return undefined;
  };
  return el('section', { 'aria-labelledby': 'cutroom-pacing', style: stack, children: [
    el('h3', { id: 'cutroom-pacing', style: h3s, children: 'Pacing' }),
    jsx(Choice, { label: 'Punch-ins', value: pacing.punch_in === 'alternate' ? 'alternate' : 'off', options: [['off', 'Off'], ['alternate', 'On']], onChange: value => set({ punch_in: value }, 'Punch-ins') }),
    el('p', { style: muted, children: 'On: every other cut zooms in a little, centred on the face, so jump cuts look intended. Cutroom lowers a zoom rather than enlarge the picture too much.' }),
    el('label', { style: { ...row, fontSize: 13 }, children: [jsx(Tick, { 'aria-label': 'Shorten long pauses', checked: shorten, onCheckedChange: checked => set({ max_pause: checked === true ? pause : null }, 'Shorten long pauses') }), 'Shorten long pauses'] }),
    el('label', { style: { ...row, fontSize: 12 }, children: [
      el('span', { children: 'Longest pause' }),
      jsx('input', { type: 'range', name: 'pacing.max_pause', 'aria-label': 'Longest pause', 'aria-valuetext': `${pause} seconds`, min: 0.2, max: 2, step: 0.1, value: pause, disabled: !shorten,
        onChange: event => set({ max_pause: Number(event.target.value) }, 'Longest pause'), style: { flex: '1 1 160px', accentColor: 'var(--ui-accent)' } }),
      el('strong', { children: `${pause} s` }),
    ] }),
    el('p', { style: muted, children: 'Silences between words longer than this are cut down to it. Captions and sound stay in step.' }),
    jsx(Choice, { label: 'Transition', value: pacing.transition || 'cut', options: TRANSITIONS, onChange: value => set({ transition: value }, 'Transition') }),
    jsx(Disclosure, { title: 'More pacing options', children: [
      el('label', { style: { ...row, fontSize: 13 }, children: [jsx(Tick, { 'aria-label': 'Slow push-in on long shots', checked: pacing.push_in === true, onCheckedChange: checked => set({ push_in: checked === true }, 'Push-in') }), 'Slow push-in on long shots (4 s or more)'] }, 'push'),
      el('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }, children: [
        jsx(Field, { label: 'Punch-in zoom (1.05–1.3; blank = 1.12)', name: 'pacing.punch_in_zoom', type: 'number', value: pacing.punch_in_zoom, onCommit: number('punch_in_zoom') }, 'punch'),
        jsx(Field, { label: 'Push-in zoom (1.02–1.15; blank = 1.06)', name: 'pacing.push_in_zoom', type: 'number', value: pacing.push_in_zoom, onCommit: number('push_in_zoom') }, 'push-zoom'),
        jsx(Field, { label: 'Most enlargement of the source (1–4×; blank = 2)', name: 'pacing.max_upscale', type: 'number', value: pacing.max_upscale, onCommit: number('max_upscale') }, 'limit'),
        jsx(Field, { label: 'Transition length, s (0.04–0.5; blank = 0.2)', name: 'pacing.transition_duration', type: 'number', value: pacing.transition_duration, onCommit: number('transition_duration') }, 'length'),
      ] }, 'numbers'),
    ] }),
  ] });
}

function PlatformVersions({ kit }) {
  const { ctx, scope, project, platforms, open } = kit;
  const client = useQueryClient();
  const lock = useRef(false);
  const [error, setError] = useState(null);
  const derive = useMutation({ mutationFn: platform => ctx.rest(`/projects/${enc(project.id)}/derive`, { method: 'POST', body: { platform } }) });
  const create = async platform => {
    if (lock.current) return;
    lock.current = true; setError(null);
    try {
      const result = await derive.mutateAsync(platform);
      client.invalidateQueries({ queryKey: scope });
      open(result.id);
    } catch (failure) { setError(failure); }
    finally { lock.current = false; }
  };
  return el('div', { style: { ...stack, gap: 8 }, children: [
    el('p', { style: muted, children: 'A version is a separate project from the same video. It copies the words, cuts and look, then gets its own platform, review and approval. Nothing is approved by creating it.' }),
    project.derived_from ? el('p', { style: muted, children: `Derived from ${project.derived_from.project_id} at revision ${project.derived_from.revision}.` }) : null,
    el('div', { style: row, children: platforms.filter(item => item.name !== 'custom').map(item => jsx(Button, { variant: 'secondary', disabled: derive.isPending, onClick: () => create(item.name), children: `Create version for ${item.short_label || item.label}` }, `derive:${item.name}`)) }),
    jsx(Notice, { error }),
  ] });
}

function SoundStep({ kit }) {
  const { view, edit, profile, ctx } = kit;
  const settings = view.settings || {};
  const music = settings.music || null;
  const level = Number.isFinite(music?.volume_db) ? music.volume_db : -18;
  const word = level <= -26 ? 'Quiet' : level <= -12 ? 'Background' : 'Loud';
  const loudness = profile?.frame ? `${profile.label} (−14 LUFS)` : 'a comfortable level (−16 LUFS)';
  const number = (group, key) => value => kit.sound(group, key, value === '' ? '' : Number(value));
  return el('div', { style: { ...stack, gap: 16 }, children: [
    el('h2', { style: h2s, children: 'Sound' }),
    el('section', { 'aria-labelledby': 'cutroom-music', style: stack, children: [
      el('h3', { id: 'cutroom-music', style: h3s, children: 'Music' }),
      el('div', { style: { ...row, alignItems: 'flex-end' }, children: [
        jsx(Field, { label: 'Music file (WAV, MP3, M4A, FLAC, OGG)', name: 'music.path', value: music?.path, placeholder: 'C:/Music/bed.mp3', onCommit: value => kit.sound('music', 'path', value) }, 'path'),
        jsx(Browse, { ctx, pattern: AUDIO_FILE, noun: 'Audio files', onPick: value => kit.sound('music', 'path', value) }, 'browse'),
      ] }),
      el('p', { style: muted, children: 'Use only music you own or may use. Leave the file blank for no music.' }),
      el('label', { style: { ...row, fontSize: 12 }, children: [
        el('span', { children: 'Music level' }),
        jsx('input', { type: 'range', name: 'music.level', 'aria-label': 'Music level', 'aria-valuetext': `${word}, ${level} dB`, min: -40, max: -6, step: 1, value: level, disabled: !music,
          onChange: event => kit.sound('music', 'volume_db', Number(event.target.value)), style: { flex: '1 1 160px', accentColor: 'var(--ui-accent)' } }),
        el('strong', { children: word }),
        el('span', { style: muted, children: `(${level} dB)` }),
      ] }),
      el('label', { style: { ...row, fontSize: 13 }, children: [jsx(Tick, { 'aria-label': 'Duck music during speech', disabled: !music, checked: music?.duck !== false, onCheckedChange: checked => kit.sound('music', 'duck', checked === true) }), 'Lower the music while someone speaks'] }),
    ] }),
    el('section', { 'aria-labelledby': 'cutroom-voice', style: stack, children: [
      el('h3', { id: 'cutroom-voice', style: h3s, children: 'Voice clean-up' }),
      jsx(Choice, { label: 'Voice clean-up', value: settings.voice_cleanup || 'off', options: [['off', 'Off'], ['light', 'Light'], ['strong', 'Strong']], onChange: value => edit({ settings: { voice_cleanup: value } }, 'Voice clean-up') }),
      el('p', { style: muted, children: `Light removes hum and hiss. Strong also reduces room echo. Cutroom sets the final loudness for ${loudness}.` }),
    ] }),
    jsx(Disclosure, { title: 'More sound options', children: [
      el('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }, children: [
        jsx(Field, { label: 'Lower music by dB during speech (12–36; blank = 12)', name: 'music.duck_db', type: 'number', value: music?.duck_db, onCommit: number('music', 'duck_db') }, 'duck'),
        jsx(Field, { label: 'Music fade in, s (0–30; blank = 0.5)', name: 'music.fade_in', type: 'number', value: music?.fade_in, onCommit: number('music', 'fade_in') }, 'in'),
        jsx(Field, { label: 'Music fade out, s (0–30; blank = 0.5)', name: 'music.fade_out', type: 'number', value: music?.fade_out, onCommit: number('music', 'fade_out') }, 'out'),
        jsx(Field, { label: 'Start the music at, s (blank = 0)', name: 'music.start_offset', type: 'number', value: music?.start_offset, onCommit: number('music', 'start_offset') }, 'offset'),
        jsx(Field, { label: 'Where the music came from', name: 'music.source_note', value: music?.source_note, onCommit: value => kit.sound('music', 'source_note', value) }, 'note'),
      ] }, 'music-more'),
      el('label', { style: { ...row, fontSize: 13 }, children: [jsx(Tick, { 'aria-label': 'Loop music', disabled: !music, checked: music?.loop !== false, onCheckedChange: checked => kit.sound('music', 'loop', checked === true) }), 'Loop the music to the end'] }, 'loop'),
      el('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }, children: [
        jsx(Field, { label: 'Sound on each cut (up to 5 s)', name: 'cut_sfx.path', value: settings.cut_sfx?.path, onCommit: value => kit.sound('cut_sfx', 'path', value) }, 'cut'),
        jsx(Field, { label: 'Cut sound level, dB (−60 to 0; blank = −12)', name: 'cut_sfx.volume_db', type: 'number', value: settings.cut_sfx?.volume_db, onCommit: number('cut_sfx', 'volume_db') }, 'cut-level'),
      ] }, 'cut'),
      el('label', { style: { ...row, fontSize: 13 }, children: [jsx(Tick, { 'aria-label': 'Even out the speech volume', checked: settings.normalize_audio === true, onCheckedChange: checked => edit({ settings: { normalize_audio: checked === true } }, 'Speech volume') }), 'Even out the speech volume'] }, 'normalize'),
      el('p', { style: muted, children: 'Each sound file is part of the approved version, so replacing it needs a new approval.' }, 'note'),
    ] }),
  ] });
}

function CheckRows({ label, items }) {
  return el('ul', { 'aria-label': label, style: { listStyle: 'none', margin: 0, padding: 0, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 10 }, children: items.map((check, index) => {
    const [title, note] = CHECK_TEXT[check.name] || [String(check.name || 'Check')];
    const [mark, word] = STATUS_MARK[check.status] || ['?', String(check.status || 'Unknown')];
    const explain = check.status === 'warning' ? note || 'Worth a look before you approve.' : check.status === 'fail' ? note || 'This needs fixing before export.' : '';
    return el('li', { style: { ...row, alignItems: 'flex-start', flexWrap: 'nowrap', padding: '8px 12px', borderTop: index ? '1px solid var(--ui-stroke-secondary)' : 'none' }, children: [
      el('span', { 'aria-hidden': true, style: { width: 16, fontWeight: 700, color: check.status === 'pass' ? 'var(--ui-text-secondary)' : 'var(--ui-text-primary)' }, children: mark }),
      el('span', { style: { ...stack, gap: 2 }, children: [el('span', { style: { fontSize: 13 }, children: `${title} — ${word}` }), explain ? el('span', { style: muted, children: explain }) : null] }),
    ] }, `check:${check.name}:${index}`);
  }) });
}

function CheckList({ checks }) {
  const list = (Array.isArray(checks) ? checks : []).filter(check => check && typeof check === 'object');
  const order = { fail: 0, warning: 1, pass: 2, skip: 3 };
  const sorted = [...list].sort((a, b) => (order[a.status] ?? 2) - (order[b.status] ?? 2));
  const attention = sorted.filter(check => check.status === 'fail' || check.status === 'warning');
  const rest = sorted.filter(check => check.status !== 'fail' && check.status !== 'warning');
  const passed = rest.filter(check => check.status === 'pass').length;
  const summary = `${plural(passed, 'check')} passed${rest.length > passed ? `, ${rest.length - passed} not checked` : ''}`;
  return el('div', { style: stack, children: [
    attention.length ? jsx(CheckRows, { label: 'Checks needing a look', items: attention }, 'attention') : null,
    rest.length ? el('details', { children: [
      el('summary', { style: { cursor: 'pointer', fontSize: 13 }, children: summary }, 'summary'),
      el('div', { style: { marginTop: 8 }, children: jsx(CheckRows, { label: 'Checks', items: rest }) }, 'rows'),
    ] }, 'rest') : null,
  ] });
}

function ReviewStep({ kit }) {
  const { project, jobs, review, confirmed, setConfirmed, approved, previewCurrent, qa } = kit;
  const previewJob = jobs.find(job => job.action === 'preview' && ACTIVE.includes(job.status));
  const qaJob = jobs.find(job => job.action === 'qa' && ACTIVE.includes(job.status));
  const intro = el('div', { style: { ...stack, gap: 4 }, children: [el('h2', { style: h2s, children: 'Review' }), el('p', { style: muted, children: 'Cutroom makes a preview and checks it. Watch it, then approve the version you want to export.' })] });
  const edited = kit.editedAfter ? el('p', { role: 'status', style: alertStyle, children: 'You changed the video after approving it. Review it again.' }) : null;
  if (!previewCurrent) return el('div', { style: stack, children: [intro, edited, el('div', { style: { ...panel, alignItems: 'flex-start' }, children: [
    el('p', { style: { margin: 0 }, children: previewJob ? `Making preview… ${pct(previewJob.progress)}%` : project.artifacts?.preview ? 'You changed the video since the last preview. Make a new preview to review it.' : 'There is no preview of this version yet.' }),
    jsx(Button, { disabled: Boolean(previewJob), onClick: () => kit.run('preview', {}, ['qa']), children: 'Make preview' }),
    el('p', { style: muted, children: 'The preview is checked automatically when it is ready.' }),
  ] })] });
  const headline = qa ? qaHeadline(qa.checks) : null;
  const current = review && review.project?.revision === project.revision;
  return el('div', { style: stack, children: [
    intro, edited,
    el('div', { role: 'status', style: { ...stack, gap: 2 }, children: [
      el('strong', { style: { fontSize: 15 }, children: headline ? headline.text : qaJob ? `Checking the preview… ${pct(qaJob.progress)}%` : 'Not checked yet' }),
      el('span', { style: muted, children: headline ? headline.detail : qaJob ? 'You can watch the preview meanwhile.' : 'Run the checks to see whether anything needs a look.' }),
    ] }),
    qa ? jsx(CheckList, { checks: qa.checks }) : qaJob ? null : jsx(Button, { variant: 'secondary', onClick: () => kit.run('qa', {}), children: 'Check preview' }),
    el('div', { style: row, children: [jsx(Button, { variant: 'secondary', onClick: kit.watch, children: 'Watch preview' }), el('span', { style: muted, children: 'Watch it to the end before approving.' })] }),
    el('section', { 'aria-labelledby': 'cutroom-approve', style: { ...panel, gap: 10 }, children: [
      el('h3', { id: 'cutroom-approve', style: h3s, children: 'Approve' }),
      approved ? el('p', { role: 'status', style: { margin: 0 }, children: '✓ Approved. You can export this version.' })
        : current ? el('div', { style: { ...stack, gap: 10 }, children: [
          el('label', { 'data-cutroom-confirm': true, style: { ...row, flexWrap: 'nowrap', fontSize: 13 }, children: [jsx(Tick, { 'aria-label': 'I watched this preview and want to export exactly this version', checked: confirmed, onCheckedChange: value => setConfirmed(value === true) }), 'I watched this preview and want to export exactly this version'] }),
          jsx(Button, { disabled: !confirmed || kit.reviewPending, onClick: () => kit.reviewNow(true), children: 'Approve this version' }),
        ] }) : jsx(Button, { variant: 'secondary', disabled: kit.reviewPending, onClick: () => kit.reviewNow(false), children: 'Get ready to approve' }),
      el('p', { style: muted, children: 'Approval is only possible here, not from chat. Any later change needs a new approval.' }),
      approved ? jsx(Button, { variant: 'ghost', onClick: () => kit.setStep('export'), children: 'Go to Export' }) : null,
    ] }),
    jsx(Disclosure, { title: 'Details', children: [
      el('p', { style: muted, children: `Version ${project.revision}` }, 'version'),
      review?.notice ? el('p', { style: muted, children: review.notice }, 'notice') : null,
      review ? el('p', { style: muted, children: ['Review digest: ', el('code', { style: { overflowWrap: 'anywhere' }, children: review.digest }, 'digest')] }, 'digest') : null,
      qa ? el('ul', { style: { ...muted, margin: 0, paddingLeft: 16 }, children: qa.checks.map((check, index) => el('li', { children: `${check.name}: ${check.status}` }, `raw:${index}`)) }, 'raw') : null,
      jsx(Button, { variant: 'ghost', disabled: kit.reviewPending, onClick: () => kit.reviewNow(false), children: 'Check again' }, 'again'),
    ] }),
  ] });
}

function ExportStep({ kit }) {
  const { ctx, project, jobs, approved } = kit;
  const [error, setError] = useState(null);
  const finalJob = jobs.find(job => ['final', 'cover'].includes(job.action) && ACTIVE.includes(job.status));
  const download = async kind => { setError(null); try { await downloadArtifact(ctx, project, kind); } catch (failure) { setError(failure); } };
  const files = [['final', 'Download video'], ['captions_srt', 'Download SRT captions'], ['captions_vtt', 'Download VTT captions'], ['cover', 'Download cover'], ['quality', 'Download report']];
  return el('div', { style: stack, children: [
    el('h2', { style: h2s, children: 'Export' }),
    approved ? el('p', { style: muted, children: 'This makes the final video from exactly the version you approved.' })
      : el('div', { style: { ...panel, padding: 12, gap: 8, alignItems: 'flex-start' }, children: [
        el('p', { style: { margin: 0, fontSize: 13 }, children: 'Approve this version in Review before exporting. Export makes exactly the version you approved.' }),
        jsx(Button, { variant: 'secondary', onClick: () => kit.setStep('review'), children: 'Go to Review' }),
      ] }),
    jsx(Button, { disabled: !approved || Boolean(finalJob), onClick: kit.exportFinal, children: finalJob ? `${jobWords(finalJob.action)[0]}… ${pct(finalJob.progress)}%` : 'Export final video' }),
    el('section', { 'aria-labelledby': 'cutroom-downloads', style: stack, children: [
      el('h3', { id: 'cutroom-downloads', style: h3s, children: 'Files' }),
      el('div', { style: row, children: files.map(([kind, label]) => jsx(Button, { variant: 'secondary', disabled: !project.artifacts?.[kind], onClick: () => download(kind), children: label }, `download:${kind}`)) }),
      jsx(Disclosure, { title: 'More files', children: jsx(Button, { variant: 'ghost', disabled: !project.artifacts?.preview, onClick: () => download('preview'), children: 'Download preview' }) }),
      el('p', { style: muted, children: 'Nothing is uploaded or posted. Files are saved where you choose.' }),
    ] }),
    jsx(Notice, { error }),
  ] });
}

function storyStatus(project) {
  const story = project.story;
  if (!story?.hooks?.length) return 'No hooks yet.';
  if (project.selected_hook == null) return 'Choose a hook, then run Storyboard again to build its scenes.';
  if (story.selected_hook !== project.selected_hook || !story.storyboard?.length) return `Run Storyboard to build scenes for hook ${project.selected_hook + 1}.`;
  return `Opening hook: ${story.opening_hook?.text || story.hooks[project.selected_hook]?.text || ''}. Used as the on-screen title when no title is set.`;
}

function MoreTools({ kit }) {
  const { view, edit, jobOptions, setJobOptions } = kit;
  const settings = view.settings || {};
  const option = key => value => { setJobOptions(old => ({ ...old, [key]: value })); return undefined; };
  const text = (key, label) => jsx(Field, { label, name: key, value: settings[key], onCommit: value => { edit({ settings: { [key]: value.trim() } }, label, `setting:${key}`); return undefined; } }, key);
  const integer = (key, label) => jsx(Field, { label, name: key, type: 'number', value: settings[key], onCommit: value => {
    if (value === '') return undefined;
    const number = Number(value);
    if (!Number.isInteger(number) || number < 1) return `${label} must be a positive whole number`;
    edit({ settings: { [key]: number } }, label, `setting:${key}`);
    return undefined;
  } }, key);
  return el('details', { style: { ...panel, gap: 12 }, children: [
    el('summary', { style: summaryStyle, children: 'More tools' }),
    el('p', { style: muted, children: 'Less common tools. Changes save automatically and can be undone.' }),
    jsx(Disclosure, { title: 'Fix words', children: jsx(FixWords, { kit }) }, 'words'),
    jsx(Disclosure, { title: 'Cut by time', children: jsx(CutByTime, { kit }) }, 'ranges'),
    jsx(Disclosure, { title: 'Transcription', children: [
      jsx(Field, { label: 'Language code (blank: detect)', name: 'job.language', value: jobOptions.language, placeholder: 'en', onCommit: option('language') }, 'language'),
      jsx(Button, { variant: 'secondary', onClick: () => kit.runAction('transcribe'), children: 'Transcribe again' }, 'run'),
      el('p', { style: muted, children: 'Transcribing again replaces the words and keeps nothing removed.' }, 'note'),
    ] }, 'transcription'),
    jsx(Disclosure, { title: 'Pause finder', children: [
      el('div', { style: row, children: [
        jsx(Field, { label: 'Silence threshold, dB (optional)', name: 'job.noise_db', value: jobOptions.noise_db, onCommit: option('noise_db') }, 'noise'),
        jsx(Field, { label: 'Shortest pause, s (optional)', name: 'job.min_duration', value: jobOptions.min_duration, onCommit: option('min_duration') }, 'min'),
      ] }, 'fields'),
      jsx(Button, { variant: 'secondary', onClick: () => kit.runAction('silence'), children: 'Find pauses' }, 'run'),
    ] }, 'silence'),
    jsx(Disclosure, { title: 'Story', children: jsx(StoryEditor, { kit }) }, 'story'),
    jsx(Disclosure, { title: 'Face analysis', children: jsx(VisionReview, { kit }) }, 'vision'),
    jsx(Disclosure, { title: 'Background layer', children: [
      el('p', { style: muted, children: 'Separates the person from the background so a graphic can sit behind them. Needs a background model file.' }, 'note'),
      jsx(Button, { variant: 'secondary', onClick: () => kit.run('segment', {}), children: 'Separate background' }, 'run'),
      el('label', { style: { ...row, fontSize: 13 }, children: [jsx(Tick, { 'aria-label': 'Use the separated background layer', checked: settings.use_segmented === true, onCheckedChange: checked => edit({ settings: { use_segmented: checked === true } }, 'Background layer') }), 'Use the separated background layer'] }, 'use'),
    ] }, 'segment'),
    jsx(Disclosure, { title: 'Framing pins', children: jsx(FramingPins, { kit }) }, 'pins'),
    jsx(Disclosure, { title: 'Title and brand', children: jsx(BrandFields, { kit }) }, 'brand'),
    jsx(Disclosure, { title: 'Project model paths', children: [
      el('p', { style: muted, children: 'Files on the computer that runs Cutroom. Nothing is downloaded automatically. New projects use the defaults from Settings → Plugins → Cutroom.' }, 'note'),
      text('whisper_model', 'Speech model (Whisper) file'), text('face_model', 'Face model file'), text('segmentation_model', 'Background model file'),
      integer('frame_step', 'Face analysis frame step'), integer('max_width', 'Largest render width'),
    ] }, 'models'),
  ] });
}

function FixWords({ kit }) {
  const words = kit.view.transcript?.words || [];
  const [page, setPage] = useState(0);
  if (!words.length) return el('p', { style: muted, children: 'No words yet.' });
  return el('div', { style: { ...stack, gap: 8 }, children: [
    el('p', { style: muted, children: 'Corrections keep each word\u2019s timing.' }, 'note'),
    el('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }, children: words.slice(page * 100, (page + 1) * 100).map(word => jsx(Field, { label: seconds(word.start), name: `caption.${word.id}`, value: word.text, onCommit: value => {
      if (!value.trim()) return 'A word cannot be empty';
      kit.correctWord(word.id, value);
      return undefined;
    } }, `caption:${word.id}`)) }, 'list'),
    words.length > 100 ? el('div', { style: row, children: [jsx(Button, { variant: 'ghost', disabled: page === 0, onClick: () => setPage(old => old - 1), children: 'Previous words' }, 'prev'), jsx(Button, { variant: 'ghost', disabled: (page + 1) * 100 >= words.length, onClick: () => setPage(old => old + 1), children: 'Next words' }, 'next')] }, 'pages') : null,
  ] });
}

function CutByTime({ kit }) {
  const { view, edit } = kit;
  const ranges = baseSegments(view);
  const duration = view.source_info?.duration;
  const commit = next => {
    let end = 0;
    for (const item of next) {
      if (!Number.isFinite(item.start) || !Number.isFinite(item.end) || item.start < end || item.end <= item.start || (Number.isFinite(duration) && item.end > duration)) return 'Ranges must be in order, not overlap and stay inside the source';
      end = item.end;
    }
    if (!next.length) return 'Keep at least one range';
    edit({ segments: next.map(item => ({ start: item.start, end: item.end })) }, 'Cut by time', 'ranges');
    return undefined;
  };
  const [error, setError] = useState(null);
  const change = (index, key) => value => commit(ranges.map((item, i) => (i === index ? { start: item.start, end: item.end, [key]: value === '' ? NaN : Number(value) } : { start: item.start, end: item.end })));
  return el('div', { style: { ...stack, gap: 8 }, children: [
    el('p', { style: muted, children: 'Kept parts of the source, in seconds. Removed words are skipped on top of these.' }, 'note'),
    ...ranges.map((item, index) => el('div', { style: { ...row, alignItems: 'flex-end' }, children: [
      jsx(Field, { label: `Part ${index + 1} start, s`, name: `range.${index}.start`, type: 'number', value: item.start, onCommit: change(index, 'start') }, 'start'),
      jsx(Field, { label: `Part ${index + 1} end, s`, name: `range.${index}.end`, type: 'number', value: item.end, onCommit: change(index, 'end') }, 'end'),
      jsx(Button, { variant: 'ghost', disabled: ranges.length < 2, onClick: () => setError(commit(ranges.filter((_, i) => i !== index))), children: 'Remove range' }, 'remove'),
    ] }, `range:${index}`)),
    jsx(Button, { variant: 'ghost', onClick: () => setError(commit([...ranges, { start: ranges.at(-1)?.end || 0, end: duration }])), children: 'Add a range' }, 'add'),
    error ? el('p', { role: 'alert', style: alertStyle, children: error }, 'error') : null,
  ] });
}

function StoryEditor({ kit }) {
  const { view, edit } = kit;
  return el('div', { style: { ...stack, gap: 8 }, children: [
    jsx(Field, { label: 'Brief: audience, message and desired outcome', name: 'brief', multiline: true, value: view.brief, onCommit: value => { edit({ brief: value }, 'Brief', 'brief'); return undefined; } }, 'brief'),
    jsx(Field, { label: 'Voice', name: 'voice', value: view.voice || 'neutral', onCommit: value => { edit({ voice: value }, 'Voice', 'voice'); return undefined; } }, 'voice'),
    el('p', { style: muted, children: 'Hooks quote the speaker\u2019s own words. They are draft openings, not invented lines.' }, 'note'),
    view.story?.hooks?.length ? el('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }, children: view.story.hooks.slice(0, 3).map((hook, index) => el('article', { style: { ...panel, padding: 10, gap: 6 }, children: [
      jsx(Badge, { children: view.selected_hook === index ? `Hook ${index + 1} · chosen` : `Hook ${index + 1}` }), el('p', { style: { margin: 0 }, children: hook.text }), el('small', { style: muted, children: `${seconds(hook.start)}–${seconds(hook.end)}` }),
      jsx(Button, { variant: 'secondary', onClick: () => edit({ selected_hook: index }, 'Hook'), children: `Use hook ${index + 1}` }),
    ] }, `hook:${index}`)) }, 'hooks') : el('p', { style: muted, children: 'Transcribe, then run Storyboard to get three hooks from the speaker\u2019s words.' }, 'empty'),
    el('p', { role: 'status', style: muted, children: storyStatus(view) }, 'status'),
    jsx(Button, { variant: 'secondary', onClick: () => kit.run('storyboard', {}), children: 'Run Storyboard' }, 'run'),
    ...(view.story?.storyboard || []).map((scene, index) => el('div', { style: { ...row, borderBottom: '1px solid var(--ui-stroke-secondary)', paddingBottom: 6 }, children: [jsx(Badge, { children: `Scene ${index + 1}` }), el('span', { style: muted, children: `${seconds(scene.source_start)}–${seconds(scene.source_end)}` }), el('span', { children: scene.text || 'Source footage' })] }, `scene:${index}`)),
  ] });
}

function VisionReview({ kit }) {
  const { view, edit } = kit;
  const analysis = view.analysis;
  return el('div', { style: { ...stack, gap: 8 }, children: [
    el('p', { style: muted, children: 'Gaze is an uncertain geometric proxy, not verified eye contact. Face presence and mouth motion are measurements, not a quality guarantee. Nothing is removed automatically.' }, 'note'),
    jsx(Button, { variant: 'secondary', onClick: () => kit.run('vision', {}), children: 'Analyse faces' }, 'run'),
    analysis ? el('p', { style: muted, children: `${analysis.status || 'Analysis ready'} · ${analysis.sampled_frames ?? analysis.frames?.length ?? 0} sampled frames · ${analysis.coverage?.complete ? 'complete coverage' : 'sampled coverage'}` }, 'summary') : el('p', { style: muted, children: 'No face analysis yet. It needs a face model file.' }, 'empty'),
    analysis?.frames?.length ? el('div', { style: { overflow: 'auto', maxHeight: 220 }, children: el('table', { style: { width: '100%', textAlign: 'left', fontSize: 12 }, children: [
      el('thead', { children: el('tr', { children: ['Time', 'Faces', 'Gaze proxy', 'Mouth motion'].map(label => el('th', { children: label }, label)) }) }, 'head'),
      el('tbody', { children: analysis.frames.slice(0, 120).map((frame, index) => el('tr', { children: [frame.time, frame.face_count, frame.gaze_score, frame.mouth_open].map((value, cell) => el('td', { style: { padding: 4 }, children: cell === 0 ? seconds(value) : value == null ? 'Unavailable' : String(value) }, cell)) }, index)) }, 'body'),
    ] }) }, 'table') : null,
    ...(analysis?.intervals || []).slice(0, 100).map((interval, index) => el('div', { style: row, children: [el('span', { children: `${seconds(interval.start)}–${seconds(interval.end)} · ${interval.reason || 'Worth a look'}` }), jsx(Button, { variant: 'ghost', onClick: () => edit({ gaze_exclusions: [...(view.gaze_exclusions || []), { start: interval.start, end: interval.end }] }, 'Remove part'), children: 'Remove this part' })] }, `interval:${index}`)),
    view.gaze_exclusions?.length ? jsx(Button, { variant: 'ghost', onClick: () => edit({ gaze_exclusions: [] }, 'Restore parts'), children: 'Restore all parts removed here' }, 'restore') : null,
  ] });
}

function FramingPins({ kit }) {
  const { view, edit, playback } = kit;
  const [horizontal, setHorizontal, horizontalRef] = useLive(0.5);
  const keys = view.settings?.framing_keyframes || [];
  const usable = playback.time !== null && playback.kind && playback.kind !== 'source';
  const pin = () => {
    if (!usable) return;
    const time = Math.round(playback.time * 1000) / 1000;
    const next = [...keys.filter(key => key.time !== time), { time, x: horizontalRef.current }].sort((a, b) => a.time - b.time);
    edit({ settings: { framing_keyframes: next } }, 'Framing pin');
  };
  return el('div', { style: { ...stack, gap: 8 }, children: [
    el('p', { style: muted, children: 'Pins use program time (the edited preview or final). Load a preview, pause where you want the crop to move, choose the horizontal centre and add a pin. Crop framings only.' }, 'note'),
    el('label', { style: { ...row, fontSize: 12 }, children: ['Horizontal crop centre', jsx('input', { name: 'framing.x', 'aria-label': 'Horizontal crop centre', type: 'range', min: 0, max: 1, step: 0.01, value: horizontal, onChange: event => setHorizontal(Number(event.target.value)), style: { accentColor: 'var(--ui-accent)' } })] }, 'slider'),
    jsx(Button, { variant: 'secondary', disabled: !usable || keys.length >= 100, onClick: pin, children: `Add framing keyframe at ${seconds(playback.time)}` }, 'add'),
    ...keys.map(key => el('div', { style: row, children: [el('span', { children: `${seconds(key.time)} program time · x ${key.x}` }), jsx(Button, { variant: 'ghost', onClick: () => edit({ settings: { framing_keyframes: keys.filter(item => item.time !== key.time) } }, 'Framing pin'), children: 'Remove framing keyframe' })] }, `framing-key:${key.time}`)),
  ] });
}

function BrandFields({ kit }) {
  const { view, edit } = kit;
  const settings = view.settings || {};
  const brand = settings.brand || {};
  const bounds = { title_size: [12, 120], subtitle_size: [12, 120], safe_margin: [0.02, 0.25] };
  const commit = (key, type) => raw => {
    const value = type === 'number' ? (raw === '' ? undefined : Number(raw)) : raw;
    if (key in bounds && value !== undefined && (!Number.isFinite(value) || value < bounds[key][0] || value > bounds[key][1])) return `${key} must be between ${bounds[key][0]} and ${bounds[key][1]}`;
    if (type === 'number' && value !== undefined && !Number.isFinite(value)) return 'Enter a number';
    if (key.endsWith('_color') && value && !HEX.test(value)) return 'Brand colours must be six-digit hex values';
    const next = { ...(computeBrand(kit)) };
    if (value === undefined || value === '') delete next[key]; else next[key] = value;
    edit({ settings: { brand: next } }, 'Brand', `brand:${key}`);
    return undefined;
  };
  const field = (label, key, type = 'text') => jsx(Field, { label, name: `brand.${key}`, type, value: brand[key], onCommit: commit(key, type) }, key);
  const setting = (label, key) => jsx(Field, { label, name: key, value: settings[key], onCommit: value => { edit({ settings: { [key]: value } }, label, `setting:${key}`); return undefined; } }, key);
  return el('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10 }, children: [
    setting('On-screen title', 'title'),
    field('Font (Arial / DejaVu Sans / Liberation Sans)', 'font'), field('Title colour (hex)', 'title_color'), field('Subtitle colour (hex)', 'subtitle_color'), field('Graphic colour (hex)', 'graphic_color'),
    field('Title size (12–120)', 'title_size', 'number'), field('Subtitle size (12–120)', 'subtitle_size', 'number'), field('Edge margin (0.02–0.25)', 'safe_margin', 'number'),
    field('Title height (0–1)', 'title_y', 'number'), field('Subtitle height (0–1)', 'subtitle_y', 'number'), field('Alignment (left / center / right)', 'alignment'),
    setting('Graphic image file (optional, behind the person)', 'graphic'), setting('Background image file or hex colour (optional)', 'background'),
  ] });
}
const computeBrand = kit => kit.view.settings?.brand || {};

function SettingsPage({ ctx }) {
  const [values, setValues, valuesRef] = useLive(() => readDefaults(ctx));
  const set = (key, value) => { const next = { ...valuesRef.current, [key]: value }; setValues(next); ctx.storage?.set?.('defaults', next); };
  const path = (key, label) => jsx(Field, { label, name: `default.${key}`, value: values[key], onCommit: value => { set(key, value.trim()); return undefined; } }, key);
  return el('div', { 'data-cutroom': '', style: { ...stack, gap: 16, maxWidth: 680, color: 'var(--ui-text-primary)' }, children: [
    el('style', { children: CSS }, 'css'),
    el('div', { style: { ...stack, gap: 4 }, children: [el('h2', { style: h2s, children: 'Cutroom' }), el('p', { style: muted, children: 'Defaults for new videos you import in Cutroom. Existing projects keep their own settings.' })] }, 'head'),
    el('section', { 'aria-labelledby': 'cutroom-models', style: stack, children: [
      el('h3', { id: 'cutroom-models', style: h3s, children: 'Model files' }),
      el('p', { style: muted, children: 'Files on the computer that runs Cutroom. Nothing is downloaded automatically.' }),
      path('whisper_model', 'Speech model (Whisper) file'), path('face_model', 'Face model file'), path('segmentation_model', 'Background model file'),
    ] }, 'models'),
    el('section', { 'aria-labelledby': 'cutroom-default-platform', style: stack, children: [
      el('h3', { id: 'cutroom-default-platform', style: h3s, children: 'Default platform' }),
      jsx(RadioCards, { label: 'Default platform', value: values.platform || 'custom', min: 130, onChange: value => set('platform', value), options: Object.entries(PLATFORM_NAMES).map(([value, title]) => ({ key: `default-platform:${value}`, value, title })) }),
    ] }, 'platform'),
    el('section', { 'aria-labelledby': 'cutroom-default-captions', style: stack, children: [
      el('h3', { id: 'cutroom-default-captions', style: h3s, children: 'Default caption style' }),
      jsx(RadioCards, { label: 'Default caption style', value: values.caption_style || 'highlight', min: 120, onChange: value => set('caption_style', value), options: CAPTION_STYLES.map(([value, title, detail]) => ({ key: `default-style:${value}`, value, title, detail })) }),
    ] }, 'captions'),
  ] });
}

function mediaOf(result) {
  let value = result;
  if (typeof value === 'string') { try { value = JSON.parse(value); } catch { value = null; } }
  const media = value && typeof value === 'object' ? value.media : null;
  return media && typeof media === 'object' ? media : {};
}

// The chat card for videos Cutroom tools produce. It opens the Studio; approval stays there.
function ChatCard(props) {
  const { file, result, fallback = null } = props || {};
  const media = mediaOf(result);
  const kind = file?.kind || media.kind;
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let live = true;
    if (kind === 'video' && typeof file?.resolveUrl === 'function') Promise.resolve().then(() => file.resolveUrl()).then(url => { if (live) setSrc(typeof url === 'string' ? url : ''); }, () => { if (live) setSrc(''); });
    return () => { live = false; };
  }, [file]);
  if (kind !== 'video') return fallback;
  const id = typeof media.project_id === 'string' && media.project_id ? media.project_id : null;
  const name = typeof media.project_name === 'string' && media.project_name ? media.project_name : file?.name || 'Cutroom video';
  const details = [PLATFORM_NAMES[media.platform] || null, Number.isFinite(media.duration) ? clock(media.duration) : null, Number.isFinite(media.width) && Number.isFinite(media.height) ? `${media.width} × ${media.height}` : null].filter(Boolean).join(' · ');
  return el('figure', { 'data-cutroom': '', style: { ...panel, gap: 8, padding: 12, margin: 0, maxWidth: 420, color: 'var(--ui-text-primary)' }, children: [
    src ? jsx('video', { src, controls: true, preload: 'metadata', 'aria-label': `Preview of ${name}`, style: { display: 'block', width: '100%', maxHeight: 320, borderRadius: 6 } }, 'video')
      : el('p', { style: muted, children: src === '' ? 'This video cannot be played here.' : 'Loading video…' }, 'placeholder'),
    el('figcaption', { style: { ...stack, gap: 2 }, children: [
      el('strong', { style: { fontSize: 13 }, children: name }),
      details ? el('span', { style: muted, children: details }) : null,
      el('span', { style: muted, children: chatQa(media.qa) }),
      el('span', { style: muted, children: media.approved === true ? '✓ Approved for export' : 'Not approved yet. Watch and approve it in Cutroom.' }),
    ] }, 'caption'),
    el('div', { style: row, children: id ? [
      jsx(Button, { onClick: () => requestOpen(id, 'review'), children: 'Review and approve' }, 'review'),
      jsx(Button, { variant: 'ghost', onClick: () => requestOpen(id, 'edit'), children: 'Open in Cutroom' }, 'open'),
    ] : [jsx(Button, { variant: 'ghost', onClick: () => host.navigate('/cutroom'), children: 'Open Cutroom' }, 'open')] }, 'actions'),
  ] });
}

export default {
  id: 'cutroom',
  name: 'Cutroom',
  description: 'Edit talking videos by text, review them and export locally.',
  defaultEnabled: false,
  register(ctx) {
    ctx.register({ id: 'studio', area: ROUTES_AREA, data: { path: '/cutroom' }, render: () => jsx(StudioPage, { ctx }) });
    ctx.register({ id: 'navigation', area: SIDEBAR_NAV_AREA, data: { path: '/cutroom', label: 'Cutroom', codicon: 'device-camera-video' } });
    ctx.register({ id: 'open-studio', area: PALETTE_AREA, data: { id: 'cutroom.open', label: 'Open Cutroom', keywords: ['video', 'edit', 'render', 'captions'], run: () => host.navigate('/cutroom') } });
    ctx.registerSettingsPage?.({ id: 'settings', title: 'Cutroom', icon: 'device-camera-video', render: () => jsx(SettingsPage, { ctx }) });
    if (typeof SDK.TOOL_MEDIA_RENDERER_AREA === 'string') ctx.register({ id: 'chat-card', area: SDK.TOOL_MEDIA_RENDERER_AREA, data: { tools: ['cutroom_job', 'cutroom_project'], render: props => jsx(ChatCard, props) } });
    ctx.onDispose?.(() => { opener.pending = null; opener.listeners.clear(); });
  },
};
