import { host, ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA, useValue, useQuery, useMutation, useQueryClient, Button, Input, Textarea, Checkbox, Badge, GlyphSpinner } from '@hermes/plugin-sdk';
import { useState, useRef, useEffect } from 'react';
import { jsx } from 'react/jsx-runtime';

const row = { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 };
const stack = { display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 };
const panel = { ...stack, padding: 16, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 10 };
const muted = { color: 'var(--ui-text-secondary)', fontSize: 12 };
const errorText = error => error?.message || String(error || '');

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
  return error ? jsx('p', { role: 'alert', style: { ...muted, color: 'var(--ui-text-primary)' }, children: errorText(error) }) : null;
}

function StudioPage({ ctx }) {
  const profile = useValue(host.state.profile);
  return jsx(StudioScope, { ctx, profile }, profile);
}

function StudioScope({ ctx, profile }) {
  const client = useQueryClient();
  const [selected, select] = useState(() => ctx.storage.get(`lastProject:${profile}`, ''));
  const [source, setSource, sourceRef] = useLive('');
  const [error, setError] = useState(null);
  const projects = useQuery({ queryKey: ['cutroom', profile, 'projects'], queryFn: () => ctx.rest('/projects'), refetchInterval: 5000 });
  const jobs = useQuery({ queryKey: ['cutroom', profile, 'jobs', selected], queryFn: () => ctx.rest(`/jobs?project_id=${encodeURIComponent(selected)}`), enabled: Boolean(selected), refetchInterval: 2500 });
  const project = useQuery({ queryKey: ['cutroom', profile, 'project', selected], queryFn: () => ctx.rest(`/projects/${encodeURIComponent(selected)}`), enabled: Boolean(selected), refetchInterval: jobs.data?.some(job => ['queued', 'running'].includes(job.status)) ? 2500 : false });
  const choose = id => { select(id); ctx.storage.set(`lastProject:${profile}`, id); setError(null); };
  const create = useMutation({ mutationFn: path => ctx.rest('/projects', { method: 'POST', body: { source: path }, timeoutMs: 120000 }), onSuccess: result => { choose(result.id); setSource(''); client.invalidateQueries({ queryKey: ['cutroom', profile] }); } });
  const importVideo = async () => {
    setError(null);
    try { await create.mutateAsync(sourceRef.current.trim()); } catch (failure) { setError(failure); }
  };
  return jsx('main', { 'aria-label': 'Cutroom Studio', style: { ...stack, padding: 20, overflow: 'auto', height: '100%', color: 'var(--ui-text-primary)' }, children: [
    jsx('header', { style: row, children: [jsx('h1', { style: { fontSize: 22, fontWeight: 600, margin: 0 }, children: 'Cutroom Studio' }), jsx(Badge, { children: 'Local workspace' }), jsx('span', { style: muted, children: `Profile: ${profile}` })] }),
    jsx('p', { style: muted, children: 'Non-destructive edits. Local models are optional. No publication or upload runs automatically.' }),
    jsx('section', { style: panel, 'aria-label': 'Import video', children: [
      jsx('label', { htmlFor: 'cutroom-source', children: 'Local video path on the backend machine' }),
      jsx('div', { style: row, children: [jsx(Input, { id: 'cutroom-source', name: 'source', value: source, placeholder: 'C:/Videos/source.mp4', style: { flex: '1 1 280px' }, onChange: event => setSource(event.target.value) }), jsx(Button, { disabled: create.isPending || !source.trim(), onClick: importVideo, children: create.isPending ? 'Importing…' : 'Import video' })] }),
      jsx(Notice, { error }),
    ] }),
    jsx('nav', { 'aria-label': 'Projects', style: row, children: [
      ...(projects.data || []).map(item => jsx(Button, { variant: item.id === selected ? 'secondary' : 'ghost', onClick: () => choose(item.id), children: item.name }, item.id)),
      jsx(Button, { variant: 'ghost', onClick: () => projects.refetch(), children: 'Refresh projects' }),
    ] }),
    jsx(Notice, { error: projects.error || project.error || jobs.error }),
    projects.isPending ? jsx(GlyphSpinner, {}) : null,
    project.data ? jsx(ProjectEditor, { ctx, profile, project: project.data, jobs: jobs.data || [] }, project.data.id) : jsx('p', { style: muted, children: 'Import a local video or select a project to begin.' }),
  ] });
}

const seconds = value => Number.isFinite(value) ? `${value.toFixed(2)}s` : '—';

function Section({ title, children }) {
  return jsx('section', { style: panel, children: [jsx('h2', { style: { fontSize: 16, fontWeight: 600, margin: 0 }, children: title }), children] });
}

function Field({ label, name, value, onChange, type = 'text', placeholder = '' }) {
  return jsx('label', { style: { ...stack, gap: 5, fontSize: 12 }, children: [label, jsx(Input, { name, value: value ?? '', type, placeholder, onChange: event => onChange(event.target.value) })] });
}

function ProjectEditor({ ctx, profile, project }) {
  const client = useQueryClient();
  const current = useRef(project);
  current.current = project;
  const busy = useRef(false);
  const [error, setError] = useState(null);
  const mutation = useMutation({
    mutationFn: async operation => {
      const latest = current.current;
      const path = `/projects/${encodeURIComponent(latest.id)}`;
      const result = await ctx.rest(path, { method: 'PATCH', body: { changes: operation.changes, revision: latest.revision } });
      return ctx.rest(`/projects/${encodeURIComponent(result.id)}`);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ['cutroom', profile] }),
  });
  const patch = async changes => {
    if (busy.current) return;
    busy.current = true; setError(null);
    try { return await mutation.mutateAsync({ changes }); } catch (failure) { setError(failure); }
    finally { busy.current = false; }
  };
  const exclude = (ids, included) => {
    const excluded = new Set(current.current.excluded_word_ids || []);
    for (const id of ids) included ? excluded.delete(id) : excluded.add(id);
    return patch({ excluded_word_ids: [...excluded] });
  };
  const info = project.source_info || {};
  return jsx('div', { style: stack, children: [
    jsx('header', { style: row, children: [jsx('h2', { style: { margin: 0, fontSize: 20 }, children: project.name }), jsx(Badge, { children: project.status || 'draft' }), jsx('span', { style: muted, children: `Revision ${project.revision}` })] }),
    jsx('p', { style: muted, children: `${seconds(info.duration)} · ${info.width || '—'} × ${info.height || '—'} · ${info.has_audio === false ? 'No audio' : 'Source audio'} · ${project.source}` }),
    jsx(Notice, { error }),
    jsx(TranscriptEditor, { project, exclude, disabled: mutation.isPending }),
    jsx(StoryEditor, { project, patch, disabled: mutation.isPending }),
    jsx(VisionReview, { project, patch, disabled: mutation.isPending }),
    jsx(SettingsForm, { project, patch, disabled: mutation.isPending }, project.revision),
  ] });
}

function TranscriptEditor({ project, exclude, disabled }) {
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState('');
  const words = (project.transcript?.words || []).filter(word => word.text.toLowerCase().includes(filter.toLowerCase()));
  const excluded = new Set(project.excluded_word_ids || []);
  const fillers = project.transcript?.fillers || project.filler_suggestions || project.fillers || [];
  return jsx(Section, { title: 'Transcript & Fillers', children: [
    jsx('p', { style: muted, children: 'Uncheck a word to exclude its timed source interval. Filler candidates are suggestions, not automatic removals; listen around every cut.' }),
    jsx(Input, { name: 'word-search', 'aria-label': 'Filter transcript words', value: filter, placeholder: 'Find words…', onChange: event => { setFilter(event.target.value); setPage(0); } }),
    words.length ? jsx('div', { style: { ...row, alignItems: 'stretch' }, children: words.slice(page * 150, (page + 1) * 150).map(word => jsx('label', { style: { ...row, padding: '6px 8px', border: '1px solid var(--ui-stroke-secondary)', borderRadius: 6, opacity: excluded.has(word.id) ? 0.6 : 1 }, children: [
      jsx(Checkbox, { checked: !excluded.has(word.id), disabled, 'aria-label': `Include word ${word.id}`, onCheckedChange: checked => exclude([word.id], checked === true) }),
      jsx('span', { children: word.text }), jsx('small', { style: muted, children: `${seconds(word.start)}–${seconds(word.end)}` }),
    ] }, word.id)) }) : jsx('p', { style: muted, children: project.transcript ? 'No matching words.' : 'No timed transcript yet. Configure a local Whisper model, then transcribe.' }),
    words.length > 150 ? jsx('div', { style: row, children: [jsx(Button, { variant: 'ghost', disabled: page === 0, onClick: () => setPage(value => value - 1), children: 'Previous words' }), jsx('span', { style: muted, children: `Page ${page + 1} of ${Math.ceil(words.length / 150)}` }), jsx(Button, { variant: 'ghost', disabled: (page + 1) * 150 >= words.length, onClick: () => setPage(value => value + 1), children: 'Next words' })] }) : null,
    jsx('h3', { style: { fontSize: 13, margin: 0 }, children: 'Fillers — review candidates' }),
    fillers.length ? fillers.map((candidate, index) => {
      const removed = (candidate.word_ids || []).every(id => excluded.has(id));
      return jsx('div', { style: row, children: [jsx('span', { children: `${candidate.text} · ${seconds(candidate.start)}–${seconds(candidate.end)}` }), jsx(Badge, { children: 'Review only' }), jsx(Button, { variant: 'ghost', disabled, onClick: () => exclude(candidate.word_ids || [], removed), children: removed ? 'Restore candidate' : 'Exclude candidate' })] }, index);
    }) : jsx('p', { style: muted, children: 'No filler suggestions available. Nothing is removed automatically.' }),
  ] });
}

function StoryEditor({ project, patch, disabled }) {
  const [brief, setBrief, briefRef] = useLive(project.brief || '');
  const [voice, setVoice, voiceRef] = useLive(project.voice || 'neutral');
  return jsx(Section, { title: 'Story · three grounded hooks', children: [
    jsx('label', { style: stack, children: ['Creative brief', jsx(Textarea, { name: 'brief', value: brief, onChange: event => setBrief(event.target.value), placeholder: 'Audience, message and desired outcome' })] }),
    jsx(Field, { label: 'Voice', name: 'voice', value: voice, onChange: setVoice }),
    jsx(Button, { variant: 'secondary', disabled, onClick: () => patch({ brief: briefRef.current, voice: voiceRef.current }), children: 'Save story brief' }),
    jsx('p', { style: muted, children: 'Hooks quote source words. They are draft alternatives, not invented dialogue or model reasoning.' }),
    project.story?.hooks?.length ? jsx('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }, children: project.story.hooks.slice(0, 3).map((hook, index) => jsx('article', { style: panel, children: [
      jsx(Badge, { children: project.selected_hook === index ? `Hook ${index + 1} · selected` : `Hook ${index + 1}` }), jsx('p', { children: hook.text }), jsx('small', { style: muted, children: `${seconds(hook.start)}–${seconds(hook.end)}` }), jsx(Button, { variant: 'secondary', disabled, onClick: () => patch({ selected_hook: index }), children: `Use hook ${index + 1}` }),
    ] }, index)) }) : jsx('p', { style: muted, children: 'Transcribe, then run Storyboard to generate three source-grounded hooks.' }),
    jsx('h3', { style: { fontSize: 13, margin: 0 }, children: 'Storyboard' }),
    ...(project.story?.storyboard || []).map((scene, index) => jsx('div', { style: { ...row, borderBottom: '1px solid var(--ui-stroke-secondary)', paddingBottom: 8 }, children: [jsx(Badge, { children: `Scene ${index + 1}` }), jsx('span', { style: muted, children: `${seconds(scene.source_start)}–${seconds(scene.source_end)}` }), jsx('span', { children: scene.text || 'Source footage' })] }, index)),
  ] });
}

function VisionReview({ project, patch, disabled }) {
  const analysis = project.analysis;
  return jsx(Section, { title: 'Vision review', children: [
    jsx('p', { style: muted, children: 'Gaze is an uncertain geometric proxy, not verified eye contact. Face presence and mouth motion are metrics, not a quality guarantee. No frames are removed automatically.' }),
    analysis ? jsx('div', { style: row, children: [jsx(Badge, { children: analysis.status || 'Analysis ready' }), jsx('span', { style: muted, children: `${analysis.sampled_frames ?? analysis.frames?.length ?? 0} sampled frames · ${analysis.coverage?.complete ? 'Complete frame coverage' : 'Partial / sampled coverage'}` })] }) : jsx('p', { style: muted, children: 'Configure a local face model, then run Vision. No analysis is connected yet.' }),
    analysis?.frames?.length ? jsx('div', { style: { overflow: 'auto', maxHeight: 230 }, children: jsx('table', { style: { width: '100%', textAlign: 'left', fontSize: 12 }, children: [
      jsx('thead', { children: jsx('tr', { children: ['Time', 'Faces', 'Gaze proxy', 'Mouth motion'].map(label => jsx('th', { children: label }, label)) }) }),
      jsx('tbody', { children: analysis.frames.slice(0, 120).map((frame, index) => jsx('tr', { children: [frame.time, frame.face_count, frame.gaze_score, frame.mouth_open].map((value, cell) => jsx('td', { style: { padding: 5 }, children: cell === 0 ? seconds(value) : value == null ? 'Unavailable' : String(value) }, cell)) }, index)) }),
    ] }) }) : null,
    analysis?.frames?.length > 120 ? jsx('p', { style: muted, children: 'Showing the first 120 sampled metrics. Coverage above describes the full analysis.' }) : null,
    ...(analysis?.intervals || []).slice(0, 100).map((interval, index) => jsx('div', { style: row, children: [jsx('span', { children: `${seconds(interval.start)}–${seconds(interval.end)} · ${interval.reason || 'Review candidate'}` }), jsx(Button, { variant: 'ghost', disabled, onClick: () => patch({ gaze_exclusions: [...(project.gaze_exclusions || []), { start: interval.start, end: interval.end }] }), children: 'Exclude reviewed interval' })] }, index)),
    project.gaze_exclusions?.length ? jsx(Button, { variant: 'ghost', disabled, onClick: () => patch({ gaze_exclusions: [] }), children: 'Restore all vision exclusions' }) : null,
  ] });
}

function SettingsForm({ project, patch, disabled }) {
  const [settings, setSettings, settingsRef] = useLive({ ...project.settings, aspect: project.settings?.aspect || 'source', brand: { ...project.settings?.brand } });
  const change = (key, value) => setSettings(old => ({ ...old, [key]: value }));
  const brand = (key, value) => setSettings(old => ({ ...old, brand: { ...old.brand, [key]: value } }));
  const field = (label, key, type = 'text') => jsx(Field, { label, name: key, type, value: settings[key], onChange: value => change(key, type === 'number' ? Number(value) : value) }, key);
  const brandField = (label, key, type = 'text') => jsx(Field, { label, name: `brand.${key}`, type, value: settings.brand[key], onChange: value => brand(key, type === 'number' ? Number(value) : value) }, key);
  return jsx(Section, { title: 'Brand, assets & local models', children: [
    jsx('p', { style: muted, children: 'Save settings before starting jobs. Paths are local to the backend machine. No model is downloaded automatically. A saved revision or completed analysis refreshes this form.' }),
    field('Video title', 'title'),
    jsx('div', { style: row, children: ['source', 'portrait', 'landscape', 'square'].map(aspect => jsx(Button, { variant: settings.aspect === aspect ? 'secondary' : 'ghost', onClick: () => { change('aspect', aspect); brand('aspect', aspect); }, children: aspect }, aspect)) }),
    jsx('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }, children: [
      brandField('Font family (Arial / DejaVu Sans / Liberation Sans)', 'font'), brandField('Title color (hex)', 'title_color'), brandField('Subtitle color (hex)', 'subtitle_color'), brandField('Graphic color (hex)', 'graphic_color'), brandField('Title size (12–120)', 'title_size', 'number'), brandField('Subtitle size (12–120)', 'subtitle_size', 'number'), brandField('Safe margin (fraction)', 'safe_margin', 'number'), brandField('Title Y (fraction)', 'title_y', 'number'), brandField('Subtitle Y (fraction)', 'subtitle_y', 'number'), brandField('Alignment (left / center / right)', 'alignment'),
      field('Graphic asset path (optional)', 'graphic'), field('Background path (optional)', 'background'), field('Whisper model path', 'whisper_model'), field('FaceLandmarker model path', 'face_model'), field('Segmentation model path', 'segmentation_model'), field('Model runtime Python path', 'runtime_python'), field('Vision frame step', 'frame_step', 'number'), field('Render maximum width', 'max_width', 'number'),
    ] }),
    jsx('div', { style: row, children: ['captions', 'normalize_audio', 'use_segmented'].map(key => jsx('label', { style: row, children: [jsx(Checkbox, { checked: settings[key] === true, onCheckedChange: checked => change(key, checked === true) }), key === 'captions' ? 'Burn timed captions' : key === 'normalize_audio' ? 'Normalize source audio' : 'Use segmented background output'] }, key)) }),
    jsx(Button, { disabled, onClick: () => patch({ settings: settingsRef.current }), children: 'Save settings' }),
  ] });
}

export default {
  id: 'cutroom',
  name: 'Cutroom Studio',
  description: 'Local editing, review and render jobs.',
  defaultEnabled: false,
  register(ctx) {
    ctx.register({ id: 'studio', area: ROUTES_AREA, data: { path: '/cutroom' }, render: () => jsx(StudioPage, { ctx }) });
    ctx.register({ id: 'navigation', area: SIDEBAR_NAV_AREA, data: { path: '/cutroom', label: 'Cutroom Studio', codicon: 'device-camera-video' } });
    ctx.register({ id: 'open-studio', area: PALETTE_AREA, data: { id: 'cutroom.open', label: 'Open Cutroom Studio', keywords: ['video', 'edit', 'render'], run: () => host.navigate('/cutroom') } });
  },
};
