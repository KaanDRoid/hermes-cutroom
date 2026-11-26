// Page for tests/desktop-pixels.mjs: the real plugin and real React on a stand-in host and backend.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { backend } from './sdk.js';
import plugin from 'PLUGIN';

let root = null;

window.__mount = async ({ project, platforms, theme, posterColour, assetSize = 100 * 1048576 }) => {
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
    if (path.includes('/artifact-info/')) return { path: 'x', name: 'x.mp4', size: assetSize };
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
