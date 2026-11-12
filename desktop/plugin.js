import { host, ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA, useValue, useQuery, useMutation, useQueryClient, Button, Input, Textarea, Checkbox, Badge, GlyphSpinner } from '@hermes/plugin-sdk';
import { useState, useRef, useEffect } from 'react';
import { jsx } from 'react/jsx-runtime';
import * as SDK from '@hermes/plugin-sdk';

const row = { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 };
const stack = { display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 };
const panel = { ...stack, padding: 16, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 10 };
const muted = { color: 'var(--ui-text-secondary)', fontSize: 12 };
// The host's unchecked checkbox border can match the page background; outline it with a theme token.
const Tick = props => jsx(Checkbox, { ...props, style: props.checked ? props.style : { borderColor: 'var(--ui-text-tertiary)', ...props.style } });
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
  // Two hosts can share a profile name; the connection id keeps their caches apart.
  const connection = host.state.connectionId ? useValue(host.state.connectionId) || 'local' : 'local';
  return jsx(StudioScope, { ctx, profile, connection }, `${connection}\u0000${profile}`);
}

function StudioScope({ ctx, profile, connection }) {
  const client = useQueryClient();
  const scope = ['cutroom', connection, profile];
  const [selected, select] = useState(() => ctx.storage.get(`lastProject:${connection}:${profile}`, ''));
  const [source, setSource, sourceRef] = useLive('');
  const [error, setError] = useState(null);
  const projects = useQuery({ queryKey: [...scope, 'projects'], queryFn: () => ctx.rest('/projects'), refetchInterval: 5000 });
  // Keep polling while a job runs even if the window is hidden, so a finished render is not shown as queued.
  const working = useRef(false);
  const jobs = useQuery({ queryKey: [...scope, 'jobs', selected], queryFn: () => ctx.rest(`/jobs?project_id=${encodeURIComponent(selected)}`), enabled: Boolean(selected), refetchInterval: 2500, refetchIntervalInBackground: working.current });
  working.current = Array.isArray(jobs.data) && jobs.data.some(job => ['queued', 'running'].includes(job.status));
  const project = useQuery({ queryKey: [...scope, 'project', selected], queryFn: () => ctx.rest(`/projects/${encodeURIComponent(selected)}`), enabled: Boolean(selected), refetchInterval: 2500, refetchIntervalInBackground: working.current });
  // Sourced platform profiles drive the selector, derive buttons and safe-zone overlay.
  const platforms = useQuery({ queryKey: [...scope, 'platforms'], queryFn: () => ctx.rest('/platforms'), staleTime: 300000 });
  const choose = id => { select(id); ctx.storage.set(`lastProject:${connection}:${profile}`, id); setError(null); };
  const create = useMutation({ mutationFn: path => ctx.rest('/projects', { method: 'POST', body: { source: path }, timeoutMs: 120000 }), onSuccess: result => { choose(result.id); setSource(''); client.invalidateQueries({ queryKey: scope }); } });
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
    project.data ? jsx(ProjectEditor, { ctx, scope, project: project.data, jobs: jobs.data || [], platforms: Array.isArray(platforms.data) ? platforms.data : [], open: choose }, project.data.id) : jsx('p', { style: muted, children: 'Import a local video or select a project to begin.' }),
  ] });
}

const seconds = value => Number.isFinite(value) ? `${value.toFixed(2)}s` : '—';

function Section({ title, children }) {
  return jsx('section', { style: panel, children: [jsx('h2', { style: { fontSize: 16, fontWeight: 600, margin: 0 }, children: title }), children] });
}

function Field({ label, name, value, onChange, type = 'text', placeholder = '' }) {
  return jsx('label', { style: { ...stack, gap: 5, fontSize: 12 }, children: [label, jsx(Input, { name, value: value ?? '', type, placeholder, onChange: event => onChange(event.target.value) })] });
}

const platformOf = (platforms, project) => platforms.find(item => item.name === (project.settings?.platform || 'custom')) || null;
const percent = value => `${+(value * 100).toFixed(2)}%`;

function PlatformVersions({ ctx, scope, project, platforms, open }) {
  const client = useQueryClient();
  const lock = useRef(false);
  const [error, setError] = useState(null);
  const derive = useMutation({ mutationFn: platform => ctx.rest(`/projects/${encodeURIComponent(project.id)}/derive`, { method: 'POST', body: { platform } }) });
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
  const targets = platforms.filter(item => item.name !== 'custom');
  return jsx(Section, { title: 'Platform versions', children: [
    jsx('p', { style: muted, children: 'A version is a separate project from the same source. It copies the transcript, cuts, story and brand, then gets its own settings, review and approval. Nothing is approved by creating it.' }),
    project.derived_from ? jsx('p', { style: muted, children: `Derived from ${project.derived_from.project_id} at revision ${project.derived_from.revision}.` }) : null,
    jsx('div', { style: row, children: targets.map(item => jsx(Button, { variant: 'secondary', disabled: derive.isPending, onClick: () => create(item.name), children: `Create version for ${item.short_label || item.label}` }, `derive:${item.name}`)) }),
    jsx(Notice, { error }),
  ] });
}

function ProjectEditor({ ctx, scope, project, jobs, platforms = [], open = () => {} }) {
  const client = useQueryClient();
  const current = useRef(project);
  current.current = project;
  const busy = useRef(false);
  const [review, setReview, reviewRef] = useLive(null);
  const [confirmed, setConfirmed, confirmedRef] = useLive(false);
  const [approval, setApproval, approvalRef] = useLive(null);
  const epoch = useRef(0);
  const clearApproval = () => { epoch.current++; setReview(null); setConfirmed(false); setApproval(null); };
  const canFinal = () => Boolean(approvalRef.current && approvalRef.current.revision === current.current.revision && approvalRef.current.digest === reviewRef.current?.digest);
  const [error, setError] = useState(null);
  const mutation = useMutation({
    mutationFn: async operation => {
      const latest = current.current;
      const path = `/projects/${encodeURIComponent(latest.id)}`;
      const result = await ctx.rest(path, { method: 'PATCH', body: { changes: operation.changes, revision: latest.revision } });
      return ctx.rest(`/projects/${encodeURIComponent(result.id)}`);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: scope }),
  });
  const patch = async changes => {
    if (busy.current) return;
    busy.current = true; clearApproval(); setError(null);
    try { return await mutation.mutateAsync({ changes }); } catch (failure) { setError(failure); }
    finally { busy.current = false; }
  };
  const exclude = (ids, included) => {
    const excluded = new Set(current.current.excluded_word_ids || []);
    for (const id of ids) included ? excluded.delete(id) : excluded.add(id);
    return patch({ excluded_word_ids: [...excluded] });
  };
  const info = project.source_info || {};
  const reviewOperation = useMutation({ mutationFn: async approve => {
    const version = epoch.current;
    const path = `/projects/${encodeURIComponent(current.current.id)}`;
    const expected = reviewRef.current;
    if (approve && (!confirmedRef.current || !expected)) throw new Error('Confirm the reviewed digest first');
    const fresh = await ctx.rest(`${path}/review`);
    if (epoch.current !== version || fresh.project.revision !== current.current.revision) throw new Error('Project changed; save and review again');
    if (!approve) { setApproval(null); setConfirmed(false); setReview(fresh); return; }
    if (fresh.digest !== expected.digest) { clearApproval(); throw new Error('Review digest changed; review again'); }
    const result = await ctx.rest(`${path}/approve`, { method: 'POST', body: { digest: expected.digest, confirmed: true } });
    const verified = await ctx.rest(path);
    if (epoch.current !== version || result.approval?.digest !== expected.digest || verified.approval?.digest !== expected.digest || verified.revision !== fresh.project.revision) throw new Error('Approval changed; review again');
    setApproval(verified.approval);
    client.invalidateQueries({ queryKey: scope });
  } });
  const reviewNow = async approve => {
    if (busy.current) return;
    busy.current = true; setError(null);
    try { await reviewOperation.mutateAsync(approve); } catch (failure) { setApproval(null); setConfirmed(false); setError(failure); }
    finally { busy.current = false; }
  };
  return jsx('div', { 'aria-label': 'Project editing workspace', onChangeCapture: event => { if (!event?.target?.closest?.('[data-cutroom-confirm]')) clearApproval(); }, style: stack, children: [
    jsx('header', { style: row, children: [jsx('h2', { style: { margin: 0, fontSize: 20 }, children: project.name }), jsx(Badge, { children: project.status || 'draft' }), jsx('span', { style: muted, children: `Revision ${project.revision}` })] }),
    jsx('p', { style: muted, children: `${seconds(info.duration)} · ${info.width || '—'} × ${info.height || '—'} · ${info.has_audio === false ? 'No audio' : 'Source audio'} · ${project.source}` }),
    jsx(Notice, { error }),
    jsx(Section, { title: 'Review & human approval', children: [
      jsx(Button, { disabled: reviewOperation.isPending, onClick: () => reviewNow(false), children: 'Review current revision' }),
      review && review.project.revision === project.revision ? jsx('div', { style: stack, children: [
        jsx('p', { children: review.notice }),
        jsx('p', { style: muted, children: `${review.project.segments?.length || 0} kept ranges · ${review.project.excluded_word_ids?.length || 0} excluded words · ${review.project.settings?.aspect || 'source'} aspect · Revision ${review.project.revision}` }),
        jsx('code', { style: { overflowWrap: 'anywhere' }, children: review.digest }),
        jsx('label', { 'data-cutroom-confirm': true, style: row, children: [jsx(Tick, { 'aria-label': 'I reviewed this exact digest', checked: confirmed, onCheckedChange: checked => setConfirmed(checked === true) }), 'I reviewed source, cuts, captions, brand and assets for this exact digest.' ] }),
        jsx(Button, { disabled: !confirmed || reviewOperation.isPending, onClick: () => reviewNow(true), children: 'Approve reviewed digest' }),
      ] }) : null,
      jsx('p', { role: 'status', style: muted, children: canFinal() ? 'Current digest approved. Final export is enabled.' : 'Final export requires current human approval. Any edit clears confirmation.' }),
    ] }),
    jsx(JobPanel, { ctx, scope, project, jobs, approved: canFinal(), canFinal }),
    jsx(MediaPanel, { ctx, project, profile: platformOf(platforms, project) }),
    jsx(PlatformVersions, { ctx, scope, project, platforms, open }),
    jsx(TranscriptEditor, { project, exclude, disabled: mutation.isPending }),
    jsx(CorrectionEditor, { project, patch, dirty: clearApproval, disabled: mutation.isPending }, `corrections:${project.revision}`),
    jsx(StoryEditor, { project, patch, disabled: mutation.isPending }),
    jsx(VisionReview, { project, patch, disabled: mutation.isPending }),
    jsx(SettingsForm, { project, platforms, patch, dirty: clearApproval, disabled: mutation.isPending }, `settings:${project.revision}`),
  ] });
}

const jobActions = ['transcribe', 'silence', 'vision', 'segment', 'storyboard', 'preview', 'final', 'cover', 'qa'];

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

function MediaPanel({ ctx, project, profile = null }) {
  const [overlay, setOverlay] = useState(false);
  const zone = profile?.safe_zone || null;
  const [media, setMedia] = useState(null);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const generation = useRef(0);
  const url = useRef(null);
  const lock = useRef(false);
  const release = () => { generation.current++; lock.current = false; if (url.current) URL.revokeObjectURL(url.current); url.current = null; setMedia(null); setProgress(null); };
  useEffect(() => {
    release();
    return () => { generation.current++; if (url.current) URL.revokeObjectURL(url.current); url.current = null; };
  }, [project.id, project.revision, project.artifacts?.preview, project.artifacts?.final]);
  const load = async kind => {
    if (lock.current) return;
    release(); lock.current = true; setError(null);
    const token = generation.current;
    try {
      const parts = [];
      let offset = 0, total = null, version = null, mime = null;
      do {
        const chunk = await ctx.rest(`/projects/${encodeURIComponent(project.id)}/media/${kind}?offset=${offset}&length=1048576${version ? `&version=${encodeURIComponent(version)}` : ''}`);
        if (token !== generation.current) return;
        if (!Number.isSafeInteger(chunk.total) || chunk.total < 1 || chunk.total > 268435456) throw new Error('Native playback is limited to 256 MiB; render a smaller preview or download the artifact.');
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
    } catch (failure) { if (token === generation.current) setError(failure); }
    finally { if (token === generation.current) { lock.current = false; setProgress(null); } }
  };
  const download = async kind => {
    setError(null);
    try {
      if (typeof SDK.captureGatewayFileDownload !== 'function') throw new Error('This host does not support native downloads. Update Hermes Desktop; no unauthenticated fallback is used.');
      const save = SDK.captureGatewayFileDownload();
      const metadata = await ctx.rest(`/projects/${encodeURIComponent(project.id)}/artifact-info/${kind}`);
      if (typeof metadata.path !== 'string' || !metadata.path || typeof metadata.name !== 'string' || !metadata.name) throw new Error('Artifact metadata is incomplete');
      await save(metadata.path, metadata.name);
    } catch (failure) { setError(failure); }
  };
  return jsx(Section, { title: 'Playback & downloads', children: [
    jsx('p', { style: muted, children: 'Explicit authenticated loads only, up to 256 MiB. Codec support depends on this Desktop host. Downloads use the native save dialog, without loading the entire artifact into memory.' }),
    jsx('div', { style: row, children: ['source', 'preview', 'final'].map(kind => jsx(Button, { disabled: progress !== null || (kind !== 'source' && !project.artifacts?.[kind]), onClick: () => load(kind), children: `Load ${kind}` }, kind)) }),
    progress !== null ? jsx('progress', { 'aria-label': 'Media loading progress', max: 1, value: progress }) : null,
    jsx('label', { style: row, children: [jsx(Tick, { 'aria-label': 'Show safe zone', checked: overlay && Boolean(zone), disabled: !zone, onCheckedChange: checked => setOverlay(checked === true) }), zone ? `Show ${profile.label} safe zone on renders (shaded areas may be covered by the app)` : 'Safe zone: choose a platform profile in settings'] }),
    media ? (() => {
      const player = jsx('video', { src: media.url, controls: true, preload: 'metadata', 'aria-label': `${media.kind} player`, style: overlay && zone && media.kind !== 'source' ? { display: 'block', maxWidth: '100%', maxHeight: 420 } : { width: '100%', maxHeight: 420 }, onError: () => { setError(new Error('This host cannot decode this media. Download it or render a compatible MP4 preview.')); release(); } }, 'player:video');
      if (!(overlay && zone && media.kind !== 'source')) return player;
      // The wrapper shrinks to the video box, so percentages follow the rendered frame.
      return jsx('div', { 'aria-label': 'Safe zone overlay', style: { position: 'relative', display: 'inline-block', maxWidth: '100%', alignSelf: 'flex-start' }, children: [player, ...SafeZoneOverlay({ zone })] });
    })() : null,
    jsx(Button, { variant: 'ghost', onClick: release, children: 'Unload media / cancel load' }),
    jsx('div', { style: row, children: [['captions_srt', 'SRT'], ['captions_vtt', 'VTT'], ['quality', 'report'], ['cover', 'cover'], ['preview', 'preview'], ['final', 'final']].map(([kind, label]) => jsx(Button, { variant: 'secondary', disabled: !project.artifacts?.[kind], onClick: () => download(kind), children: `Download ${label}` }, kind)) }),
    jsx(Notice, { error }),
  ] });
}

function JobPanel({ ctx, scope, project, jobs, approved, canFinal }) {
  const client = useQueryClient();
  const [options, setOptions, optionsRef] = useLive({ language: '', noise_db: '', min_duration: '' });
  const current = useRef({ project, approved });
  current.current = { project, approved };
  const lock = useRef(false);
  const [error, setError] = useState(null);
  const mutation = useMutation({
    mutationFn: async operation => {
      if (operation.cancel) return ctx.rest(`/jobs/${encodeURIComponent(operation.cancel)}/cancel`, { method: 'POST' });
      if (!jobActions.includes(operation.action)) throw new Error('Unsupported local action');
      if (operation.action === 'final' && !canFinal()) throw new Error('Review and approve the current digest first');
      return ctx.rest(`/projects/${encodeURIComponent(current.current.project.id)}/jobs`, { method: 'POST', body: { action: operation.action, options: operation.options || {} } });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: scope }),
  });
  const run = async operation => {
    if (lock.current) return;
    lock.current = true; setError(null);
    try {
      if (!operation.cancel && !operation.options) {
        const values = optionsRef.current;
        operation = { ...operation, options: {} };
        if (operation.action === 'transcribe' && values.language.trim()) {
          const language = values.language.trim();
          if (!/^[a-z]{2,3}$/.test(language)) throw new Error('Language must be a lowercase two- or three-letter code, for example en or tr');
          operation.options.language = language;
        }
        if (operation.action === 'silence') for (const key of ['noise_db', 'min_duration']) if (values[key].trim()) {
          const value = Number(values[key]);
          if (!Number.isFinite(value) || (key === 'min_duration' && value <= 0)) throw new Error('Silence duration must be positive and options must be finite numbers');
          operation.options[key] = value;
        }
      }
      await mutation.mutateAsync(operation);
    } catch (failure) { setError(failure); }
    finally { lock.current = false; }
  };
  return jsx(Section, { title: 'Local jobs', children: [
    jsx('p', { style: muted, children: 'Save edits first. Actions use the saved local model paths and render settings. Nothing is downloaded or published here.' }),
    jsx('div', { style: row, children: [['language', 'Transcription language code (blank: detect)'], ['noise_db', 'Silence threshold (dB, optional)'], ['min_duration', 'Minimum silence duration (seconds, optional)']].map(([key, label]) => jsx(Field, { label, name: `job.${key}`, value: options[key], onChange: value => setOptions(old => ({ ...old, [key]: value })) }, key)) }),
    jsx('div', { style: row, children: jobActions.map(action => jsx(Button, { variant: 'secondary', disabled: mutation.isPending || (action === 'final' && !approved), onClick: () => run({ action }), children: `Run ${action}` }, action)) }),
    jsx(Notice, { error }),
    ...jobs.map(job => jsx('article', { style: panel, children: [
      jsx('div', { style: row, children: [jsx(Badge, { children: job.status }), jsx('strong', { children: job.action }), jsx('span', { style: muted, children: `Revision ${job.revision ?? '—'}${job.cancel_requested ? ' · Cancellation requested' : ''}` })] }),
      jsx('progress', { 'aria-label': `${job.action} progress`, max: 1, value: Math.max(0, Math.min(1, Number(job.progress) || 0)) }),
      jsx(Notice, { error: job.error }),
      ['queued', 'running'].includes(job.status) ? jsx(Button, { disabled: mutation.isPending || job.cancel_requested, onClick: () => run({ cancel: job.id }), children: `Cancel ${job.action}` }) : null,
      ['failed', 'cancelled'].includes(job.status) && jobActions.includes(job.action) ? jsx(Button, { disabled: mutation.isPending || (job.action === 'final' && !approved), onClick: () => run({ action: job.action, options: job.options }), children: `Retry ${job.action}` }) : null,
    ] }, job.id)),
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
      jsx(Tick, { checked: !excluded.has(word.id), disabled, 'aria-label': `Include word ${word.id}`, onCheckedChange: checked => exclude([word.id], checked === true) }),
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

function storyStatus(project) {
  const story = project.story;
  if (!story?.hooks?.length) return 'No hooks yet.';
  if (project.selected_hook == null) return 'Choose a hook, then run Storyboard again to build its scenes.';
  if (story.selected_hook !== project.selected_hook || !story.storyboard?.length) return `Run Storyboard to build scenes for hook ${project.selected_hook + 1}.`;
  return `Opening hook: ${story.opening_hook?.text || story.hooks[project.selected_hook]?.text || ''}. Used as the on-screen title when no title is set.`;
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
    jsx('p', { role: 'status', style: muted, children: storyStatus(project) }),
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

function CorrectionEditor({ project, patch, dirty, disabled }) {
  const [words, setWords, wordsRef] = useLive(project.transcript?.words || []);
  const [ranges, setRanges, rangesRef] = useLive(project.base_segments || project.segments || []);
  const [page, setPage] = useState(0);
  const [error, setError] = useState(null);
  const correct = (id, value) => { dirty(); setWords(old => old.map(word => word.id === id ? { ...word, text: value } : word)); };
  const range = (index, key, value) => { dirty(); setRanges(old => old.map((item, i) => i === index ? { ...item, [key]: Number(value) } : item)); };
  const saveWords = () => {
    if (wordsRef.current.some(word => !word.text.trim())) { setError(new Error('Caption words cannot be empty')); return; }
    setError(null);
    return patch({ transcript: { ...project.transcript, words: wordsRef.current, text: wordsRef.current.map(word => word.text).join(' ') } });
  };
  const saveRanges = () => {
    let end = 0;
    for (const item of rangesRef.current) {
      if (!Number.isFinite(item.start) || !Number.isFinite(item.end) || item.start < end || item.end <= item.start || item.end > project.source_info.duration) { setError(new Error('Ranges must be ordered, non-overlapping and inside the source')); return; }
      end = item.end;
    }
    if (!rangesRef.current.length) { setError(new Error('Keep at least one manual source range')); return; }
    setError(null); return patch({ segments: rangesRef.current });
  };
  return jsx(Section, { title: 'Caption corrections & manual ranges', children: [
    jsx('p', { style: muted, children: 'Text corrections preserve word IDs, timing and confidence. Manual ranges remain the base; word and vision exclusions are applied on top.' }),
    ...words.slice(page * 100, (page + 1) * 100).map(word => jsx(Field, { label: `${seconds(word.start)}–${seconds(word.end)}`, name: `caption.${word.id}`, value: word.text, onChange: value => correct(word.id, value) }, `caption:${word.id}`)),
    words.length > 100 ? jsx('div', { style: row, children: [jsx(Button, { disabled: page === 0, onClick: () => setPage(old => old - 1), children: 'Previous captions' }), jsx(Button, { disabled: (page + 1) * 100 >= words.length, onClick: () => setPage(old => old + 1), children: 'Next captions' })] }) : null,
    jsx(Button, { disabled: disabled || !words.length, onClick: saveWords, children: 'Save caption corrections' }),
    ...ranges.map((item, index) => jsx('div', { style: row, children: [
      ...['start', 'end'].map(key => jsx(Field, { label: `Range ${index + 1} ${key} (seconds)`, name: `range.${index}.${key}`, type: 'number', value: item[key], onChange: value => range(index, key, value) }, key)),
      jsx(Button, { variant: 'ghost', disabled: ranges.length < 2, onClick: () => { dirty(); setRanges(old => old.filter((_, i) => i !== index)); }, children: 'Remove range' }),
    ] }, index)),
    jsx(Button, { variant: 'ghost', onClick: () => { dirty(); setRanges(old => [...old, { start: old.at(-1)?.end || 0, end: project.source_info.duration }]); }, children: 'Add manual range' }),
    jsx(Button, { disabled, onClick: saveRanges, children: 'Save manual ranges' }), jsx(Notice, { error }),
  ] });
}

function SettingsForm({ project, platforms = [], patch, dirty, disabled }) {
  const [settings, setSettings, settingsRef] = useLive({ ...project.settings, aspect: project.settings?.aspect || 'source', brand: { ...project.settings?.brand } });
  const [error, setError] = useState(null);
  const change = (key, value) => { dirty(); setSettings(old => ({ ...old, [key]: value })); };
  const brand = (key, value) => { dirty(); setSettings(old => ({ ...old, brand: { ...old.brand, [key]: value } })); };
  const save = () => {
    const value = settingsRef.current;
    const bounds = { title_size: [12, 120], subtitle_size: [12, 120], safe_margin: [0.02, 0.25] };
    for (const [key, [min, max]] of Object.entries(bounds)) if (value.brand[key] != null && (!Number.isFinite(value.brand[key]) || value.brand[key] < min || value.brand[key] > max)) { setError(new Error(`${key} must be between ${min} and ${max}`)); return; }
    for (const key of ['title_color', 'subtitle_color', 'graphic_color']) if (value.brand[key] && !/^#[0-9a-f]{6}$/i.test(value.brand[key])) { setError(new Error('Brand colors must be six-digit hex values')); return; }
    for (const key of ['frame_step', 'max_width']) if (value[key] != null && (!Number.isInteger(value[key]) || value[key] < 1)) { setError(new Error(`${key} must be a positive integer`)); return; }
    setError(null); return patch({ settings: value });
  };
  const field = (label, key, type = 'text') => jsx(Field, { label, name: key, type, value: settings[key], onChange: value => change(key, type === 'number' ? Number(value) : value) }, key);
  const selected = platforms.find(item => item.name === (settings.platform || 'custom')) || null;
  const platformFixed = Boolean(selected?.frame);
  const choosePlatform = item => { change('platform', item.name); if (item.orientation) { change('aspect', item.orientation); brand('aspect', item.orientation); } };
  const resolution = settings.final_resolution || selected?.frame?.default_final || '1080';
  const summary = () => {
    if (!platformFixed) return 'Custom: frame follows the aspect below (1080 preview, 2160 final), loudness −16 LUFS. No platform limits are checked.';
    const final = selected.frame.final[resolution] || [];
    const limit = selected.max_duration_s?.value;
    return `${selected.label}: preview ${selected.frame.preview.join(' × ')}, final ${final.join(' × ')} · ${limit ? `max ${limit} s` : 'no length limit'} · −14 LUFS, −1 dBTP · text kept inside the platform safe zone.`;
  };
  const brandField = (label, key, type = 'text') => jsx(Field, { label, name: `brand.${key}`, type, value: settings.brand[key], onChange: value => brand(key, type === 'number' ? Number(value) : value) }, key);
  return jsx(Section, { title: 'Brand, assets & local models', children: [
    jsx('p', { style: muted, children: 'Save settings before starting jobs. Paths are local to the backend machine. No model is downloaded automatically. A saved revision or completed analysis refreshes this form.' }),
    field('Video title', 'title'),
    jsx('div', { role: 'group', 'aria-label': 'Platform profile', style: row, children: platforms.map(item => jsx(Button, { variant: (settings.platform || 'custom') === item.name ? 'secondary' : 'ghost', onClick: () => choosePlatform(item), children: item.label }, `platform:${item.name}`)) }),
    jsx('div', { role: 'group', 'aria-label': 'Final resolution', style: row, children: [['1080', 'HD final (1080)'], ['2160', '4K final (2160)']].map(([value, label]) => jsx(Button, { variant: platformFixed && resolution === value ? 'secondary' : 'ghost', disabled: !platformFixed, onClick: () => change('final_resolution', value), children: label }, `resolution:${value}`)) }),
    jsx('p', { role: 'status', style: muted, children: summary() }),
    jsx('div', { role: 'group', 'aria-label': 'Aspect', style: row, children: ['source', 'portrait', 'landscape', 'square'].map(aspect => jsx(Button, { variant: settings.aspect === aspect ? 'secondary' : 'ghost', disabled: platformFixed, onClick: () => { change('aspect', aspect); brand('aspect', aspect); }, children: aspect }, `aspect:${aspect}`)) }),
    jsx('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }, children: [
      brandField('Font family (Arial / DejaVu Sans / Liberation Sans)', 'font'), brandField('Title color (hex)', 'title_color'), brandField('Subtitle color (hex)', 'subtitle_color'), brandField('Graphic color (hex)', 'graphic_color'), brandField('Title size (12–120)', 'title_size', 'number'), brandField('Subtitle size (12–120)', 'subtitle_size', 'number'), brandField('Safe margin (fraction)', 'safe_margin', 'number'), brandField('Title Y (fraction)', 'title_y', 'number'), brandField('Subtitle Y (fraction)', 'subtitle_y', 'number'), brandField('Alignment (left / center / right)', 'alignment'),
      field('Graphic raster asset path (optional, behind person)', 'graphic'), field('Background raster path or RGB hex color (optional)', 'background'), field('Whisper model path', 'whisper_model'), field('FaceLandmarker model path', 'face_model'), field('Segmentation model path', 'segmentation_model'), field('Vision frame step', 'frame_step', 'number'), field('Render maximum width', 'max_width', 'number'),
    ] }),
    jsx('div', { style: row, children: ['captions', 'normalize_audio', 'use_segmented'].map(key => jsx('label', { style: row, children: [jsx(Tick, { checked: settings[key] === true, onCheckedChange: checked => change(key, checked === true) }), key === 'captions' ? 'Burn timed captions' : key === 'normalize_audio' ? 'Normalize source audio' : 'Use segmented background output'] }, key)) }),
    jsx(Button, { disabled, onClick: save, children: 'Save settings' }), jsx(Notice, { error }),
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
