"""Bounded, deterministic crop planning; coordinates are display-source pixels."""

import bisect
import math
import re
import subprocess
import tempfile
from pathlib import Path

MODES = ("fit", "blur_fill", "center_crop", "face_track")
TRACKING = {"dead_zone": 0.035, "max_speed": 1.2, "max_acceleration": 2.5, "tau": 0.18}
MAX_FRAMES = 250000
MAX_SAMPLES = 100000
# Each axis's crop expression is a balanced if() tree of at most this many
# linear pieces; FFmpeg parses it once, but the filter script grows with it.
MAX_PIECES = 20000
# Below this share of program frames with a usable face, face_track warns.
MIN_FACE_COVERAGE = 0.5


def number(value, low=0, high=86400):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError("Framing values must be finite numbers in range")
    return float(value)


def validate_framing(mode):
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("framing must be fit, blur_fill, center_crop or face_track")
    return mode


def validate_keyframes(keys, duration=86400):
    if not isinstance(keys, list) or len(keys) > 100:
        raise ValueError("framing_keyframes must be a list of at most 100 entries")
    result, previous = [], -1
    for key in keys:
        if (
            not isinstance(key, dict)
            or set(key) - {"time", "x", "y"}
            or not {"time", "x"} <= set(key)
        ):
            raise ValueError("Each framing keyframe needs time, x and optional y")
        time = number(key["time"])
        if time > duration:
            raise ValueError(
                f"Framing keyframe at {time:g} s is past the end of the "
                f"{duration:g} s program; remove it or move it earlier"
            )
        item = {"time": time, "x": number(key["x"], high=1)}
        if "y" in key:
            item["y"] = number(key["y"], high=1)
        if item["time"] <= previous:
            raise ValueError("Framing keyframe times must be strictly increasing")
        previous = item["time"]
        result.append(item)
    return result


def validate_analysis(analysis):
    if not isinstance(analysis, dict) or set(analysis) != {"faces", "scene_cuts"}:
        raise ValueError(
            "Framing analysis needs faces and scene_cuts; run Vision again"
        )
    faces, cuts = analysis["faces"], analysis["scene_cuts"]
    if not isinstance(faces, list) or len(faces) > MAX_SAMPLES:
        raise ValueError("Framing face samples exceed the bounded list limit")
    previous = -1
    for sample in faces:
        if not isinstance(sample, list) or len(sample) != 2:
            raise ValueError("Invalid framing face sample")
        timestamp, entries = sample
        timestamp = number(timestamp)
        if timestamp <= previous or not isinstance(entries, list) or len(entries) > 4:
            raise ValueError("Face samples must be ordered with at most four faces")
        previous = timestamp
        for entry in entries:
            if not isinstance(entry, list) or len(entry) != 6:
                raise ValueError("Invalid compact face geometry")
            for value in entry[:5]:
                number(value, high=1)
            if entry[5] is not None:
                number(entry[5], high=10)
    if cuts is not None:
        if not isinstance(cuts, list) or len(cuts) > MAX_SAMPLES:
            raise ValueError("Invalid scene-cut list")
        previous = -1
        for cut in cuts:
            value = number(cut)
            if value <= previous:
                raise ValueError("Scene cuts must be strictly ordered")
            previous = value
    return analysis


def face_samples(frames):
    samples = []
    for frame in frames:
        entries = []
        for face in frame.get("faces", []):
            box = face.get("box")
            if not box:
                continue
            x0, y0, x1, y1 = [max(0, min(1, v)) for v in box]
            if x1 <= x0 or y1 <= y0:
                continue
            entries.append(
                [
                    round((x0 + x1) / 2, 6),
                    round((y0 + y1) / 2, 6),
                    round(x1 - x0, 6),
                    round(y1 - y0, 6),
                    round(
                        max(0, min(1, face.get("eye_y") or (y0 + (y1 - y0) * 0.35))), 6
                    ),
                    face.get("mouth_open"),
                ]
            )
        samples.append([round(frame["time"], 6), entries])
    validate_analysis({"faces": samples, "scene_cuts": []})
    return samples


def scene_cuts(source):
    """Full decode at 160 px wide; scdet >=10 percent. Failure is explicit None."""
    from .postproduction import _run

    try:
        with tempfile.TemporaryDirectory(prefix=".reframe-cuts-") as temp:
            directory = Path(temp)
            _run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file",
                    "-i",
                    str(source),
                    "-an",
                    "-vf",
                    "scale=160:-2,scdet=threshold=10:sc_pass=1,metadata=mode=print:file=cuts.txt",
                    "-f",
                    "null",
                    "-",
                ],
                cwd=directory,
                timeout=300,
            )
            text = (directory / "cuts.txt").read_text(encoding="utf-8")
            return sorted(
                set(float(v) for v in re.findall(r"lavfi.scd.time=([\d.]+)", text))
            )
    except (OSError, subprocess.SubprocessError):
        return None


def crop_size(sw, sh, ow, oh):
    """Even crop nearest the target aspect; odd sources lose at most one pixel row/column."""
    ew, eh = max(2, sw // 2 * 2), max(2, sh // 2 * 2)
    if sw / sh > ow / oh:
        return min(ew, max(2, round(sh * ow / oh / 2) * 2)), eh
    return ew, min(eh, max(2, round(sw * oh / ow / 2) * 2))


def content_upscale(source, width, height, mode):
    from .postproduction import _content_upscale

    if mode not in {"center_crop", "face_track"}:
        return _content_upscale(source, width, height)
    cw, ch = crop_size(source["width"], source["height"], width, height)
    return [width, height], max(width / cw, height / ch)


def _clip(value, low, high):
    return max(low, min(high, value))


def _selected_faces(samples):
    """Largest area weighted by mouth opening change; geometric speaker heuristic."""
    previous = []
    result = []
    for timestamp, faces in samples:
        ranked = []
        for face in faces:
            nearest = min(
                previous, key=lambda p: math.dist(p[:2], face[:2]), default=None
            )
            activity = (
                0
                if face[5] is None or nearest is None or nearest[5] is None
                else min(1, abs(face[5] - nearest[5]) * 4)
            )
            score = face[2] * face[3] * (1 + 2 * activity)
            ranked.append((score, face))
        result.append(
            [timestamp, max(ranked, key=lambda p: p[0])[1] if ranked else None]
        )
        previous = faces
    return result


def _motion(targets, resets, scale, frames):
    """Exponential target smoothing with speed, acceleration and braking bounds."""
    result, velocity, position = [], 0.0, targets[0]
    for index, target in enumerate(targets):
        if index == 0 or index in resets:
            position, velocity = target, 0.0
        else:
            dt = max(1e-6, frames[index] - frames[index - 1])
            offset = target - position
            desired = offset * (1 - math.exp(-dt / TRACKING["tau"])) / dt
            if abs(offset) < TRACKING["dead_zone"] * scale and abs(velocity) < 1e-6:
                desired = 0
            braking = math.sqrt(2 * TRACKING["max_acceleration"] * scale * abs(offset))
            desired = _clip(
                desired,
                -min(TRACKING["max_speed"] * scale, braking),
                min(TRACKING["max_speed"] * scale, braking),
            )
            acceleration = TRACKING["max_acceleration"] * scale * dt
            velocity = _clip(desired, velocity - acceleration, velocity + acceleration)
            position += velocity * dt
        result.append(position)
    return result


def _smoothstep(u):
    return u * u * (3 - 2 * u)


def _manual(values, keys, axis, source, crop, frames, mode, ramp=1.0):
    """Apply pins; returns the path and each frame's pin weight (0 = tracker only).

    Between pins the crop eases (smoothstep). Before the first and after the
    last pin, center_crop holds the pin; face_track follows the tracked path and
    blends into and out of the pin over a ramp sized for the motion limits.
    """
    selected = [key for key in keys if axis in key]
    if not selected:
        return values, [0.0] * len(values)
    anchors = [
        (key["time"], _clip(key[axis] * source - crop / 2, 0, source - crop))
        for key in selected
    ]
    times = [p[0] for p in anchors]

    def ramp_time(time, value):
        tracked = values[min(len(frames) - 1, bisect.bisect_left(frames, time))]
        distance = abs(value - tracked)
        # Smoothstep peaks at 1.5x mean speed and 6x distance/T^2 acceleration.
        return ramp * max(
            0.25,
            1.5 * distance / (TRACKING["max_speed"] * crop),
            math.sqrt(6 * distance / (TRACKING["max_acceleration"] * crop)),
        )

    ramps = (ramp_time(*anchors[0]), ramp_time(*anchors[-1]))
    result, weights = [], []
    for i, timestamp in enumerate(frames):
        index = bisect.bisect_right(times, timestamp)
        if 0 < index < len(anchors):
            ta, a = anchors[index - 1]
            tb, b = anchors[index]
            value, weight = a + (b - a) * _smoothstep((timestamp - ta) / (tb - ta)), 1
        elif mode != "face_track":
            value, weight = anchors[0 if index == 0 else -1][1], 1
        else:
            ta, a = anchors[0] if index == 0 else anchors[-1]
            u = 1 - abs(timestamp - ta) / ramps[0 if index == 0 else 1]
            weight = _smoothstep(u) if u > 0 else 0.0
            value = values[i] + (a - values[i]) * weight
        result.append(value)
        weights.append(weight)
    return result, weights


def _pin_error(values, weights, scale, frames, resets):
    """Speed/acceleration breach of a pinned path, or None.

    A reset frame (edit or scene cut) may jump; when it does not, velocity
    carries across it, so a smooth pan over a cut is not a stop and restart.
    Frames driven only by the tracker are bounded by construction.
    """
    velocity = None
    top = TRACKING["max_speed"] * scale
    for i in range(1, len(values)):
        dt = max(1e-6, frames[i] - frames[i - 1])
        speed = (values[i] - values[i - 1]) / dt
        if i in resets:
            velocity = None if abs(speed) > top + 1e-5 else speed
            continue
        if not max(weights[max(0, i - 2) : i + 1]):
            velocity = speed
            continue
        if abs(speed) > top + 1e-5:
            return "Framing keyframes exceed pan speed; space them further apart"
        if (
            velocity is not None
            and abs(speed - velocity) / dt > TRACKING["max_acceleration"] * scale + 1e-4
        ):
            return "Framing keyframes exceed pan acceleration; space them further apart"
        velocity = speed
    return None


def plan_path(
    *,
    mode,
    source_size,
    crop_size,
    frame_size,
    frames,
    fps,
    faces=(),
    scene_cuts=(),
    edit_resets=(),
    zone=None,
    keyframes=(),
    sample_interval=None,
):
    """Plan the crop path in program frames.

    `faces` are Vision samples in program time; only samples inside the
    current shot (between resets) are used. At a reset the crop starts at the
    first sample of the new shot (look-ahead) and stays centred until a sample
    exists. A face frame is "fresh" when its sample is at most one sampling
    interval plus one frame away; older held faces are "stale".
    """
    validate_framing(mode)
    if not frames or len(frames) > MAX_FRAMES:
        raise ValueError(
            "Reframing requires 1 to 250000 output frames; split longer edits"
        )
    count = len(frames)
    sw, sh = source_size
    cw, ch = crop_size
    zone = zone or {"left": 0.05, "right": 0.05, "top": 0.05, "bottom": 0.05}
    selected = _selected_faces(faces) if mode == "face_track" else []
    sample_times = [sample[0] for sample in selected]
    resets = set(edit_resets) | {0}
    for cut in scene_cuts or []:
        index = bisect.bisect_left(frames, cut - 0.000001)
        if index < count:
            resets.add(index)
    resets = {index for index in resets if 0 <= index < count}
    if sample_interval is None:
        gaps = sorted(b - a for a, b in zip(sample_times, sample_times[1:]))
        sample_interval = gaps[len(gaps) // 2] if gaps else 1 / fps
    max_age = sample_interval + 1 / fps + 1e-6
    bounds = sorted(resets) + [count]
    targets_x, targets_y, face_frames = [], [], []
    stale = uncovered = 0
    for start, stop in zip(bounds, bounds[1:]):
        # Samples of this shot only: never the previous shot or removed content.
        low = bisect.bisect_left(sample_times, frames[start] - 0.000001)
        high = (
            bisect.bisect_left(sample_times, frames[stop] - 0.000001)
            if stop < count
            else len(sample_times)
        )
        x, y = (sw - cw) / 2, (sh - ch) / 2
        for index in range(start, stop):
            timestamp = frames[index]
            j = bisect.bisect_right(sample_times, timestamp + 0.000001) - 1
            if j < low:
                j = low if low < high else None
            face = selected[j][1] if j is not None else None
            if face:
                fx, fy, _, _, eye, _ = face
                fx, fy = fx * sw, fy * sh
                x = _clip(fx - cw * (zone["left"] + 1 - zone["right"]) / 2, 0, sw - cw)
                y = _clip(
                    eye * sh
                    - ch * (zone["top"] + (1 - zone["top"] - zone["bottom"]) / 3),
                    0,
                    sh - ch,
                )
                # Keep the centre within the safe area when physical crop limits permit it.
                y = _clip(
                    y,
                    max(0, fy - ch * (1 - zone["bottom"])),
                    min(sh - ch, max(0, fy - ch * zone["top"])),
                )
                if abs(timestamp - sample_times[j]) <= max_age:
                    face_frames.append([index, fx, fy])
                else:
                    stale += 1
            else:
                uncovered += 1
            targets_x.append(x)
            targets_y.append(y)
    tracked_x = _motion(targets_x, resets, cw, frames)
    tracked_y = _motion(targets_y, resets, ch, frames)
    error = None
    # face_track widens its blend ramps before refusing pins.
    for ramp in (1.1, 1.4, 2, 3, 4.5, 7, 10) if mode == "face_track" else (1,):
        x, wx = _manual(tracked_x, keyframes, "x", sw, cw, frames, mode, ramp)
        y, wy = _manual(tracked_y, keyframes, "y", sh, ch, frames, mode, ramp)
        x = [_clip(v, 0, sw - cw) for v in x]
        y = [_clip(v, 0, sh - ch) for v in y]
        error = _pin_error(x, wx, cw, frames, resets) or _pin_error(
            y, wy, ch, frames, resets
        )
        if not error:
            break
    if keyframes and error:
        raise ValueError(error)
    report = {
        "mode": mode,
        "crop": [cw, ch],
        "source": [sw, sh],
        "frame": list(frame_size),
        "fps": fps,
        "frames": count,
        "x": x,
        "y": y,
        "resets": sorted(resets),
        "face_frames": face_frames,
        "max_step": [
            TRACKING["max_speed"] * cw / fps,
            TRACKING["max_speed"] * ch / fps,
        ],
        "tracking": dict(TRACKING),
        "zone": {side: zone[side] for side in ("left", "right", "top", "bottom")},
        "keyframed": bool(keyframes),
        "warnings": [],
    }
    if mode == "face_track":
        fraction = len(face_frames) / count
        report["face_coverage"] = {
            "fresh_frames": len(face_frames),
            "stale_frames": stale,
            "uncovered_frames": uncovered,
            "fraction": fraction,
            "max_sample_age_s": max_age,
        }
        if fraction < MIN_FACE_COVERAGE:
            report["warnings"].append(
                f"A usable face was found in {fraction:.0%} of program frames "
                f"(below {MIN_FACE_COVERAGE:.0%}); the crop holds or stays centred "
                "elsewhere. Small faces in wide shots can be missed: Vision "
                "analyses frames at 640 px wide"
            )
    return report


def path_expression(values, resets=()):
    """Balanced piecewise-linear expression in frame index n; error <=0.1 source px."""
    boundaries = sorted({0, len(values), *resets})
    pieces = []

    def split(first, last):
        # Iterative (left first) so adversarial paths cannot exhaust the stack.
        stack = [(first, last)]
        while stack:
            a, b = stack.pop()
            if a == b:
                pieces.append((a, b, values[a], 0))
                continue
            slope = (values[b] - values[a]) / (b - a)
            error, pivot = max(
                (
                    (abs(values[i] - (values[a] + slope * (i - a))), i)
                    for i in range(a + 1, b)
                ),
                default=(0, a),
            )
            if error > 0.1:
                # Split at the worst point unless it hugs an end of a long span;
                # then halve, which bounds the work at O(n log n).
                if b - a > 32 and min(pivot - a, b - pivot) < (b - a) // 8:
                    pivot = (a + b) // 2
                stack.append((pivot, b))
                stack.append((a, pivot))
            else:
                pieces.append((a, b, values[a], slope))
            if len(pieces) + len(stack) > MAX_PIECES:
                # Every pending span adds at least one piece.
                raise ValueError(
                    f"Crop path for {len(values)} frames needs more than "
                    f"{MAX_PIECES} expression pieces per axis (the limit); split "
                    "the edit into shorter renders"
                )

    for a, b in zip(boundaries, boundaries[1:]):
        if a < b:
            split(a, b - 1)

    def balanced(items):
        if len(items) == 1:
            a, _, value, slope = items[0]
            return (
                f"({value:.8f}+{slope:.8f}*(n-{a}))"
                if abs(slope) > 1e-10
                else f"{value:.8f}"
            )
        half = len(items) // 2
        return f"if(lt(n,{items[half][0]}),{balanced(items[:half])},{balanced(items[half:])})"

    return balanced(pieces), len(pieces)


def validate_report(report):
    if not isinstance(report, dict) or report.get("mode") not in {
        "center_crop",
        "face_track",
    }:
        raise ValueError("Invalid framing report")
    count = report.get("frames")
    if type(count) is not int or not 1 <= count <= MAX_FRAMES:
        raise ValueError("Invalid framing frame count")
    for axis in ("x", "y"):
        values = report.get(axis)
        if not isinstance(values, list) or len(values) > MAX_FRAMES:
            raise ValueError("Invalid framing path")
        for value in values:
            number(value, high=100000)
    for key in ("crop", "source", "frame", "max_step"):
        values = report.get(key)
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError("Invalid framing geometry")
        for value in values:
            number(value, high=100000)
    number(report.get("fps"), low=0.001, high=1000)
    for key in ("resets", "face_frames"):
        if not isinstance(report.get(key), list) or len(report[key]) > MAX_FRAMES:
            raise ValueError("Invalid framing evidence")
    for index in report["resets"]:
        if type(index) is not int or not 0 <= index < count:
            raise ValueError("Invalid reset frame")
    for face in report["face_frames"]:
        if not isinstance(face, list) or len(face) != 3:
            raise ValueError("Invalid face evidence")
        number(face[0], high=count - 1)
        number(face[1], high=100000)
        number(face[2], high=100000)
    coverage = report.get("face_coverage")
    if coverage is not None:
        if not isinstance(coverage, dict) or set(coverage) != {
            "fresh_frames",
            "stale_frames",
            "uncovered_frames",
            "fraction",
            "max_sample_age_s",
        }:
            raise ValueError("Invalid face coverage")
        for value in coverage.values():
            number(value, high=MAX_FRAMES)
    zone = report.get("zone")
    if not isinstance(zone, dict) or set(zone) != {"left", "right", "top", "bottom"}:
        raise ValueError("Invalid framing safe zone")
    for value in zone.values():
        number(value, high=0.49)
    return report


def quality_checks(add, report, decoded_frames):
    if report is None:
        add(
            "framing_face_safe_zone",
            "warning",
            {"reason": "face_track render without a crop-path report; not checked"},
        )
        return
    validate_report(report)
    count = report["frames"]
    actual = decoded_frames
    add(
        "framing_frames",
        "pass"
        if actual == count and len(report["x"]) == len(report["y"]) == count
        else "fail",
        {"planned": count, "decoded": actual},
    )
    resets = set(report["resets"])
    maximum = [0.0, 0.0]
    for axis, key in enumerate(("x", "y")):
        values = report[key]
        maximum[axis] = max(
            (
                abs(b - a)
                for i, (a, b) in enumerate(zip(values, values[1:]), 1)
                if i not in resets
            ),
            default=0,
        )
    limits = [TRACKING["max_speed"] * v / report["fps"] for v in report["crop"]]
    add(
        "framing_smoothness",
        "pass" if all(a <= b + 1e-5 for a, b in zip(maximum, limits)) else "fail",
        {
            "max_per_frame_source_px": maximum,
            "limit_source_px": limits,
            "max_pan_crop_widths_per_second": maximum[0]
            * report["fps"]
            / report["crop"][0],
            "reset_frames_exempt": sorted(resets),
            "method": "planned continuous path; encoded crop quantizes to chroma pixels",
        },
    )
    factor = max(a / b for a, b in zip(report["frame"], report["crop"]))
    add(
        "framing_upscale",
        "warning" if factor > 1.0001 else "pass",
        {
            "crop": report["crop"],
            "frame": report["frame"],
            "factor": factor,
            "meaning": "crop window in square display pixels enlarged to the output "
            "frame; detail is interpolated, not recorded",
        },
    )
    tracked = report["mode"] == "face_track"
    coverage = report.get("face_coverage") or {}
    zone = report["zone"]
    inside = total = 0
    for index, fx, fy in report["face_frames"]:
        if type(index) is not int or index >= min(len(report["x"]), len(report["y"])):
            continue
        # Match crop's default chroma-subsampled even-pixel rounding.
        x, y = int(report["x"][index]) // 2 * 2, int(report["y"][index]) // 2 * 2
        nx, ny = (fx - x) / report["crop"][0], (fy - y) / report["crop"][1]
        total += 1
        inside += (
            zone["left"] <= nx <= 1 - zone["right"]
            and zone["top"] <= ny <= 1 - zone["bottom"]
        )
    fraction = inside / total if total else None
    add(
        "framing_face_safe_zone",
        ("warning" if tracked else "skip")
        if not total
        else "pass"
        if fraction >= 0.95
        else "fail",
        {
            "inside_fraction": fraction,
            "required_fraction": 0.95,
            "sampled_face_frames": total,
            "inside": inside,
            "stale_frames": coverage.get("stale_frames"),
            "uncovered_frames": coverage.get("uncovered_frames", count - total),
            "max_sample_age_s": coverage.get("max_sample_age_s"),
            "method": "frames with a fresh face sample of the same shot (age at most "
            "one sampling interval plus one frame); selected face centres projected "
            "through the planned quantized crop, not output redetection",
            **({} if total else {"reason": "No usable face sample in any frame"}),
        },
    )
    if tracked:
        share = total / count
        add(
            "framing_face_coverage",
            "warning" if share < MIN_FACE_COVERAGE else "pass",
            {
                "fresh_fraction": share,
                "required_fraction": MIN_FACE_COVERAGE,
                "fresh_frames": total,
                "stale_frames": coverage.get("stale_frames"),
                "uncovered_frames": coverage.get("uncovered_frames"),
                "meaning": "share of program frames with a usable face; elsewhere "
                "the crop holds or stays centred",
            },
        )


def prepare_path(source, info, ranges, settings, width, height):
    """Map decoded source PTS to the exact kept frames; expressions use joined n."""
    import json

    from .postproduction import _frame_rate, _run, _source_video, _timeline

    fps = _frame_rate(info) or 30
    data = json.loads(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-select_streams",
                "v:0",
                "-show_frames",
                "-show_entries",
                "frame=best_effort_timestamp_time",
                "-of",
                "json",
                str(source),
            ],
            timeout=settings["timeout"],
        ).stdout
    )
    timestamps = [
        float(f["best_effort_timestamp_time"])
        for f in data["frames"]
        if "best_effort_timestamp_time" in f
    ]
    if len(timestamps) > MAX_FRAMES:
        raise ValueError(
            "Reframing supports at most 250000 source frames; split longer media"
        )
    stream = next(s for s in info["streams"] if s.get("codec_type") == "video")
    if stream.get("r_frame_rate") != stream.get("avg_frame_rate") and (
        settings.get("framing") == "face_track" or settings.get("framing_keyframes")
    ):
        raise ValueError(
            "Tracked/keyframed crops require constant-rate media; conform variable-rate sources first"
        )
    analysis = settings.get("framing_analysis") or {"faces": [], "scene_cuts": []}
    if settings.get("framing") == "face_track" and "framing_analysis" not in settings:
        raise ValueError("Run Vision before rendering face_track framing")
    validate_analysis(analysis)
    # One timeline: FFmpeg's filter time (container start = 0), as used by the
    # trim edges, scdet and segment times. Vision times start at the first video
    # frame, which sits `origin` seconds into that timeline.
    base, origin = _timeline(info)
    timestamps = [t - base for t in timestamps]
    selected, samples, resets, cuts = [], [], [], []
    source_times = [sample[0] + origin for sample in analysis["faces"]]
    gaps = sorted(b - a for a, b in zip(source_times, source_times[1:]))
    sample_interval = gaps[len(gaps) // 2] if gaps else 1 / fps
    source_cuts = analysis["scene_cuts"] or []
    half = 0.5 / fps
    for start, end in ranges:
        indices = [t for t in timestamps if start <= t < end]
        if not indices:
            continue
        resets.append(len(selected))
        last_t = start
        for t in indices:
            index = len(selected)
            selected.append(t)
            # Only a sample of this very frame is carried; samples from removed
            # content never reach the program.
            j = bisect.bisect_left(source_times, t - half)
            if j < len(source_times) and source_times[j] < t + half:
                samples.append([index / fps, analysis["faces"][j][1]])
            if bisect.bisect_right(source_cuts, t + 1e-6) > bisect.bisect_right(
                source_cuts, last_t
            ):
                cuts.append(index / fps)
            last_t = t
    source_grid = _source_video(info)
    sw, sh = source_grid["width"], source_grid["height"]
    cw, ch = crop_size(sw, sh, width, height)
    from .platforms import profile

    entry = profile(settings.get("platform", "custom"))
    zone = entry["safe_zone"]
    if zone:
        zone = {
            side: max(zone[side], settings["brand"]["safe_margin"])
            for side in ("left", "right", "top", "bottom")
        }
    keys = validate_keyframes(
        settings.get("framing_keyframes", []),
        duration=sum(e - s for s, e in ranges) + 1 / fps,
    )
    report = plan_path(
        mode=settings["framing"],
        source_size=(sw, sh),
        crop_size=(cw, ch),
        frame_size=(width, height),
        frames=[i / fps for i in range(len(selected))],
        fps=fps,
        faces=samples,
        scene_cuts=cuts,
        edit_resets=resets,
        zone=zone,
        keyframes=keys,
        sample_interval=sample_interval,
    )
    if analysis["scene_cuts"] is None:
        report["warnings"].append(
            "Scene detection unavailable; only edit boundaries reset the crop"
        )
    report["source_sample_count"] = len(analysis["faces"])
    return report
