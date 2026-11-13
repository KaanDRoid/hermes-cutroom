"""Pacing: punch-ins on edit cuts, slow push-ins, shorter pauses and transitions.

Frames are program frame indices unless a name says otherwise. A "window" is
the picture a zoom works inside: the planned crop for cropped framings, or the
whole decoded frame for `fit` and `blur_fill`. Zooms scale that window about an
anchor point (the speaker's face, else the window centre), so the anchor keeps
its place in the frame while the picture grows around it.
"""

import bisect
import math
from fractions import Fraction
from statistics import median

DEFAULTS = {
    "punch_in": "off",
    "punch_in_zoom": 1.12,
    "max_upscale": 2.0,
    "push_in": False,
    "push_in_zoom": 1.06,
    "max_pause": None,
    "transition": "cut",
    "transition_duration": 0.2,
}
LIMITS = {
    "punch_in_zoom": (1.05, 1.3),
    "max_upscale": (1.0, 4.0),
    "push_in_zoom": (1.02, 1.15),
    "max_pause": (0.2, 2.0),
    "transition_duration": (0.04, 0.5),
}
PUSH_IN_MIN_DURATION = 4.0  # seconds of uninterrupted program
MIN_USEFUL_ZOOM = 1.02  # a reduced zoom below this is skipped, not shown
TRANSITION_FRAMES = (2, 12)
AUDIO_FADE_S = 0.01  # each side of a cut that has a transition
MAX_RANGES = 10000
MAX_FRAMES = 250000
MAX_WORDS = 100000
FACE_SHARE = 0.95


def _number(value, key):
    low, high = LIMITS[key]
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(f"pacing.{key} must be a number from {low:g} to {high:g}")
    return float(value)


def validate_settings(value):
    """Normalised pacing settings with defaults filled in; None means none."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("pacing accepts only " + ", ".join(DEFAULTS))
    result = {**DEFAULTS, **value}
    if result["punch_in"] not in ("off", "alternate"):
        raise ValueError("pacing.punch_in must be off or alternate")
    if result["transition"] not in ("cut", "crossfade", "dip"):
        raise ValueError("pacing.transition must be cut, crossfade or dip")
    if not isinstance(result["push_in"], bool):
        raise ValueError("pacing.push_in must be true or false")
    for key in ("punch_in_zoom", "max_upscale", "push_in_zoom", "transition_duration"):
        result[key] = _number(result[key], key)
    if result["max_pause"] is not None:
        result["max_pause"] = _number(result["max_pause"], "max_pause")
    return result


def video_active(settings):
    """True when pacing changes the picture (max_pause only changes segments)."""
    return bool(settings) and (
        settings["punch_in"] != "off"
        or settings["push_in"]
        or settings["transition"] != "cut"
    )


def zooming(settings):
    return bool(settings) and (settings["punch_in"] != "off" or settings["push_in"])


def transition_frames(duration, fps):
    low, high = TRANSITION_FRAMES
    return min(high, max(low, round(duration * fps)))


def _word_spans(words, segments):
    """Program-time [start, end] of each kept word, fragments of one word merged."""
    spans, offset = {}, 0.0
    for start, end in segments:
        for number, (word_start, word_end) in enumerate(words):
            a, b = max(word_start, start), min(word_end, end)
            if a >= b:
                continue
            program = (offset + a - start, offset + b - start)
            if number in spans:
                spans[number][1] = program[1]
            else:
                spans[number] = [program[0], program[1]]
        offset += end - start
    return sorted(spans.values())


def shorten_pauses(segments, words, max_pause):
    """Shorten pauses between kept words to `max_pause` on the program timeline.

    `words` are the kept (not excluded) transcript words in source time. A
    pause counts program time, so the kept tail of one range plus the kept head
    of the next is one pause. The middle of a longer pause is removed, leaving
    half of `max_pause` after the earlier word and half before the later one.
    Silence before the first and after the last kept word is not a pause
    between words and stays.
    """
    plain = [{"start": s["start"], "end": s["end"]} for s in segments]
    if max_pause is None or not words:
        return plain
    from .speech import remap_words

    spans, last = [], None
    for item in remap_words(words, plain):
        if spans and item["source_id"] == last:
            spans[-1][1] = item["end"]
        else:
            spans.append([item["start"], item["end"]])
            last = item["source_id"]
    spans.sort()
    removals, end = [], None
    for start, stop in spans:
        if end is not None and start - end > max_pause + 1e-9:
            removals.append((end + max_pause / 2, start - max_pause / 2))
        end = stop if end is None else max(end, stop)
    if not removals:
        return plain
    ends = [b for _, b in removals]
    result, offset = [], 0.0
    for segment in plain:
        low = offset
        high = offset + segment["end"] - segment["start"]
        kept, cursor = [], low
        index = bisect.bisect_right(ends, low)
        while index < len(removals) and removals[index][0] < high:
            a, b = removals[index]
            if a > cursor:
                kept.append((cursor, a))
            cursor = max(cursor, b)
            index += 1
        if cursor < high:
            kept.append((cursor, high))
        for a, b in kept:
            start = round(segment["start"] + a - low, 6)
            stop = round(min(segment["end"], segment["start"] + b - low), 6)
            if stop - start > 1e-6 and (not result or start >= result[-1]["end"]):
                result.append({"start": start, "end": stop})
        offset = high
    return result or plain


def _smoothstep(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def zoom_at(item, frame):
    """Zoom of a planned range at its kept frame `frame` (0 = first kept frame)."""
    z0, z1 = item["zoom"]
    if z1 == z0:
        return z0
    return z0 + (z1 - z0) * _smoothstep(frame / max(1, item["frames"] - 1))


def _even(value):
    return max(2, int(round(value / 2)) * 2)


def _fixed_window(window, zoom, anchor, base, limit):
    """Even-sized zoom window scaled about `anchor`, within the upscale limit."""
    cw, ch = window
    zh = min(ch // 2 * 2, _even(ch / zoom))
    zw = min(cw // 2 * 2, _even(zh * cw / ch))
    while base * max(cw / zw, ch / zh) > limit + 1e-9 and zh + 2 <= ch:
        zh += 2
        zw = min(cw // 2 * 2, _even(zh * cw / ch))
    ax, ay = anchor
    # Scale about the anchor, on even pixels (chroma) inside the window.
    ox = min(max(0, int(round(ax * (1 - zw / cw) / 2)) * 2), (cw - zw) // 2 * 2)
    oy = min(max(0, int(round(ay * (1 - zh / ch) / 2)) * 2), (ch - zh) // 2 * 2)
    return [ox, oy, zw, zh]


def plan(
    settings,
    *,
    counts,
    firsts,
    fps,
    last_frame,
    window,
    base_upscale,
    output_box,
    zone,
    faces=(),
):
    """Plan zooms and transitions for kept ranges.

    `counts` are kept frames per range and `firsts` each range's first source
    frame. `faces` are [program frame, x, y] face centres in window pixels.
    `base_upscale` is the framing's own enlargement of the source; every zoom
    keeps base_upscale × zoom at or under `max_upscale`.
    """
    if not counts or len(counts) != len(firsts) or len(counts) > MAX_RANGES:
        raise ValueError("Pacing needs 1 to 10000 kept ranges")
    cw, ch = window
    limit = settings["max_upscale"]
    zmax = limit / base_upscale
    starts, total = [], 0
    for count in counts:
        starts.append(total)
        total += count
    face_list = sorted(list(face) for face in faces)
    face_index = [face[0] for face in face_list]
    ranges, warnings = [], []
    for k, (start, count) in enumerate(zip(starts, counts)):
        punch = settings["punch_in"] == "alternate" and k % 2 == 1
        z0 = settings["punch_in_zoom"] if punch else 1.0
        push = settings["push_in"] and count / fps >= PUSH_IN_MIN_DURATION
        z1 = z0 * settings["push_in_zoom"] if push else z0
        requested = [z0, z1]
        reduced = z1 > zmax + 1e-12
        if reduced:
            z0, z1 = min(z0, zmax), min(z1, zmax)
            if z0 < MIN_USEFUL_ZOOM:
                z0 = 1.0
            if z1 < MIN_USEFUL_ZOOM:
                z1 = 1.0
            if z1 <= 1.0:
                warnings.append(
                    f"Zoom on range {k + 1} skipped: the framing already enlarges "
                    f"the source {base_upscale:.2f}×, at or near the {limit:g}× limit"
                )
            else:
                warnings.append(
                    f"Zoom on range {k + 1} reduced from {requested[1]:.3f}× to "
                    f"{z1:.3f}× to stay within the {limit:g}× enlargement limit"
                )
        low = bisect.bisect_left(face_index, start)
        high = bisect.bisect_left(face_index, start + count)
        inside = face_list[low:high]
        anchor = (
            [median(f[1] for f in inside), median(f[2] for f in inside)]
            if inside
            else [cw / 2, ch / 2]
        )
        anchor = [min(max(anchor[0], 0.0), cw), min(max(anchor[1], 0.0), ch)]
        if z0 == z1 and z0 > 1.0:
            box = _fixed_window((cw, ch), z0, anchor, base_upscale, limit)
            actual = max(cw / box[2], ch / box[3])
            zoom = [actual, actual]
        elif z0 == z1:
            box, zoom = [0, 0, cw, ch], [1.0, 1.0]
        else:
            box, zoom = None, [z0, z1]
        ranges.append(
            {
                "start_frame": start,
                "frames": count,
                "source_first": firsts[k],
                "zoom": zoom,
                "requested_zoom": requested,
                "window": box,
                "anchor": anchor,
                "upscale": base_upscale * max(zoom),
                "reduced": reduced,
            }
        )
    cuts = starts[1:]
    transitions, skipped = [], []
    d = (
        transition_frames(settings["transition_duration"], fps)
        if settings["transition"] != "cut"
        else 0
    )
    used = [0] * len(counts)
    for k in range(len(counts) - 1 if d else 0):
        stop = firsts[k] + counts[k]
        last = k + 1 == len(counts) - 1
        cap_before = min(counts[k] - used[k], firsts[k + 1])
        cap_after = min(
            counts[k + 1] if last else counts[k + 1] // 2, max(0, last_frame - stop)
        )
        after = min(d // 2, cap_after)
        before = min(d - after, cap_before)
        after = min(d - before, cap_after)
        if before + after < TRANSITION_FRAMES[0]:
            skipped.append(
                {"frame": cuts[k], "reason": "a neighbouring range is too short"}
            )
            continue
        used[k + 1] = after
        transitions.append(
            {
                "frame": cuts[k],
                "frames": before + after,
                "before": before,
                "after": after,
            }
        )
    if skipped:
        warnings.append(
            f"{len(skipped)} cut(s) kept a plain cut: a neighbouring range is too short"
        )
    zoomed = {
        index
        for item in ranges
        if max(item["zoom"]) > 1.0
        for index in range(item["start_frame"], item["start_frame"] + item["frames"])
    }
    return {
        "punch_in": settings["punch_in"],
        "push_in": settings["push_in"],
        "transition": settings["transition"],
        "fps": float(fps),
        "frames": total,
        "window": [cw, ch],
        "base_upscale": base_upscale,
        "max_upscale": limit,
        "max_upscale_factor": max(item["upscale"] for item in ranges),
        "output_box": list(output_box),
        "zone": dict(zone),
        "ranges": ranges,
        "cuts": cuts,
        "transition_frames": d,
        "transitions": transitions,
        "skipped_transitions": skipped,
        "face_frames": [face for face in face_list if face[0] in zoomed],
        "audio_fade_s": AUDIO_FADE_S if d else 0.0,
        "warnings": warnings,
    }


def _expression_parts(item, hb):
    """Push-in zoom as an FFmpeg expression in the piece's output frame `on`."""
    z0, z1 = item["zoom"]
    u = f"clip((on-{hb})/{max(1, item['frames'] - 1)},0,1)"
    return f"({z0:.8f}+{z1 - z0:.8f}*{u}*{u}*(3-2*{u}))"


def _perspective(item, window, hb):
    cw, ch = window
    ax, ay = item["anchor"]
    z = _expression_parts(item, hb)
    left, top = f"{ax:.6f}-{ax:.6f}/{z}", f"{ay:.6f}-{ay:.6f}/{z}"
    right, bottom = f"{ax:.6f}+{cw - ax:.6f}/{z}", f"{ay:.6f}+{ch - ay:.6f}/{z}"
    corners = [(left, top), (right, top), (left, bottom), (right, bottom)]
    values = ":".join(f"x{i}='{x}':y{i}='{y}'" for i, (x, y) in enumerate(corners))
    return f"perspective={values}:interpolation=linear:eval=frame"


def build_graph(report, *, rate, origin, out_size, crop=None, prefilters=(), sar="1"):
    """Per-range video chains joined by cuts or transitions into [joined].

    Each range is trimmed with the transition handles it needs, framed (crop
    path first, then the zoom inside the crop window, as one crop where the
    zoom is constant), scaled to `out_size` and given one-frame timestamps. A
    transition overlaps the outgoing range's tail handle with the incoming
    range's head handle, centred on the cut, so every kept frame keeps its
    program position and the program length does not change.
    """
    from . import reframe

    numerator, _, denominator = rate.partition("/")
    num, den = int(numerator), int(denominator or 1)
    fps = Fraction(num, den)
    origin = Fraction(str(float(origin or 0)))
    ranges = report["ranges"]
    by_frame = {t["frame"]: t for t in report["transitions"]}
    lines, lengths, pieces = [], [], [0, 0]

    def edge(frame):
        return round(max(0.0, float(origin + (frame - Fraction(1, 2)) / fps)), 6)

    for k, item in enumerate(ranges):
        start, count = item["start_frame"], item["frames"]
        hb = by_frame.get(start, {}).get("before", 0) if k else 0
        ha = (
            by_frame.get(ranges[k + 1]["start_frame"], {}).get("after", 0)
            if k + 1 < len(ranges)
            else 0
        )
        first = item["source_first"] - hb
        stop = item["source_first"] + count + ha
        chain = [f"trim=start={edge(first)}:end={edge(stop)}", "setpts=PTS-STARTPTS"]
        chain += list(prefilters)
        zoomed = max(item["zoom"]) > 1.0
        box = item["window"]
        if crop is not None:
            expressions = []
            for axis in ("x", "y"):
                values = crop[axis][start : start + count]
                values = [values[0]] * hb + values + [values[-1]] * ha
                resets = [
                    r - start + hb for r in crop["resets"] if start < r < start + count
                ]
                expression, used = reframe.path_expression(values, resets)
                pieces[len(expressions)] += used
                expressions.append(expression)
            x, y = expressions
            cw, ch = crop["size"]
            if zoomed and box is not None:
                chain.append(
                    f"crop={box[2]}:{box[3]}:x='({x})+{box[0]}':y='({y})+{box[1]}'"
                )
            else:
                chain.append(f"crop={cw}:{ch}:x='{x}':y='{y}'")
                if zoomed:
                    chain.append(_perspective(item, (cw, ch), hb))
        elif zoomed and box is not None:
            chain.append(f"crop={box[2]}:{box[3]}:{box[0]}:{box[1]}")
        elif zoomed:
            chain.append(_perspective(item, report["window"], hb))
        if crop is not None or zoomed:
            chain.append(f"scale={out_size[0]}:{out_size[1]}")
        chain += [f"setsar={sar}", f"settb={den}/{num}", "setpts=N"]
        lines.append("[0:v:0]" + ",".join(chain) + f"[p{k}]")
        lengths.append(hb + count + ha)
    if max(pieces) > reframe.MAX_PIECES:
        raise ValueError(
            f"Crop path for {report['frames']} frames needs more than "
            f"{reframe.MAX_PIECES} expression pieces per axis (the limit); split "
            "the edit into shorter renders"
        )
    kind = "fadeblack" if report["transition"] == "dip" else "fade"
    if len(ranges) == 1:
        lines.append("[p0]null[joined]")
    elif not report["transitions"]:
        lines.append(
            "".join(f"[p{k}]" for k in range(len(ranges)))
            + f"concat=n={len(ranges)}:v=1:a=0[joined]"
        )
    else:
        label, total = "[p0]", lengths[0]
        for k in range(1, len(ranges)):
            target = "[joined]" if k == len(ranges) - 1 else f"[x{k}]"
            step = by_frame.get(ranges[k]["start_frame"])
            if step:
                offset = Fraction(total - step["frames"]) / fps
                duration = Fraction(step["frames"]) / fps
                lines.append(
                    f"{label}[p{k}]xfade=transition={kind}:duration="
                    f"{float(duration):.6f}:offset={float(offset):.6f}{target}"
                )
                total += lengths[k] - step["frames"]
            else:
                lines.append(
                    f"{label}[p{k}]concat=n=2:v=1:a=0,settb={den}/{num},setpts=N{target}"
                )
                total += lengths[k]
            label = target
    return lines, pieces


def audio_fades(index, count, samples, sample_rate, report):
    """Short fades on both sides of a cut that has a transition, sample-exact."""
    if not report or not report["transitions"] or samples is None:
        return ""
    frames = {t["frame"] for t in report["transitions"]}
    ranges = report["ranges"]
    length = min(round(report["audio_fade_s"] * sample_rate), samples // 2)
    if length < 1:
        return ""
    result = ""
    if index and ranges[index]["start_frame"] in frames:
        result += f",afade=t=in:start_sample=0:nb_samples={length}"
    if index + 1 < count and ranges[index + 1]["start_frame"] in frames:
        result += f",afade=t=out:start_sample={samples - length}:nb_samples={length}"
    return result


def face_points(analysis_faces, ranges, fps, grid, offsets=None):
    """[program frame, x, y] window-pixel face centres on frames with their own sample.

    `analysis_faces` are Vision samples (time from the first video frame,
    compact face lists); the speaker is chosen as in reframing. `offsets(i)`
    gives the window's top-left corner in grid pixels for program frame `i`.
    """
    from .reframe import _selected_faces

    by_frame = {}
    for timestamp, face in _selected_faces(analysis_faces or []):
        if face:
            by_frame.setdefault(int(round(timestamp * fps)), face)
    result = []
    for item in ranges:
        for j in range(item["frames"]):
            face = by_frame.get(item["source_first"] + j)
            if not face:
                continue
            index = item["start_frame"] + j
            ox, oy = offsets(index) if offsets else (0, 0)
            result.append([index, face[0] * grid[0] - ox, face[1] * grid[1] - oy])
    return result


def validate_report(report):
    def finite(value, low=0.0, high=1e9):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not low <= value <= high
        ):
            raise ValueError("Invalid pacing report value")
        return value

    if not isinstance(report, dict):
        raise ValueError("Invalid pacing report")
    finite(report.get("fps"), 0.001, 1000)
    finite(report.get("base_upscale"), 0.0001, 1000)
    finite(report.get("max_upscale"), 1, 4)
    ranges = report.get("ranges")
    if not isinstance(ranges, list) or not 1 <= len(ranges) <= MAX_RANGES:
        raise ValueError("Invalid pacing ranges")
    window = report.get("window")
    if not isinstance(window, list) or len(window) != 2:
        raise ValueError("Invalid pacing window")
    for value in window:
        finite(value, 1, 100000)
    for item in ranges:
        if not isinstance(item, dict):
            raise ValueError("Invalid pacing range")
        for key in ("start_frame", "frames"):
            finite(item.get(key), 0, MAX_FRAMES)
        zoom = item.get("zoom")
        if not isinstance(zoom, list) or len(zoom) != 2:
            raise ValueError("Invalid pacing zoom")
        for value in zoom:
            finite(value, 1, 10)
        box = item.get("window")
        if box is not None:
            if not isinstance(box, list) or len(box) != 4:
                raise ValueError("Invalid pacing zoom window")
            for value in box:
                finite(value, 0, 100000)
            if box[2] < 1 or box[3] < 1:
                raise ValueError("Invalid pacing zoom window")
        anchor = item.get("anchor")
        if not isinstance(anchor, list) or len(anchor) != 2:
            raise ValueError("Invalid pacing anchor")
        for value in anchor:
            finite(value, 0, 100000)
    for key, size, limit in (
        ("face_frames", 3, MAX_FRAMES),
        ("transitions", None, MAX_RANGES),
        ("cuts", None, MAX_RANGES),
    ):
        values = report.get(key)
        if not isinstance(values, list) or len(values) > limit:
            raise ValueError("Invalid pacing evidence")
        for value in values:
            if size is not None:
                if not isinstance(value, list) or len(value) != size:
                    raise ValueError("Invalid pacing face evidence")
                for number in value:
                    finite(number, -100000, 100000)
    for item in report["transitions"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid pacing transition")
        for key in ("frame", "frames", "before", "after"):
            finite(item.get(key), 0, MAX_FRAMES)
    box = report.get("output_box")
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("Invalid pacing output box")
    for value in box:
        finite(value, 0, 1)
    zone = report.get("zone")
    if not isinstance(zone, dict) or set(zone) != {"left", "right", "top", "bottom"}:
        raise ValueError("Invalid pacing safe zone")
    for value in zone.values():
        finite(value, 0, 0.49)
    sources = report.get("source_ranges")
    if sources is not None:
        if not isinstance(sources, list) or len(sources) > MAX_RANGES:
            raise ValueError("Invalid pacing source ranges")
        for pair in sources:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("Invalid pacing source ranges")
            finite(pair[0], 0, 86400 * 30)
            finite(pair[1], 0, 86400 * 30)
    return report


def _zoom_box(report, item, frame):
    """(ox, oy, w, h) of the zoom window at program frame `frame` of `item`."""
    if item["window"] is not None:
        return item["window"]
    cw, ch = report["window"]
    z = zoom_at(item, frame - item["start_frame"])
    ax, ay = item["anchor"]
    return [ax - ax / z, ay - ay / z, cw / z, ch / z]


def quality_checks(add, report, settings, words=None):
    """pacing_upscale, pacing_face, pacing_transitions and pacing_max_pause."""
    if report is None:
        add(
            "pacing_upscale",
            "warning",
            {"reason": "render without a pacing report; pacing not checked"},
        )
        return
    validate_report(report)
    ranges = report["ranges"]
    starts = [item["start_frame"] for item in ranges]
    base, limit = report["base_upscale"], report["max_upscale"]
    cw, ch = report["window"]
    if zooming(settings):
        worst, over, zoomed = 0.0, [], 0
        for item in ranges:
            box = item["window"]
            zoom = max(cw / box[2], ch / box[3]) if box else max(item["zoom"])
            if zoom <= 1 + 1e-9:
                continue
            zoomed += 1
            factor = base * zoom
            worst = max(worst, factor)
            if factor > limit + 1e-6:
                over.append(item["start_frame"])
        status = "fail" if over else "pass"
        detail = {
            "max_upscale_factor": worst or base,
            "limit": limit,
            "framing_upscale": base,
            "zoomed_ranges": zoomed,
            "reduced_ranges": [
                item["start_frame"] for item in ranges if item.get("reduced")
            ],
            "ranges_over_limit": over,
            "method": "planned zoom windows times the framing's own enlargement",
        }
        if not zoomed and base * MIN_USEFUL_ZOOM > limit:
            status = "warning"
            detail["reason"] = (
                "The framing alone enlarges the source close to or beyond the "
                "limit, so no zoom was applied"
            )
        add("pacing_upscale", status, detail)
        zone, (bx, by, bw, bh) = report["zone"], report["output_box"]
        inside = total = 0
        misses = []
        for index, wx, wy in report["face_frames"]:
            k = bisect.bisect_right(starts, index) - 1
            if k < 0 or index >= starts[k] + ranges[k]["frames"]:
                continue
            item = ranges[k]
            if max(item["zoom"]) <= 1.0:
                continue
            ox, oy, w, h = _zoom_box(report, item, index)
            nx, ny = (wx - ox) / w, (wy - oy) / h
            x, y = bx + nx * bw, by + ny * bh
            total += 1
            ok = (
                0 <= nx <= 1
                and 0 <= ny <= 1
                and zone["left"] <= x <= 1 - zone["right"]
                and zone["top"] <= y <= 1 - zone["bottom"]
            )
            inside += ok
            if not ok and len(misses) < 20:
                misses.append(index)
        share = inside / total if total else None
        add(
            "pacing_face",
            "skip" if not total else "pass" if share >= FACE_SHARE else "fail",
            {
                "inside_fraction": share,
                "required_fraction": FACE_SHARE,
                "sampled_face_frames": total,
                "inside": inside,
                "first_misses": misses,
                "method": "zoomed frames with their own face sample; the selected "
                "face centre is projected through the planned zoom window into "
                "the safe area, not redetected on the output",
                **({} if total else {"reason": "No face sample on a zoomed frame"}),
            },
        )
    if settings["transition"] != "cut":
        cuts = set(report["cuts"])
        placed = [
            t
            for t in report["transitions"]
            if t["frame"] in cuts
            and TRANSITION_FRAMES[0] <= t["frames"] <= TRANSITION_FRAMES[1]
            and t["before"] + t["after"] == t["frames"]
        ]
        skipped = report.get("skipped_transitions") or []
        status = (
            "pass"
            if len(placed) == len(cuts)
            else "warning"
            if len(placed) + len(skipped) == len(cuts)
            else "fail"
        )
        add(
            "pacing_transitions",
            status,
            {
                "transition": settings["transition"],
                "cuts": len(cuts),
                "placed": len(placed),
                "skipped": skipped,
                "frames": report.get("transition_frames"),
                "program_length": "unchanged; transitions use handles centred on "
                "each cut",
            },
        )
    if settings.get("max_pause") is not None:
        sources = report.get("source_ranges")
        if not words or not sources:
            add(
                "pacing_max_pause",
                "skip",
                {"reason": "No kept words or rendered ranges to measure"},
            )
            return
        if len(words) > MAX_WORDS:
            raise ValueError("Too many words for the pause check")
        spans = _word_spans([tuple(w) for w in words], [tuple(r) for r in sources])
        pauses = [(a[1], b[0] - a[1]) for a, b in zip(spans, spans[1:]) if b[0] > a[1]]
        allowed = settings["max_pause"] + 1 / report["fps"] + 1e-6
        longest = max((length for _, length in pauses), default=0.0)
        over = [
            [round(t, 6), round(length, 6)] for t, length in pauses if length > allowed
        ]
        add(
            "pacing_max_pause",
            "pass" if not over else "fail",
            {
                "max_pause_s": settings["max_pause"],
                "allowed_s": allowed,
                "longest_pause_s": longest,
                "pauses_over": over[:20],
                "words": len(spans),
                "method": "kept word times mapped through the rendered frame-aligned "
                "ranges; one frame of rounding allowed",
            },
        )
