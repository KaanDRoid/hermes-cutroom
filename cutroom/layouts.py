"""Split explainer and picture-over-you layouts for 9:16 videos.

Geometry is in 1080 x 1920 frame pixels and is shared with the Studio
preview (desktop/plugin.js mirrors PALETTE and geometry()). Layout settings
are validated here before they are saved on a project.
"""

import json
import math
import subprocess
from pathlib import Path

from .project import file_digest

FRAME = (1080, 1920)
LAYOUTS = ("full", "split", "over")
BACKGROUNDS = ("paper", "grid", "kraft", "dark")
SPEAKERS = ("small", "wide", "full")
HOLDS = ("whole", "opening")
CARD_TYPES = ("title", "number", "quote", "bars", "apps", "terminal")
DIVIDER = (1060, 1420)
DEFAULT_DIVIDER = 1170
OPENING_SECONDS = 3.0
MAX_PICTURES = 50
PANEL_MAX_BYTES = 512 * 1024 * 1024

# Colours burned into the video. The Studio preview declares the same values.
PALETTE = {
    "paper_paper": "#EBE1D1",
    "paper_ink": "#1D2128",
    "grid_paper": "#F4F2EC",
    "grid_ink": "#1D2128",
    "grid_line": "#00000012",
    "kraft_paper": "#C5A888",
    "kraft_ink": "#1D1A16",
    "dark_paper": "#101114",
    "dark_ink": "#F4F4F5",
    "card": "#FFFFFF",
    "dark_card": "#1D1F24",
    "box": "#FFD02B",
    "on_box": "#101114",
    "cover": "#101114",
    "shadow": "#00000066",
    "terminal": "#1E1F22",
    "terminal_text": "#D6D6D6",
    "terminal_command": "#FFFFFF",
    "terminal_ok": "#7FD18B",
    "terminal_red": "#FF5F57",
    "terminal_yellow": "#FEBC2E",
    "terminal_green": "#28C840",
}

_KEYS = {"layout", "background", "speaker", "divider", "hold", "headline", "panel", "pictures"}
_IMAGE_FORMATS = {"image2", "png_pipe", "jpeg_pipe", "webp_pipe"}
_VIDEO_FORMATS = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm"}
_TEXT_LIMITS = {"title": 120, "number": 24, "quote": 200, "bars": 200, "apps": 200, "terminal": 400}


def upper(text, language="en"):
    """Capitals that respect Turkish and Azeri dotted and dotless i."""
    text = str(text)
    if str(language or "").lower().split("-")[0] in {"tr", "az"}:
        text = text.replace("i", "İ").replace("ı", "I")
    return text.upper()


def _text(value, limit, name, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name} must be one line of at most {limit} characters")
    if required and not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


def _time(value, duration, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a number of seconds")
    if not 0 <= value <= duration:
        raise ValueError(f"{name} must be inside the source")
    return float(value)


def _probe(path):
    from .postproduction import _run

    data = json.loads(
        _run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-show_streams", "-show_format", "-of", "json", str(path)],
            timeout=30,
        ).stdout
    )
    formats = set(data["format"]["format_name"].split(","))
    video = next(s for s in data["streams"] if s.get("codec_type") == "video")
    return formats, video, data["format"]


def normalize_item(spec):
    """A card drawn by Cutroom or a local picture/screen recording."""
    if not isinstance(spec, dict):
        raise ValueError("A panel item must be a card or a local file")
    if spec.get("kind") == "card":
        if set(spec) - {"kind", "type", "text", "detail"}:
            raise ValueError("Unknown card fields")
        if spec.get("type") not in CARD_TYPES:
            raise ValueError("Unknown card type")
        return {
            "kind": "card",
            "type": spec["type"],
            "text": _text(spec.get("text"), _TEXT_LIMITS[spec["type"]], "Card text", required=True),
            "detail": _text(spec.get("detail"), 120, "Card caption"),
        }
    if spec.get("kind") != "file":
        raise ValueError("A panel item must be a card or a local file")
    from .postproduction import _path

    raw = spec.get("path")
    if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
        # A relative path would depend on the server's working directory.
        raise ValueError("A panel file needs an absolute local path")
    path = _path(raw)
    size = path.stat().st_size
    if not 0 < size <= PANEL_MAX_BYTES:
        raise ValueError("A panel file must be between 1 byte and 512 MiB")
    before = file_digest(path)
    try:
        formats, video, container = _probe(path)
        width, height = int(video["width"]), int(video["height"])
    except (subprocess.SubprocessError, StopIteration, KeyError, TypeError, ValueError) as error:
        raise ValueError("This file is not a picture or video Cutroom can read") from error
    if formats & _IMAGE_FORMATS:
        media, duration = "image", None
    elif formats & _VIDEO_FORMATS:
        media = "video"
        try:
            duration = float(container["duration"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("This video has no known length") from error
        if not 0 < duration <= 86400:
            raise ValueError("This video has no usable length")
    else:
        raise ValueError("This file is not a picture or video Cutroom can read")
    if not (0 < width <= 8192 and 0 < height <= 8192):
        raise ValueError("Panel pictures can be at most 8192 pixels on a side")
    if before != file_digest(path):
        raise PermissionError("The panel file changed while it was checked")
    return {"kind": "file", "path": str(path), "name": path.name, "sha256": before, "media": media, "width": width, "height": height, "duration": duration}


def _headline(spec):
    if spec is None:
        return None
    if not isinstance(spec, dict) or set(spec) - {"l1", "l2", "boxed"}:
        raise ValueError("A headline has two lines and boxed words")
    l1 = _text(spec.get("l1"), 60, "Headline line 1")
    l2 = _text(spec.get("l2"), 60, "Headline line 2")
    if not (l1.strip() or l2.strip()):
        return None
    count = len(l2.split())
    boxed = spec.get("boxed", [])
    if not isinstance(boxed, list) or len(boxed) > 8 or any(
        isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < count for i in boxed
    ):
        raise ValueError("Boxed words must be words of headline line 2")
    return {"l1": l1, "l2": l2, "boxed": sorted(set(boxed))}


def normalize_layout(spec, duration):
    """Validated layout settings, or None to go back to the plain frame."""
    if spec is None:
        return None
    if not isinstance(spec, dict) or set(spec) - _KEYS:
        raise ValueError("Unsupported layout settings")
    value = {
        "layout": spec.get("layout", "full"),
        "background": spec.get("background", "paper"),
        "speaker": spec.get("speaker", "wide"),
        "divider": spec.get("divider", DEFAULT_DIVIDER),
        "hold": spec.get("hold", "whole"),
    }
    for key, allowed in (("layout", LAYOUTS), ("background", BACKGROUNDS), ("speaker", SPEAKERS), ("hold", HOLDS)):
        if value[key] not in allowed:
            raise ValueError(f"Unsupported {key}")
    divider = value["divider"]
    if isinstance(divider, bool) or not isinstance(divider, int) or not DIVIDER[0] <= divider <= DIVIDER[1]:
        raise ValueError(f"The divider must be a whole number from {DIVIDER[0]} to {DIVIDER[1]}")
    value["headline"] = _headline(spec.get("headline"))
    value["panel"] = None if spec.get("panel") is None else normalize_item(spec["panel"])
    pictures = spec.get("pictures", [])
    if not isinstance(pictures, list) or len(pictures) > MAX_PICTURES:
        raise ValueError(f"At most {MAX_PICTURES} timed pictures")
    timed = []
    for entry in pictures:
        if not isinstance(entry, dict) or set(entry) - {"start", "end", "said", "item"}:
            raise ValueError("A timed picture has a start, an end and an item")
        start, end = _time(entry.get("start"), duration, "Start"), _time(entry.get("end"), duration, "End")
        if end <= start:
            raise ValueError("A timed picture must end after it starts")
        timed.append({"start": start, "end": end, "said": _text(entry.get("said"), 300, "Words"), "item": normalize_item(entry.get("item"))})
    timed.sort(key=lambda entry: entry["start"])
    for before, after in zip(timed, timed[1:]):
        if after["start"] < before["end"]:
            raise ValueError("Timed pictures cannot overlap")
    value["pictures"] = timed
    return value


def geometry(layout):
    """Boxes in 1080 x 1920 frame pixels for the panel, speaker and captions."""
    if layout.get("layout") == "over":
        return {"panel": {"x": 80, "y": 300, "w": 920, "h": 440}, "speaker": {"x": 0, "y": 0, "w": 1080, "h": 1920}, "radius": 0, "caption_y": 1450, "head_y": None}
    seam = max(DIVIDER[0], min(DIVIDER[1], int(layout.get("divider", DEFAULT_DIVIDER))))
    speaker = layout.get("speaker", "wide")
    if speaker == "small":
        box = {"x": 270, "y": seam + 20, "w": 540, "h": min(440, 1880 - seam - 20)}
    elif speaker == "full":
        box = {"x": 0, "y": seam, "w": 1080, "h": 1920 - seam}
    else:
        box = {"x": 24, "y": seam, "w": 1032, "h": 1920 - seam - 24}
    return {
        "panel": {"x": 56, "y": 500, "w": 968, "h": seam - 190 - 500},
        "speaker": box,
        "radius": 0 if speaker == "full" else 40,
        "caption_y": seam - 20,
        "head_y": 300,
    }


# ---------------------------------------------------------------------------
# Rendering. Everything is drawn in 1080 x 1920 units and scaled to the frame.
# Cards, headline and rounded corners are one ASS script; the speaker and local
# pictures/videos are FFmpeg overlays under it.
# ---------------------------------------------------------------------------

CQH = 19.2  # one percent of the frame height, the unit the Studio preview uses
_KAPPA = 0.5523


def program_times(ranges, start, end):
    """Program intervals (after cuts) covered by the source interval start..end."""
    out, offset = [], 0.0
    for a, b in ranges:
        low, high = max(a, start), min(b, end)
        if high > low:
            out.append((round(offset + low - a, 6), round(offset + high - a, 6)))
        offset += b - a
    return out


def face_centre(samples, ranges=None):
    """Median centre of the largest face over the kept ranges, or None."""
    xs, ys = [], []
    for at, faces in samples or []:
        if ranges and not any(a <= at <= b for a, b in ranges):
            continue
        if faces:
            face = max(faces, key=lambda item: item[2] * item[3])
            xs.append(face[0])
            ys.append(face[1])
    if not xs:
        return None
    xs.sort()
    ys.sort()
    return xs[len(xs) // 2], ys[len(ys) // 2]


def speaker_crop(source_w, source_h, box_w, box_h, face=None, zoom=1.7):
    """Source rectangle shown in the speaker card: zoomed in, face a little above the middle."""
    ratio = source_w / source_h
    width = max(box_w, box_h * ratio) * zoom
    height = width / ratio
    fx, fy = face or (0.5, 0.4)
    left = min(0.0, max(box_w - width, box_w * 0.5 - fx * width))
    top = min(0.0, max(box_h - height, box_h * 0.47 - fy * height))
    scale = source_w / width
    w = min(source_w, round(box_w * scale / 2) * 2)
    h = min(source_h, round(box_h * scale / 2) * 2)
    x = max(0, min(source_w - w, round(-left * scale)))
    y = max(0, min(source_h - h, round(-top * scale)))
    return {"x": x, "y": y, "w": w, "h": h}


def caption_layout(platform_layout, layout, scale):
    """Caption band between the top panel and the speaker card."""
    geo = geometry(layout)
    if platform_layout is None or "captions" not in platform_layout["boxes"]:
        return platform_layout
    panel = geo["panel"]
    safe = platform_layout["safe"]
    # Inside the panel's width and the platform's safe area (buttons sit on the right).
    x0, x1 = max(panel["x"] * scale, safe["x0"]), min((panel["x"] + panel["w"]) * scale, safe["x1"])
    if layout["layout"] == "over":
        y0, y1 = (panel["y"] + panel["h"] + 40) * scale, geo["caption_y"] * scale
    else:
        y0, y1 = (panel["y"] + panel["h"]) * scale, geo["caption_y"] * scale
    band = dict(platform_layout["boxes"]["captions"])
    band.update(x=x0, y=y0, w=x1 - x0, h=y1 - y0)
    band["size"] = min(band["size"], (y1 - y0) / 2.5)
    band["chars_per_line"] = max(1, math.floor((x1 - x0) / band["size"]))
    return {**platform_layout, "safe": dict(x0=x0, y0=y0, x1=x1, y1=y1), "boxes": {**platform_layout["boxes"], "captions": band}}


def _ass_colour(value):
    value = value.lstrip("#")
    alpha = 255 - int(value[6:8], 16) if len(value) == 8 else 0
    return f"&H{alpha:02X}{value[4:6]}{value[2:4]}{value[0:2]}&"


def _ass_time(seconds):
    centis = max(0, round(seconds * 100))
    return f"{centis // 360000}:{centis // 6000 % 60:02d}:{centis // 100 % 60:02d}.{centis % 100:02d}"


def _rounded(x, y, w, h, r):
    r = max(0, min(r, w / 2, h / 2))
    k = r * (1 - _KAPPA)
    p = lambda *values: " ".join(str(round(v)) for v in values)  # noqa: E731
    return (
        f"m {p(x + r, y)} l {p(x + w - r, y)} b {p(x + w - k, y, x + w, y + k, x + w, y + r)} "
        f"l {p(x + w, y + h - r)} b {p(x + w, y + h - k, x + w - k, y + h, x + w - r, y + h)} "
        f"l {p(x + r, y + h)} b {p(x + k, y + h, x, y + h - k, x, y + h - r)} "
        f"l {p(x, y + r)} b {p(x, y + k, x + k, y, x + r, y)}"
    )


def _corners(x, y, w, h, r):
    """Four corner pieces (square minus quarter circle) that round a rectangle off."""
    k = r * _KAPPA
    p = lambda *values: " ".join(str(round(v)) for v in values)  # noqa: E731
    return " ".join(
        [
            f"m {p(x, y)} l {p(x + r, y)} b {p(x + r - k, y, x, y + r - k, x, y + r)}",
            f"m {p(x + w, y)} l {p(x + w, y + r)} b {p(x + w, y + r - k, x + w - r + k, y, x + w - r, y)}",
            f"m {p(x + w, y + h)} l {p(x + w - r, y + h)} b {p(x + w - r + k, y + h, x + w, y + h - r + k, x + w, y + h - r)}",
            f"m {p(x, y + h)} l {p(x, y + h - r)} b {p(x, y + h - r + k, x + r - k, y + h, x + r, y + h)}",
        ]
    )


def _circle(cx, cy, r):
    return _rounded(cx - r, cy - r, 2 * r, 2 * r, r)


class _Script:
    def __init__(self, width, height, font, ink):
        self.s = width / FRAME[0]
        self.width, self.height, self.font, self.ink = width, height, font, ink
        self.lines = []

    def shape(self, spans, path, colour, layer=1):
        tag = f"{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\1c{_ass_colour(colour[:7])}\\1a&H{255 - int(colour[7:9], 16) if len(colour) > 7 else 0:02X}&}}"
        for start, end in spans:
            self.lines.append(f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},Shape,,0,0,0,,{tag}{path}")

    def text(self, spans, x, y, text, size, colour, align=5, style="Text", width=None, layer=2):
        from .captions import literal

        margin = 0
        if width is not None:
            margin = max(0, round((self.width - width * self.s) / 2))
        tag = f"{{\\an{align}\\pos({round(x * self.s)},{round(y * self.s)})\\fs{round(size * self.s)}\\1c{_ass_colour(colour)}}}"
        body = literal(text)
        for start, end in spans:
            self.lines.append(f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style},,{margin},{margin},0,,{tag}{body}")

    def scaled(self, *values):
        return [v * self.s for v in values]

    def render(self, box_pad):
        ink = _ass_colour(PALETTE["paper_ink"])
        box = _ass_colour(PALETTE["box"])
        on_box = _ass_colour(PALETTE["on_box"])
        header = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {self.width}",
            f"PlayResY: {self.height}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Text,{self.font},60,{ink},{ink},{ink},{ink},-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
            f"Style: Box,{self.font},60,{on_box},{on_box},{box},{box},-1,0,0,0,100,100,0,0,3,{round(box_pad * self.s)},0,5,0,0,0,1",
            f"Style: Shape,{self.font},20,{ink},{ink},{ink},{ink},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        return "\n".join(header + self.lines) + "\n"


def _card(script, spans, item, panel, colours):
    """Draw one card into the panel (1080 x 1920 units)."""
    x, y, w, h = panel["x"], panel["y"], panel["w"], panel["h"]
    cx, cy = x + w / 2, y + h / 2
    ink, card = colours["ink"], colours["card"]
    kind, text, detail = item["type"], item["text"], item.get("detail", "")
    radius = 1.4 * CQH
    if kind in ("title", "quote"):
        script.shape(spans, _rounded(*script.scaled(x, y, w, h, radius)), card)
        size = (4.2 if kind == "title" else 3.0) * CQH
        script.text(spans, cx, cy, f"“{text}”" if kind == "quote" else text, size, ink, width=w - 80)
    elif kind == "number":
        script.text(spans, cx, cy - 40, text, 9 * CQH, PALETTE["on_box"], style="Box")
        if detail:
            script.text(spans, cx, cy + 5.5 * CQH, detail, 2.2 * CQH, ink, width=w - 60)
    elif kind == "bars":
        bars = []
        for pair in text.split(","):
            name, _, value = pair.partition(":")
            try:
                number = float(value)
            except ValueError:
                continue
            if math.isfinite(number):
                bars.append((name.strip(), max(0.0, number)))
        bars = bars[:6]
        most = max([1.0] + [value for _, value in bars])
        bar_w, gap, area = 6 * CQH, 2.4 * CQH, 16 * CQH
        total = len(bars) * bar_w + max(0, len(bars) - 1) * gap
        left, base = cx - total / 2, cy + area / 2 - (1.5 * CQH if detail else 0)
        for index, (name, value) in enumerate(bars):
            bh = max(0.04, value / most) * area
            bx = left + index * (bar_w + gap)
            colour = PALETTE["box"] if index == len(bars) - 1 else ink + "40"
            script.shape(spans, _rounded(*script.scaled(bx, base - bh, bar_w, bh, 0.4 * CQH)), colour)
            script.text(spans, bx + bar_w / 2, base + 1.6 * CQH, name, 1.6 * CQH, ink)
        if detail:
            script.text(spans, cx, base + 4.5 * CQH, detail, 2 * CQH, ink, width=w - 60)
    elif kind == "apps":
        names = [name.strip() for name in text.split(",") if name.strip()][:5]
        gap = 3 * CQH
        tile = min(11 * CQH, (w - 40 - (len(names) - 1) * gap) / max(1, len(names)))
        total = len(names) * tile + (len(names) - 1) * gap
        for index, name in enumerate(names):
            tx = cx - total / 2 + index * (tile + gap)
            ty = cy - tile / 2 - 1.5 * CQH
            script.shape(spans, _rounded(*script.scaled(tx, ty, tile, tile, tile * 0.22)), card)
            script.text(spans, tx + tile / 2, ty + tile / 2, name[0].upper(), tile * 0.45, ink)
            script.text(spans, tx + tile / 2, ty + tile + 2.2 * CQH, name, 2 * CQH, ink)
    elif kind == "terminal":
        inset = 1.5 * CQH
        tx, ty, tw, th = x + inset, y + inset, w - 2 * inset, h - 2 * inset
        script.shape(spans, _rounded(*script.scaled(tx, ty, tw, th, 1.2 * CQH)), PALETTE["terminal"])
        for index, colour in enumerate((PALETTE["terminal_red"], PALETTE["terminal_yellow"], PALETTE["terminal_green"])):
            script.shape(spans, _circle(*script.scaled(tx + 2.4 * CQH + index * 1.8 * CQH, ty + 2.4 * CQH, 0.55 * CQH)), colour, layer=2)
        lines = [line.strip() for line in text.split(",") if line.strip()][:6]
        for index, line in enumerate(lines):
            colour = PALETTE["terminal_command"] if index == 0 else PALETTE["terminal_ok"]
            script.text(spans, tx + 2.4 * CQH, ty + 4.6 * CQH + index * 2.9 * CQH, ("$ " if index == 0 else "› ") + line, 1.7 * CQH, colour, align=4)


def _draw_headline(script, spans, headline, measure):
    size = min(84.0, 900 / (max(len(headline["l1"]), len(headline["l2"]), 1) * 0.66))
    top = 300
    if headline["l1"]:
        script.text(spans, 540, top + size * 0.61, headline["l1"], size, script.ink)
    words = headline["l2"].split()
    if not words:
        return
    pad = 0.8 * CQH
    widths = [measure(word, size) for word in words]
    space = size * 0.28
    gaps = [space + (pad if i in headline["boxed"] or i + 1 in headline["boxed"] else 0) for i in range(len(words) - 1)]
    total = sum(widths) + sum(gaps)
    x = 540 - total / 2
    y = top + size * 1.4 + size * 0.61
    for index, word in enumerate(words):
        boxed = index in headline["boxed"]
        script.text(spans, x + widths[index] / 2, y, word, size, PALETTE["on_box"] if boxed else script.ink, style="Box" if boxed else "Text")
        x += widths[index] + (gaps[index] if index < len(gaps) else 0)


def build(layout, *, width, height, ranges, program, font, font_path, source_size, face=None):
    """Everything the renderer needs for a layout.

    Returns the ASS script, the speaker crop/box and the local files to overlay
    with their program intervals and boxes (all in output pixels).
    """
    from .captions import Measurer

    geo = geometry(layout)
    s = width / FRAME[0]
    background = layout["background"] if layout["layout"] == "split" else "paper"
    colours = {
        "paper": PALETTE[f"{background}_paper"],
        "ink": PALETTE[f"{background}_ink"],
        "card": PALETTE["dark_card"] if background == "dark" and layout["layout"] == "split" else PALETTE["card"],
    }
    script = _Script(width, height, font, colours["ink"])
    measure = Measurer(font_path)
    whole = [(0.0, program)]
    # Timed pictures first; the whole-video panel fills the time between them.
    timed = []
    for entry in layout["pictures"]:
        spans = program_times(ranges, entry["start"], entry["end"])
        if spans:
            timed.append((spans, entry["item"]))
    busy = sorted(span for spans, _ in timed for span in spans)
    free, cursor = [], 0.0
    for start, end in busy:
        if start > cursor:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < program:
        free.append((cursor, program))
    shows = ([(free, layout["panel"])] if layout["panel"] else []) + timed
    files = []
    panel = geo["panel"]
    for spans, item in shows:
        if item["kind"] == "card":
            _card(script, spans, item, panel, colours)
        else:
            if file_digest(item["path"]) != item["sha256"]:
                raise ValueError(f"{item['name']} changed since it was chosen; choose it again in Style")
            for start, end in spans:
                files.append({"path": item["path"], "media": item["media"], "start": start, "end": end,
                              "box": {key: round(value * s / 2) * 2 for key, value in panel.items()}})
            script.shape(spans, _corners(*script.scaled(panel["x"], panel["y"], panel["w"], panel["h"], 1.4 * CQH)), colours["paper"], layer=3)
    speaker = geo["speaker"]
    if layout["layout"] == "split" and geo["radius"]:
        script.shape(whole, _corners(*script.scaled(speaker["x"], speaker["y"], speaker["w"], speaker["h"], geo["radius"])), colours["paper"], layer=3)
    if layout["layout"] == "split" and layout["headline"]:
        spans = whole if layout["hold"] == "whole" else [(0.0, min(program, OPENING_SECONDS))]
        _draw_headline(script, spans, layout["headline"], measure)
    box = {key: round(value * s / 2) * 2 for key, value in speaker.items()}
    crop = speaker_crop(*source_size, box["w"], box["h"], face=face, zoom=1.0 if layout["layout"] == "over" else 1.7)
    return {
        "script": script.render(1.0 * CQH),
        "paper": colours["paper"],
        "grid": layout["layout"] == "split" and background == "grid",
        "speaker": {"crop": crop, "box": box},
        "files": files,
        "report": {"layout": layout["layout"], "background": background, "speaker": layout["speaker"], "divider": layout["divider"],
                   "timed_pictures": len(timed), "headline": bool(layout["headline"]), "files": len(files)},
    }


def graph(plan, *, width, height, rate, program, first_input):
    """Filter lines turning [joined] into [laid] and the extra FFmpeg inputs they read."""
    s = width / FRAME[0]
    paper = plan["paper"].lstrip("#")
    lines = [f"color=c=0x{paper}:s={width}x{height}:r={rate}:d={program + 1:.3f}" + (
        f",drawgrid=w={round(3.4 * CQH * s)}:h={round(3.4 * CQH * s)}:t=1:c=black@0.07" if plan["grid"] else "") + "[lbg]"]
    crop, box = plan["speaker"]["crop"], plan["speaker"]["box"]
    lines.append(f"[joined]crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']},scale={box['w']}:{box['h']},setsar=1[lspk]")
    lines.append(f"[lbg][lspk]overlay=x={box['x']}:y={box['y']}:shortest=1[l0]")
    inputs = []
    for index, item in enumerate(plan["files"]):
        stream = first_input + index
        b = item["box"]
        fit = f"scale=w={b['w']}:h={b['h']}:force_original_aspect_ratio=decrease,setsar=1"
        if item["media"] == "image":
            inputs += ["-loop", "1", "-framerate", str(rate), "-t", f"{program + 1:.3f}", "-protocol_whitelist", "file", "-i", item["path"]]
            lines.append(f"[{stream}:v:0]{fit}[lf{index}]")
        else:
            inputs += ["-protocol_whitelist", "file", "-i", item["path"]]
            lines.append(f"[{stream}:v:0]{fit},setpts=PTS-STARTPTS+{item['start']:.3f}/TB[lf{index}]")
        lines.append(
            f"[l{index}][lf{index}]overlay=x={b['x']}+({b['w']}-w)/2:y={b['y']}+({b['h']}-h)/2:"
            f"eof_action=pass:enable='between(t,{item['start']:.3f},{item['end']:.3f})'[l{index + 1}]"
        )
    lines.append(f"[l{len(plan['files'])}]null[laid]")
    return lines, inputs
