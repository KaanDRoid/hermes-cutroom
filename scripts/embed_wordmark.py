"""Embed the wordmark into desktop/plugin.js as a small path table.

Usage: embed_wordmark.py <wordmark.svg> <plugin.js> [left,top,right,bottom crop]
"""

import re
import sys
from pathlib import Path

svg = Path(sys.argv[1]).read_text(encoding="utf-8")
plugin = Path(sys.argv[2])
# In the app the logo sits flush with the text beside it: crop the clear space
# to the ink (margins measured by the logo audit: left, top, right, bottom).
crop = [int(v) for v in sys.argv[3].split(",")] if len(sys.argv) > 3 else [0, 0, 0, 0]
x0, y0, x1, y1 = (
    float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()
)
view = f"{crop[0]:g} {crop[1]:g} {x1 - crop[0] - crop[2]:g} {y1 - crop[1] - crop[3]:g}"
transform = re.search(r'<g transform="([^"]+)"', svg).group(1)
paths = re.findall(
    r'<path fill="(#[0-9A-Fa-f]{6})" fill-rule="evenodd" d="([^"]+)"/>', svg
)
rows = ",\n".join(
    f"  ['{'accent' if fill.upper() == '#F2542D' else 'ink'}', '{d}']"
    for fill, d in paths
)
block = (
    "// The Cutroom wordmark (docs/brand): letters take the text colour, the portrait frame the app accent.\n"
    f"const WORDMARK = {{ viewBox: '{view}', transform: '{transform}', paths: [\n{rows},\n] }};\n"
    "const Wordmark = ({ height = 28 }) => el('svg', { xmlns: 'http://www.w3.org/2000/svg', viewBox: WORDMARK.viewBox, 'aria-hidden': true, focusable: 'false',\n"
    "  style: { height, width: 'auto', display: 'block' }, children: el('g', { transform: WORDMARK.transform, children: WORDMARK.paths.map(([paint, d], index) =>\n"
    "    el('path', { d, fillRule: 'evenodd', fill: paint === 'accent' ? 'var(--ui-accent)' : 'currentColor' }, `p${index}`)) }) });\n"
)
s = plugin.read_bytes().decode("utf-8")
nl = "\r\n" if "\r\n" in s else "\n"
s = s.replace("\r\n", "\n")
start = s.find("// The Cutroom wordmark (docs/brand)")
if start >= 0:
    end = s.index("`p${index}`)) }) });\n", start) + len("`p${index}`)) }) });\n")
    s = s[:start] + block + s[end:]
else:
    anchor = "function useLive(initial) {"
    assert s.count(anchor) == 1
    s = s.replace(anchor, block + "\n" + anchor)
old = "el('h1', { style: { fontSize: 22, fontWeight: 600, margin: 0 }, children: 'Cutroom' })"
new = "el('h1', { style: { margin: 0, lineHeight: 0, color: 'var(--ui-text-primary)' }, children: [jsx(Wordmark, { height: 30 }, 'logo'), el('span', { style: hidden, children: 'Cutroom' }, 'name')] })"
if old in s:
    s = s.replace(old, new)
plugin.write_bytes(s.replace("\n", nl).encode("utf-8"))
print(len(paths), "paths")
