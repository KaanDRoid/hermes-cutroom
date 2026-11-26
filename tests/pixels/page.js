// Page for tests/desktop-pixels.mjs: the real plugin and real React on a stand-in host and backend.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { backend } from './sdk.js';
import plugin from 'PLUGIN';

let root = null;

// media: a real file on the test server that the stand-in serves in 1 MiB pieces, each after delayMs.
window.__served = [];
window.__mount = async ({ project, platforms, theme, posterColour, assetSize = 100 * 1048576, media = null }) => {
  for (const [name, value] of Object.entries(theme)) document.documentElement.style.setProperty(name, value);
  const canvas = document.createElement('canvas');
  canvas.width = 640; canvas.height = 360;
  const paint = canvas.getContext('2d');
  paint.fillStyle = posterColour;
  paint.fillRect(0, 0, 640, 360);
  const poster = { mime: 'image/jpeg', data_url: canvas.toDataURL('image/jpeg', 0.92), time: project.posterTime ?? 3.6 };
  let current = structuredClone(project);
  backend.rest = async (path, options) => {
    if (path === '/platforms') return platforms;
    if (path === '/projects') return [current];
    if (path.includes('/artifact-info/preview') && media) return { path: 'x', name: 'preview.mp4', mime: 'video/mp4', size: media.size, stream: media.stream };
    if (path.includes('/artifact-info/')) return { path: 'x', name: 'x.mp4', size: assetSize };
    if (path.includes('/media/preview') && media) {
      const offset = Number(new URL(path, 'https://x').searchParams.get('offset') || 0);
      const end = Math.min(media.size, offset + 1048576);
      if (offset > 0) await new Promise(resolve => setTimeout(resolve, media.delayMs));
      const bytes = new Uint8Array(await (await fetch(media.url, { headers: { Range: `bytes=${offset}-${end - 1}` } })).arrayBuffer());
      let binary = '';
      for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
      window.__served.push(end);
      return { data: btoa(binary), offset, next_offset: end, total: media.size, mime: 'video/mp4', version: 'v1' };
    }
    if (path.includes('/poster')) return poster;
    if (path.includes('/layout-still')) return null;
    if (path.startsWith('/jobs')) return [];
    if (options?.method === 'PATCH') {
      const changes = options.body.changes || {};
      const settings = { ...current.settings, ...(changes.settings || {}) };
      for (const [key, value] of Object.entries(changes.settings || {})) if (value === null) delete settings[key];
      current = { ...current, ...changes, settings, revision: current.revision + 1 };
      backend.bump();
      return current;
    }
    return current;
  };
  const stored = { 'lastProject:local:default': project.id };
  const entries = [];
  plugin.register({
    register: entry => entries.push(entry),
    registerSettingsPage() {},
    storage: { get: (key, fallback) => (key in stored ? stored[key] : fallback), set: (key, value) => { stored[key] = value; } },
    rest: (path, options) => backend.rest(path, options),
    files: { requestFolder: async () => ({ ok: false }), list: async () => ({ ok: true, entries: [] }) },
  });
  if (root) root.unmount();
  root = createRoot(document.getElementById('app'));
  backend.bump();
  const route = entries.find(entry => entry.area === 'routes');
  root.render(React.createElement(() => route.render()));
  await new Promise(resolve => setTimeout(resolve, 600));
};
