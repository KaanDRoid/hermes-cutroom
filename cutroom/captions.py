"""Word-timed ASS captions, measured layout and script-based quality checks."""

import bisect
import math
import re
from fractions import Fraction
from functools import lru_cache

STYLES = ("classic", "highlight", "pop", "one_word")
DEFAULT_HIGHLIGHT = "#FFCC00"
# One-word captions sit in the lower part of the safe area, below a talking
# head's face (0 = top of the safe area, 1 = bottom).
DEFAULT_WORD_Y = 0.8
# Optional fields where an explicit null in an update means "use the default".
RESETTABLE = ("caption_highlight_color", "caption_word_y")


def validate_settings(settings, *, allow_reset=False):
    """Validate caption settings; ``allow_reset`` accepts null for RESETTABLE."""
    if settings.get("caption_style", "classic") not in STYLES:
        raise ValueError("caption_style must be classic, highlight, pop or one_word")
    if allow_reset:
        settings = {
            key: value
            for key, value in settings.items()
            if not (key in RESETTABLE and value is None)
        }
    color = settings.get("caption_highlight_color", DEFAULT_HIGHLIGHT)
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise ValueError("Caption highlight color must be a six-digit hex value")
    y = settings.get("caption_word_y", DEFAULT_WORD_Y)
    if (
        isinstance(y, bool)
        or not isinstance(y, (int, float))
        or not math.isfinite(y)
        or not 0 <= y <= 1
    ):
        raise ValueError("caption_word_y must be between 0 and 1")


class Measurer:
    """Use local glyph advances with a conservative fallback when Pillow is absent."""

    def __init__(self, font_path):
        self.font = None
        if font_path is not None:
            try:
                from PIL import ImageFont

                self.font = ImageFont.truetype(str(font_path), 1080)
            except (ImportError, OSError):
                pass
        self.method = "glyph" if self.font else "em"

    @lru_cache(maxsize=4096)
    def __call__(self, text, size):
        if self.font is None:
            return len(text) * size
        # Include overhanging glyph ink as well as advances.
        bounds = self.font.getbbox(text)
        return (
            max(self.font.getlength(text), bounds[2] - min(0, bounds[0])) * size / 1080
        )


def literal(text):
    return " ".join(text.split()).translate(
        str.maketrans({"\\": "＼", "{": "｛", "}": "｝"})
    )


def plain_text(text):
    return re.sub(r"\{[^}]*\}", "", text).replace(r"\N", "\n")


def color(value):
    rgb = value.lstrip("#")
    return "&H" + rgb[4:6] + rgb[2:4] + rgb[:2] + "&"


def timestamp(value):
    ticks = round(value * 100)
    return f"{ticks // 360000}:{ticks // 6000 % 60:02}:{ticks // 100 % 60:02}.{ticks % 100:02}"


def words_from_cues(cues):
    result = []
    for cue in cues:
        tokens = cue["text"].split()
        total = sum(map(len, tokens))
        done = 0
        for token in tokens:
            start = cue["start"] + (cue["end"] - cue["start"]) * done / total
            done += len(token)
            end = cue["start"] + (cue["end"] - cue["start"]) * done / total
            result.append(dict(start=start, end=end, text=token))
    return result


def _words(words, duration):
    """Validate words; keep renderable ones with their original index.

    The index names each word event (``w<index>``), so dropping a zero-length
    word never shifts which event the timing report compares a word with.
    """
    previous = 0
    result = []
    for index, word in enumerate(words):
        start, end = word["start"], word["end"]
        if any(
            isinstance(t, bool)
            or not isinstance(t, (int, float))
            or not math.isfinite(t)
            for t in (start, end)
        ):
            raise ValueError("Word timestamps must be finite numbers")
        if start < previous or start < 0 or end < start:
            raise ValueError("Word timestamps must be ordered and positive")
        if (
            not isinstance(word["text"], str)
            or not word["text"].strip()
            or len(word["text"]) > 1000
        ):
            raise ValueError("Word text must be non-empty and under 1000 characters")
        previous = start
        if end > start and start < duration:
            result.append(
                dict(
                    start=start,
                    end=min(end, duration),
                    text=literal(word["text"]),
                    index=index,
                )
            )
    return result


def wrap_lines(text, width, size, measure):
    """Measured two-line caller primitive; split oversized tokens without dropping text."""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for token in paragraph.split():
            pieces = []
            piece = ""
            for char in token:
                if piece and measure(piece + char, size) > width:
                    pieces.append(piece)
                    piece = ""
                piece += char
            if piece:
                pieces.append(piece)
            for index, piece in enumerate(pieces):
                trial = (line + " " + piece).strip()
                if line and (index or measure(trial, size) > width):
                    lines.append(line)
                    line = piece
                else:
                    line = trial
        if line:
            lines.append(line)
    return lines


def build(
    words, settings, width, height, layout, *, frame_rate="30/1", duration=math.inf
):
    """Each state is a separate event: no cumulative karaoke rounding or sweep.

    Highlight resets to the base colour in pauses. Pop uses stable full-cue
    advances, transparent future words and a vertical 82%-100% scale-in, so
    revealing a word cannot reflow the cue or expand it outside its box.
    """
    from .postproduction import _font_path

    validate_settings(settings)
    style = settings.get("caption_style", "classic")
    brand = settings["brand"]
    measure = Measurer(_font_path(brand["font"]))
    words = _words(words, duration)
    if layout is None:
        margin = brand["safe_margin"]
        safe = dict(
            x0=width * margin + 8,
            x1=width * (1 - margin) - 8,
            y0=height * margin + 8,
            y1=height * (1 - margin) - 8,
        )
        size = brand["subtitle_size"] * min(width, height) / 1080
        bottom = min(
            safe["y1"],
            max(safe["y0"] + 2.5 * size, height * brand["subtitle_y"] + 2 * size),
        )
        band = dict(
            x=safe["x0"],
            y=bottom - 2.5 * size,
            w=safe["x1"] - safe["x0"],
            h=2.5 * size,
            size=size,
        )
    else:
        safe, band = layout["safe"], layout["boxes"]["captions"]
    base_size = band["size"] * (2 if style == "one_word" else 1)
    # Padding covers libass border, shadow and metric differences.
    available = band["w"] - 16
    base_size = min(base_size, (safe["y1"] - safe["y0"] - 16) / 2.5)
    fps = float(Fraction(frame_rate or "30/1"))
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("Invalid frame rate")

    def snap(t):
        # The centisecond begins after the preceding frame, never after the
        # desired first frame. First decoded appearance is ceil(t * fps).
        frame = math.ceil(t * fps - 1e-8)
        return math.floor(frame / fps * 100 + 1e-8) / 100

    groups, group, lines = [], [], [""]
    for index, word in enumerate(words):
        text = word["text"]
        trial = (lines[-1] + " " + text).strip()
        new_line = measure(trial, base_size) > available
        if group and (
            style == "one_word"
            or len(group) >= 6
            or word["start"] - words[group[0]]["start"] > 3
            or (new_line and len(lines) == 2)
        ):
            groups.append((group, lines))
            group, lines, new_line = [], [""], False
        if new_line and group:
            lines.append(text)
        else:
            lines[-1] = (lines[-1] + " " + text).strip()
        group.append(index)
    if group:
        groups.append((group, lines))
    events = []
    for indices, lines in groups:
        size = min(
            base_size, available / max(1, max(measure(line, 1) for line in lines))
        )
        x = (safe["x0"] + safe["x1"]) / 2
        y = band["y"] + band["h"] / 2
        if style == "one_word":
            span = safe["y1"] - safe["y0"] - 2.5 * size - 16
            y = (
                safe["y0"]
                + 1.25 * size
                + 8
                + span * settings.get("caption_word_y", DEFAULT_WORD_Y)
            )
        first, last = words[indices[0]]["start"], max(words[i]["end"] for i in indices)
        boundaries = sorted(
            {
                first,
                last,
                *(words[i]["start"] for i in indices),
                *(words[i]["end"] for i in indices),
            }
        )
        for start, end in zip(boundaries, boundaries[1:]):
            if end <= start:
                continue
            active = next(
                (
                    i
                    for i in reversed(indices)
                    if words[i]["start"] <= start < words[i]["end"]
                ),
                None,
            )
            newly = next((i for i in indices if words[i]["start"] == start), None)
            name = f"w{words[newly]['index']}" if newly is not None else "gap"
            if style == "one_word" and active is None:
                continue
            rendered, line_index, used = [], 0, ""
            for i in indices:
                token = words[i]["text"]
                if (
                    used
                    and measure(used + " " + token, base_size) > available
                    and line_index < len(lines) - 1
                ):
                    rendered.append(r"\N")
                    line_index += 1
                    used = ""
                elif used:
                    rendered.append(" ")
                used = (used + " " + token).strip()
                tags = r"\alpha&H00&\fscy100\1c" + color(brand["subtitle_color"])
                if style == "highlight" and i == active:
                    tags += r"\1c" + color(
                        settings.get("caption_highlight_color", DEFAULT_HIGHLIGHT)
                    )
                if style == "pop":
                    if words[i]["start"] > start:
                        tags += r"\alpha&HFF&"
                    elif i == newly:
                        ms = min(90, max(1, round((end - start) * 1000)))
                        tags += rf"\fscy82\t(0,{ms},\fscy100)"
                if style != "one_word" or i == active:
                    rendered.append("{" + tags + "}" + token)
            a, b = snap(start), snap(end)
            if b <= a:
                # A fragment shorter than a frame has no renderable interval.
                continue
            text = rf"{{\an5\pos({x:.3f},{y:.3f})\fs{size:.3f}\q2}}" + "".join(rendered)
            events.append(dict(start=a, end=b, name=name, text=text))
    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Word,{brand['font']},{base_size:.3f},{color(brand['subtitle_color'])},{color(brand['subtitle_color'])},&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,5,0,0,0,1\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    script = header + "".join(
        f"Dialogue: 0,{timestamp(e['start'])},{timestamp(e['end'])},Word,{e['name']},0,0,0,,{e['text']}\n"
        for e in events
    )
    return dict(script=script, events=events, measurement=measure.method)


def parse_script(script):
    def seconds(t):
        h, m, s = map(float, t.split(":"))
        return h * 3600 + m * 60 + s

    styles, events = {}, []
    for line in script.splitlines():
        if line.startswith("Style: "):
            fields = line[7:].split(",")
            styles[fields[0]] = dict(
                size=float(fields[2]),
                outline=float(fields[16]),
                shadow=float(fields[17]),
            )
        if line.startswith("Dialogue: "):
            fields = line[10:].split(",", 9)
            events.append(
                dict(
                    start=seconds(fields[1]),
                    end=seconds(fields[2]),
                    style=fields[3],
                    name=fields[4],
                    text=fields[9],
                )
            )
    return dict(styles=styles, events=events)


def event_boxes(parsed, measure):
    boxes = []
    for event in parsed["events"]:
        text = event["text"]
        pos = re.search(r"\\pos\(([\d.]+),([\d.]+)\)", text)
        fs = re.search(r"\\fs([\d.]+)", text)
        if not pos or not fs:
            raise ValueError("Animated event lacks explicit position or font size")
        x, y = map(float, pos.groups())
        size = float(fs[1])
        lines = plain_text(text).split("\n")
        w = max(measure(line, size) for line in lines) + 8
        h = len(lines) * size * 1.25 + 8
        boxes.append(dict(x=x - w / 2, y=y - h / 2, w=w, h=h, size=size))
    return boxes


def timing_report(parsed, words, frames):
    events = {
        int(e["name"][1:]): e
        for e in parsed["events"]
        if re.fullmatch(r"w\d+", e["name"])
    }
    typical = sorted(b - a for a, b in zip(frames, frames[1:]) if b > a)
    tolerance = typical[len(typical) // 2] if typical else 1 / 30
    errors, findings = [], []
    for index, word in enumerate(words):
        if word["end"] <= word["start"]:
            continue
        event = events.get(index)
        if event is None:
            findings.append(dict(word=index, reason="No rendered word event"))
            continue
        at = bisect.bisect_left(frames, event["start"] - 1e-8)
        if at >= len(frames):
            findings.append(dict(word=index, reason="No decoded frame in event"))
            continue
        error = frames[at] - word["start"]
        errors.append(error)
        if abs(error) > tolerance + 1e-6 or error < -1e-6:
            findings.append(dict(word=index, error_seconds=error))
        # The word's state must also end on time: the first frame without this
        # event may come at most one frame after the word ends. Ending earlier is
        # expected when the next word starts before this one finishes.
        after = bisect.bisect_left(frames, event["end"] - 1e-8)
        stop = frames[after] if after < len(frames) else event["end"]
        late = stop - word["end"]
        if late > tolerance + 1e-6:
            findings.append(dict(word=index, end_late_seconds=late))
    return dict(
        status="fail" if findings else "pass",
        words_checked=len(errors),
        max_abs_error_seconds=max(map(abs, errors), default=0),
        tolerance_seconds=tolerance,
        findings=findings,
    )
