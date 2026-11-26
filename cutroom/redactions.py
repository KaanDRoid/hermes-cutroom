"""Bleeps, mutes and hidden areas.

Both work on the source streams in source seconds, before any cut: the render
replaces every read of the source video/audio with a redacted copy, so cuts,
variable frame rates, punch-ins, music mixes and layouts all see the same
redacted picture and sound.
"""

import math

from .layouts import PALETTE

MAX_BLEEPS = 200
MAX_HIDDEN = 50
MAX_FOLLOWED = 10  # Each followed box decodes its own stretch of the source.
FOLLOW_SECONDS = 30.0
FOLLOW_MARGIN = 0.08  # A followed box covers this much more on every side (positions are estimates).
MODES = ("bleep", "mute")
STYLES = ("cover", "blur", "pixelate")
TONE_HZ = 1000
TONE_LEVEL = 0.18
# Extra time on each side so a frame or a few audio samples cannot slip through.
AUDIO_PAD = 0.02
VIDEO_PAD_FRAMES = 2
MASK = "—"
# The solid box uses the same colour as the Studio preview.
COVER = PALETTE["cover"].lstrip("#")


def _seconds(value, duration, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a number of seconds")
    if not 0 <= value <= duration:
        raise ValueError(f"{name} must be inside the source")
    return float(value)


def _span(entry, duration):
    start, end = _seconds(entry.get("start"), duration, "Start"), _seconds(entry.get("end"), duration, "End")
    if end <= start:
        raise ValueError("A range must end after it starts")
    return start, end


def _said(value):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 300 or any(ord(c) < 32 for c in value):
        raise ValueError("Words must be one line of at most 300 characters")
    return value


def _fraction(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return float(value)


def normalize(spec, duration):
    """Validated bleeps and hidden areas, or None when there are none."""
    if spec is None:
        return None
    if not isinstance(spec, dict) or set(spec) - {"bleeps", "hidden"}:
        raise ValueError("Redactions have bleeps and hidden areas only")
    bleeps, hidden = spec.get("bleeps", []), spec.get("hidden", [])
    if not isinstance(bleeps, list) or len(bleeps) > MAX_BLEEPS:
        raise ValueError(f"At most {MAX_BLEEPS} bleeps")
    if not isinstance(hidden, list) or len(hidden) > MAX_HIDDEN:
        raise ValueError(f"At most {MAX_HIDDEN} hidden areas")
    out_bleeps = []
    for entry in bleeps:
        if not isinstance(entry, dict) or set(entry) - {"start", "end", "mode", "said", "ids"}:
            raise ValueError("A bleep has a start, an end, a mode and words")
        start, end = _span(entry, duration)
        mode = entry.get("mode", "bleep")
        if mode not in MODES:
            raise ValueError("A bleep is a bleep or a mute")
        ids = entry.get("ids", [])
        if not isinstance(ids, list) or len(ids) > 50 or any(isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in ids):
            raise ValueError("Bleep word ids are transcript word numbers")
        out_bleeps.append({"start": start, "end": end, "mode": mode, "said": _said(entry.get("said")), "ids": list(ids)})
    out_hidden = []
    for entry in hidden:
        if not isinstance(entry, dict) or set(entry) - {"start", "end", "said", "box", "style", "follow", "at"}:
            raise ValueError("A hidden area has a start, an end, a box, a style, when it was drawn and whether it follows")
        start, end = _span(entry, duration)
        box = entry.get("box")
        if not isinstance(box, dict) or set(box) != {"x", "y", "w", "h"}:
            raise ValueError("A hidden area needs a box with x, y, w and h")
        x, y, w, h = (_fraction(box[key], key) for key in ("x", "y", "w", "h"))
        if w < 0.01 or h < 0.01 or x + w > 1.0001 or y + h > 1.0001:
            raise ValueError("A hidden area must be inside the picture and at least 1% wide and tall")
        style = entry.get("style", "cover")
        if style not in STYLES:
            raise ValueError("A hidden area is a solid box, blur or pixelate")
        follow = entry.get("follow", False)
        if not isinstance(follow, bool):
            raise ValueError("A hidden area follows what is inside it or stays put (true or false)")
        item = {"start": start, "end": end, "said": _said(entry.get("said")), "box": {"x": x, "y": y, "w": min(w, 1 - x), "h": min(h, 1 - y)}, "style": style}
        if follow:
            item["follow"] = True  # Only when asked, so saved projects keep their shape.
            if end - start > FOLLOW_SECONDS + 1e-6:
                raise ValueError(f"Follow movement works on up to {FOLLOW_SECONDS:g} seconds at a time; split the range")
        if "at" in entry:
            drawn = entry["at"]
            if isinstance(drawn, bool) or not isinstance(drawn, (int, float)) or not math.isfinite(drawn):
                raise ValueError("A hidden area's drawing time is a number of seconds")
            item["at"] = min(max(float(drawn), start), end)  # The frame the box was drawn on.
        out_hidden.append(item)
    if sum(1 for item in out_hidden if item.get("follow")) > MAX_FOLLOWED:
        raise ValueError(f"Follow movement works on up to {MAX_FOLLOWED} hidden areas per video")
    if not out_bleeps and not out_hidden:
        return None
    return {"bleeps": sorted(out_bleeps, key=lambda b: b["start"]), "hidden": sorted(out_hidden, key=lambda b: b["start"])}


def mask_words(words, spec):
    """Words with bleeped or muted ones replaced, for captions and subtitle files."""
    if not spec or not spec.get("bleeps"):
        return list(words)
    ids = {i for b in spec["bleeps"] for i in b["ids"]}
    spans = [(b["start"], b["end"]) for b in spec["bleeps"]]
    out = []
    for word in words:
        middle = (word["start"] + word["end"]) / 2
        hit = word.get("id") in ids or any(a <= middle <= b for a, b in spans)
        out.append({**word, "text": MASK} if hit else word)
    return out


def _between(spans):
    return "+".join(f"between(t,{a:.4f},{b:.4f})" for a, b in spans) or "0"


def _merged(spans):
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def audio_filter(spec, channels):
    """One aeval filter: silence in every range, plus a tone in bleeped ones."""
    bleeps = spec.get("bleeps") if spec else None
    if not bleeps:
        return None
    pad = lambda b: (max(0.0, b["start"] - AUDIO_PAD), b["end"] + AUDIO_PAD)  # noqa: E731
    silent = _between(_merged([pad(b) for b in bleeps]))
    tone = _between(_merged([pad(b) for b in bleeps if b["mode"] == "bleep"]))
    channel = f"val(CH)*(1-gt({silent},0))+{TONE_LEVEL}*sin(2*PI*{TONE_HZ}*t)*gt({tone},0)"
    exprs = "|".join(channel.replace("CH", str(index)) for index in range(max(1, channels)))
    return f"aeval=exprs='{exprs}':c=same"


def _simplify(times, values, tolerance):
    """Indices of a polyline through (times, values) within ``tolerance`` of every sample."""
    keep, stack = {0, len(values) - 1}, [(0, len(values) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        span = times[b] - times[a] or 1e-9
        worst, at = max((abs(values[i] - (values[a] + (values[b] - values[a]) * (times[i] - times[a]) / span)), i) for i in range(a + 1, b))
        if worst > tolerance:
            keep.add(at)
            stack.extend(((a, at), (at, b)))
    return sorted(keep)


def time_expression(times, values, tolerance=0.5):
    """FFmpeg expression in t following the samples (straight lines between kept points).

    The pieces are nested as a balanced tree, so long paths stay shallow for the parser.
    """
    if not values:
        raise ValueError("A path needs at least one sample")
    points = [(times[i], values[i]) for i in _simplify(times, values, tolerance)]
    if len(points) == 1:
        return f"{points[0][1]:.2f}"
    pieces = []
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        slope = (v1 - v0) / ((t1 - t0) or 1e-9)
        pieces.append((t1, f"({v0:.2f}+({slope:.4f})*(t-{t0:.4f}))"))
    pieces[-1] = (math.inf, f"if(lt(t,{points[-1][0]:.4f}),{pieces[-1][1]},{points[-1][1]:.2f})")
    first = f"{points[0][1]:.2f}"

    def tree(lo, hi):
        if lo == hi:
            return pieces[lo][1]
        mid = (lo + hi) // 2
        return f"if(lt(t,{pieces[mid][0]:.4f}),{tree(lo, mid)},{tree(mid + 1, hi)})"

    return f"if(lt(t,{points[0][0]:.4f}),{first},{tree(0, len(pieces) - 1)})"


def video_chain(spec, width, height, frame_rate, paths=None):
    """Filter-graph pieces turning [vin] into [vout] with every hidden area applied.

    ``paths`` maps a hidden area's index to its followed path (see tracking.follow_box).
    """
    hidden = spec.get("hidden") if spec else None
    if not hidden:
        return None
    pad = VIDEO_PAD_FRAMES / (frame_rate or 30)
    lines, current = [], "[vin]"
    for index, item in enumerate(hidden):
        box = item["box"]
        x = max(0, math.floor(box["x"] * width / 2) * 2)
        y = max(0, math.floor(box["y"] * height / 2) * 2)
        w = min(width - x, math.ceil(box["w"] * width / 2) * 2 + 2)
        h = min(height - y, math.ceil(box["h"] * height / 2) * 2 + 2)
        path = (paths or {}).get(index)
        if path:
            # A followed box is a little larger than drawn, and kept inside the frame.
            mx, my = math.ceil(w * FOLLOW_MARGIN / 2) * 2, math.ceil(h * FOLLOW_MARGIN / 2) * 2
            w, h = min(width, w + 2 * mx), min(height, h + 2 * my)
            xs = [min(width - w, max(0.0, value * width - mx - 1)) for value in path["x"]]
            ys = [min(height - h, max(0.0, value * height - my - 1)) for value in path["y"]]
            x, y = f"'{time_expression(path['times'], xs)}'", f"'{time_expression(path['times'], ys)}'"
        when = f"between(t,{max(0.0, item['start'] - pad):.4f},{item['end'] + pad:.4f})"
        nxt = "[vout]" if index == len(hidden) - 1 else f"[vh{index}]"
        lost = path["lost"] if path else []
        if lost:
            blocked = "+".join(f"between(t,{max(0, a - pad):.4f},{b + pad:.4f})" for a, b in lost)
            covered = f"[hl{index}]"
            lines.append(f"{current}drawbox=color=0x{COVER}:t=fill:enable='{blocked}'{covered}")
            current = covered
        if item["style"] == "cover" and not path:
            lines.append(f"{current}drawbox=x={x}:y={y}:w={w}:h={h}:color=0x{COVER}:t=fill:enable='{when}'{nxt}")
        else:
            look = (
                f"boxblur=luma_radius={max(4, min(w, h) // 4)}:luma_power=3:chroma_radius={max(2, min(w, h) // 8)}:chroma_power=3"
                if item["style"] == "blur"
                # drawbox places its box once, so a followed solid box is a filled moving overlay.
                else f"drawbox=color=0x{COVER}:t=fill"
                if item["style"] == "cover"
                else f"scale={max(1, w // 24)}:{max(1, h // 24)}:flags=area,scale={w}:{h}:flags=neighbor"
            )
            lines.append(f"{current}split=2[hb{index}][hs{index}]")
            lines.append(f"[hs{index}]crop={w}:{h}:{x}:{y},{look}[hp{index}]")
            lines.append(f"[hb{index}][hp{index}]overlay=x={x}:y={y}:enable='{when}'{nxt}")
        current = nxt
    return lines


def redirect(lines, stream, chain, prefix):
    """Point every read of ``stream`` (e.g. [0:v:0]) at a redacted copy.

    ``chain`` is either a filter string or graph lines from [vin] to [vout].
    Returns the rewritten lines; a filter output can be read once, so the
    redacted copy is split for every reader.
    """
    readers = sum(line.count(stream) for line in lines if line)
    if not readers:
        return lines
    labels = [f"[{prefix}{index}]" for index in range(readers)]
    counter = iter(labels)
    out = []
    for line in lines:
        if not line:
            out.append(line)
            continue
        while stream in line:
            line = line.replace(stream, next(counter), 1)
        out.append(line)
    fan = f"split={readers}" if stream.endswith(":v:0]") else f"asplit={readers}"
    if isinstance(chain, str):
        out.append(f"{stream}{chain},{fan}{''.join(labels)}")
    else:
        out.extend(piece.replace("[vin]", stream, 1).replace("[vout]", f"[{prefix}x]") for piece in chain)
        out.append(f"[{prefix}x]{fan}{''.join(labels)}")
    return out
