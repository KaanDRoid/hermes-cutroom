"""Follow a hidden area's contents from frame to frame (template matching).

Frames come from FFmpeg with the same input handling as the render: the same timeline (the
container's earliest stream starts at 0) and the same automatic rotation, so a box drawn on the
picture as shown lands on the same pixels the render covers.

The box keeps its size. It is learned on the frame it was drawn on and followed forwards and
backwards from there. A frame counts as followed only when one place clearly matches; when the
match is weak (covered, cut away, gone) or two places match about as well (look-alikes), the box
stays where it last was and the time is reported as lost. The render then covers the whole picture
for that time, so a tracking miss hides too much rather than too little.
"""

import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

from . import media

ANALYSIS_WIDTH = 480  # Frames are searched at this width at most; positions are fractions.
MATCH = 0.6  # Normalised correlation needed to trust a position.
AMBIGUOUS = 0.12  # A second place this close to the best means look-alikes: not trusted.
PLAIN = 4.0  # Below this grey-level spread a box holds nothing to follow.
SEARCH = 1.0  # Search this many box sizes around the last position.
MAX_SECONDS = 30.0  # Longest stretch one box follows (see redactions.normalize).
MAX_BYTES = 320 * 1024 * 1024  # Decoded analysis frames held for one box.
TIMEOUT = 300
_PTS = re.compile(r"pts_time:\s*(-?[0-9.]+(?:e-?[0-9]+)?)")


def _dependencies():
    try:
        import cv2
        import numpy as np
    except ImportError as error:  # pragma: no cover - depends on the install
        raise ValueError("Following a hidden area needs the vision extra (pip install 'hermes-cutroom[vision]')") from error
    return cv2, np


def _shown_size(path):
    """(width, height, frames per second) of the first video stream as the render sees it."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,avg_frame_rate,r_frame_rate:stream_side_data=rotation", "-of", "json", str(path)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, env=media.child_env(python=False), check=True,
    )
    streams = json.loads(out.stdout).get("streams") or []
    if not streams:
        raise ValueError("The source has no picture to follow")
    stream = streams[0]
    width, height = int(stream["width"]), int(stream["height"])
    turns = [abs(float(item.get("rotation", 0))) % 180 for item in stream.get("side_data_list", []) if "rotation" in item]
    if turns and abs(turns[0] - 90) < 1:
        width, height = height, width
    rate = 0.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            top, bottom = (float(part) for part in str(stream.get(key, "0/0")).split("/"))
            rate = top / bottom if bottom else 0.0
        except ValueError:
            rate = 0.0
        if rate > 0:
            break
    return width, height, rate or 30.0


def _frames(path, start, end):
    """Grey analysis frames over [start, end] on the render timeline, with their times."""
    width, height, rate = _shown_size(path)
    gw = max(16, min(ANALYSIS_WIDTH, width) // 2 * 2)
    gh = max(16, round(height * gw / width / 2) * 2)
    if (end - start + 1) * rate * gw * gh > MAX_BYTES:
        raise ValueError("This hidden area is too long or the video's frame rate too high to follow; split the range")
    seek = max(0.0, start - 2.0)
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"), prefix="cutroom-follow-") as folder:
        log = Path(folder) / "frames.txt"
        with open(log, "wb") as errors:
            # -copyts -start_at_zero keeps the render's timeline after seeking; trim cuts exactly.
            run = subprocess.run(
                ["ffmpeg", "-nostdin", "-hide_banner", "-v", "info", "-protocol_whitelist", "file",
                 "-copyts", "-start_at_zero", "-ss", f"{seek:.3f}", "-i", str(path), "-map", "0:v:0", "-an", "-sn", "-dn",
                 "-vf", f"trim=start={start:.6f}:end={end + 1e-3:.6f},scale={gw}:{gh}:flags=area,format=gray,showinfo",
                 "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors, timeout=TIMEOUT,
                env=media.child_env(python=False), check=False,
            )
        text = log.read_text(encoding="utf-8", errors="replace")
    if run.returncode != 0:
        raise ValueError("The source video could not be read for following a hidden area")
    times = [float(match.group(1)) for line in text.splitlines() if "Parsed_showinfo" in line for match in [_PTS.search(line)] if match]
    size = gw * gh
    if len(run.stdout) != size * len(times):
        raise ValueError("The frames and their times do not line up; the hidden area cannot be followed")
    if any(not math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("The source's frame times are not in order; the hidden area cannot be followed")
    return times, run.stdout, (gw, gh), rate


def _match(cv2, np, frame, position, size, patterns):
    """(best score, second-place score, position) near the last position."""
    w, h = size
    gh, gw = frame.shape
    reach = round(max(w, h) * SEARCH)
    x0, y0 = max(0, position[0] - reach), max(0, position[1] - reach)
    x1, y1 = min(gw, position[0] + w + reach), min(gh, position[1] + h + reach)
    area = frame[y0:y1, x0:x1]
    best = (-1.0, -1.0, position)
    for pattern in patterns:
        scores = cv2.matchTemplate(area, pattern, cv2.TM_CCOEFF_NORMED)
        scores = np.nan_to_num(scores, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, score, _, (bx, by) = cv2.minMaxLoc(scores)
        others = scores.copy()
        others[max(0, by - h // 2) : by + h // 2 + 1, max(0, bx - w // 2) : bx + w // 2 + 1] = -1.0
        second = float(others.max()) if others.size else -1.0
        if score > best[0]:
            best = (float(score), second, (x0 + bx, y0 + by))
    return best


def follow_box(source, box, start, end, at=None):
    """Box positions over [start, end] in source seconds (the render's timeline).

    ``at`` is when the box was drawn (default ``start``). Returns {"times", "x", "y", "lost"}: x and
    y are fractions of the picture as shown, one sample per frame; ``lost`` lists [start, end]
    stretches where the box could not be trusted.
    """
    cv2, np = _dependencies()
    if not (0 <= start < end) or end - start > MAX_SECONDS + 1e-6:
        raise ValueError(f"A followed hidden area lasts at most {MAX_SECONDS:g} seconds")
    times, data, (gw, gh), rate = _frames(media._local_path(source), start, end)
    if not times:
        raise ValueError("No frames were found for the hidden area's time")
    frames = np.frombuffer(data, dtype=np.uint8).reshape(len(times), gh, gw)
    at = start if at is None else min(max(at, start), end)
    seed = min(range(len(times)), key=lambda i: abs(times[i] - at))
    w = max(4, min(gw, round(box["w"] * gw)))
    h = max(4, min(gh, round(box["h"] * gh)))
    x = min(gw - w, max(0, round(box["x"] * gw)))
    y = min(gh - h, max(0, round(box["y"] * gh)))
    template = frames[seed][y : y + h, x : x + w].copy()
    positions = [(x, y)] * len(times)
    trusted = [False] * len(times)
    if float(template.std()) >= PLAIN:
        trusted[seed] = True
        for step in (1, -1):
            position, latest = (x, y), template
            index = seed + step
            while 0 <= index < len(times):
                score, second, found = _match(cv2, np, frames[index], position, (w, h), (template, latest))
                if score >= MATCH and second < score - AMBIGUOUS:
                    position = found
                    latest = frames[index][position[1] : position[1] + h, position[0] : position[0] + w].copy()
                    trusted[index] = True
                positions[index] = position
                index += step
    lost, run = [], None
    for index, good in enumerate(trusted):
        if not good and run is None:
            run = index
        if good and run is not None:
            lost.append([round(start if run == 0 else times[run], 3), round(times[index], 3)])
            run = None
    if run is not None:
        lost.append([round(start if run == 0 else times[run], 3), round(end, 3)])
    elif end - times[-1] > 2.5 / rate:
        # The picture stopped before the range did (or reading stopped early): cover the rest.
        lost.append([round(times[-1], 3), round(end, 3)])
    return {"times": times, "x": [p[0] / gw for p in positions], "y": [p[1] / gh for p in positions], "lost": lost}
