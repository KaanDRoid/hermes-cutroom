// Stand-in for @hermes/plugin-sdk used by tests/desktop-pixels.mjs: real React, plain HTML controls.
// Queries resolve once from the stand-in backend; buttons and inputs use the host's theme tokens.
import React from 'react';

const el = React.createElement;
const cache = new Map();
let version = 0;
const listeners = new Set();
export const backend = { rest: null, bump() { version++; cache.clear(); listeners.forEach(f => f()); } };

const pass = props => {
  const { variant, size, asChild, onCheckedChange, onValueChange, ...rest } = props;
  return rest;
};
export const ROUTES_AREA = 'routes', SIDEBAR_NAV_AREA = 'nav', PALETTE_AREA = 'palette', TOOL_MEDIA_RENDERER_AREA = 'media';
export const host = { navigate() {}, state: { profile: { get: () => 'default' }, connectionId: { get: () => 'local' } } };
export const useValue = atom => atom.get();
export const useQuery = options => {
  const [, force] = React.useState(0);
  const key = JSON.stringify(options.queryKey);
  React.useEffect(() => {
    const again = () => force(n => n + 1);
    listeners.add(again);
    if (options.enabled !== false && !cache.has(key)) {
      Promise.resolve(options.queryFn()).then(value => { cache.set(key, value); again(); }, () => {});
    }
    return () => listeners.delete(again);
  }, [key, options.enabled, version]);
  return { data: options.enabled === false ? undefined : cache.get(key), isPending: false, isFetching: false, error: null, refetch() {} };
};
export const useQueryClient = () => ({ invalidateQueries() { backend.bump(); }, setQueryData() {} });
export const useMutation = options => ({ isPending: false, mutateAsync: options.mutationFn, mutate: options.mutationFn });
export const relativeTime = () => 'just now';
export const Button = props => el('button', { ...pass(props), className: `sdk-button ${props.variant || 'primary'}` }, props.children);
export const Input = props => el('input', { ...pass(props), className: 'sdk-input' });
export const Textarea = props => el('textarea', { ...pass(props), className: 'sdk-input' });
export const Checkbox = props => el('input', { type: 'checkbox', checked: Boolean(props.checked), onChange: event => props.onCheckedChange?.(event.target.checked), 'aria-label': props['aria-label'] });
export const Switch = props => el('button', { role: 'switch', className: 'sdk-switch', 'aria-checked': Boolean(props.checked), 'aria-label': props['aria-label'], onClick: () => props.onCheckedChange?.(!props.checked) });
export const Badge = props => el('span', { className: 'sdk-badge' }, props.children);
export const GlyphSpinner = () => el('span', null, '…');
