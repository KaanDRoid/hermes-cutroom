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
# Smallest font for animated captions, as a share of the frame height. The BBC
# Subtitle Guidelines set a line height of 3.9-4.5 % of the frame for 9:16 video
# and 7-8 % for 16:9 and 1:1; at a 1.2 line spacing that is a font of 3.5 % and
# 6.25 %. A larger brand subtitle size is kept.
READABLE_FONT = {"portrait": 0.035, "landscape": 0.0625}
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


def frame_rate_value(frame_rate):
    """Frames per second from an FFprobe rate; unknown rates ('0/0') mean 30."""
    try:
        fps = float(Fraction(str(frame_rate))) if frame_rate else 30.0
    except (ValueError, ZeroDivisionError):
        return 30.0
    return fps if math.isfinite(fps) and fps > 0 else 30.0


def frame_edge(frame, fps):
    """ASS time (centiseconds) at which an event must start to show from ``frame``.

    libass treats a frame whose time equals an event edge as outside the event
    (millisecond truncation), and at 25, 30 and 60 fps many frames fall exactly
    on a centisecond. The edge is therefore the last centisecond at least 1 ms
    before the frame and still after the previous frame. Above about 90 fps no
    such centisecond may exist, and the frame time itself is used.
    """
    if frame <= 0:
        return 0.0
    target = frame / fps
    value = math.floor((target - 0.001) * 100 + 1e-9) / 100
    if value <= (frame - 1) / fps + 1e-9:
        value = math.floor(target * 100 + 1e-9) / 100
    return value


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
            or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in word["text"])
        ):
            raise ValueError(
                "Word text must be printable, non-empty and under 1000 characters"
            )
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
    readable = READABLE_FONT["portrait" if height > width else "landscape"] * height
    base_size = max(band["size"], readable) * (2 if style == "one_word" else 1)
    # Padding covers libass border, shadow and metric differences.
    available = band["w"] - 16
    base_size = min(base_size, (safe["y1"] - safe["y0"] - 16) / 2.5)
    fps = frame_rate_value(frame_rate)
    # Frames 0 .. last_frame - 1 exist; a word starting after them cannot show.
    last_frame = math.ceil(duration * fps - 1e-6) if math.isfinite(duration) else None

    def first_frame(t):
        return math.ceil(t * fps - 1e-6)

    # Units: words whose first frame is the same share one caption state, and a
    # word shorter than a frame still gets one frame.
    units = []
    for index, word in enumerate(words):
        start_frame = first_frame(word["start"])
        if last_frame is not None and start_frame >= last_frame:
            continue
        end_frame = max(first_frame(word["end"]), start_frame + 1)
        if last_frame is not None:
            end_frame = min(end_frame, last_frame)
        if units and units[-1]["start"] == start_frame:
            units[-1]["words"].append(index)
            units[-1]["end"] = max(units[-1]["end"], end_frame)
        else:
            units.append(dict(start=start_frame, end=end_frame, words=[index]))

    groups, group, lines = [], [], [""]
    for unit in units:
        tokens = [words[i]["text"] for i in unit["words"]]
        trial = (lines[-1] + " " + " ".join(tokens)).strip()
        new_line = measure(trial, base_size) > available
        if group and (
            style == "one_word"
            or sum(len(u["words"]) for u in group) >= 6
            or (unit["start"] - group[0]["start"]) / fps > 3
            or (new_line and len(lines) == 2)
        ):
            groups.append((group, lines))
            group, lines, new_line = [], [""], False
        for token in tokens:
            if new_line and group and lines[-1]:
                lines.append(token)
                new_line = False
            else:
                lines[-1] = (lines[-1] + " " + token).strip()
        group.append(unit)
    if group:
        groups.append((group, lines))
    # A group ends no later than the next group starts, so two groups never
    # draw at the same time.
    for (group, _), (following, _) in zip(groups, groups[1:]):
        for unit in group:
            unit["end"] = min(unit["end"], following[0]["start"])
    events = []
    for group, lines in groups:
        size = min(
            base_size, available / max(1, max(measure(line, 1) for line in lines))
        )
        x = (safe["x0"] + safe["x1"]) / 2
        # The block (lines x 1.25 line height, plus border padding) stays in the
        # safe area even when the readable size is larger than the brand band.
        half = (len(lines) * size * 1.25 + 8) / 2
        y = band["y"] + band["h"] / 2
        y = min(max(y, safe["y0"] + half), safe["y1"] - half)
        if style == "one_word":
            # caption_word_y places the block within the room left by its height.
            span = safe["y1"] - safe["y0"] - 2 * half
            y = (
                safe["y0"]
                + half
                + span * settings.get("caption_word_y", DEFAULT_WORD_Y)
            )
        boundaries = sorted({f for unit in group for f in (unit["start"], unit["end"])})
        for start, end in zip(boundaries, boundaries[1:]):
            active = next(
                (u for u in reversed(group) if u["start"] <= start < u["end"]), None
            )
            newly = next((u for u in group if u["start"] == start), None)
            name = (
                "w" + "_".join(str(words[i]["index"]) for i in newly["words"])
                if newly is not None
                else "gap"
            )
            if style == "one_word" and active is None:
                continue
            rendered, line_index, used = [], 0, ""
            for unit in group:
                if style == "one_word" and unit is not active:
                    continue
                for i in unit["words"]:
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
                    if style == "highlight" and unit is active:
                        tags += r"\1c" + color(
                            settings.get("caption_highlight_color", DEFAULT_HIGHLIGHT)
                        )
                    if style == "pop":
                        if unit["start"] > start:
                            tags += r"\alpha&HFF&"
                        elif unit is newly:
                            ms = min(90, max(1, round((end - start) / fps * 1000)))
                            tags += rf"\fscy82\t(0,{ms},\fscy100)"
                    rendered.append("{" + tags + "}" + token)
            a, b = frame_edge(start, fps), frame_edge(end, fps)
            if b <= a:
                # Above about 100 fps two frames can share a centisecond.
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

    styles, events, play = {}, [], {}
    for line in script.splitlines():
        if line.startswith(("PlayResX:", "PlayResY:")):
            key, _, value = line.partition(":")
            try:
                play[key] = int(value.strip())
            except ValueError:
                pass
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
    return dict(
        styles=styles,
        events=events,
        play_res=(play.get("PlayResX"), play.get("PlayResY")),
    )


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
    """Compare every word with the frames on which its caption state is shown.

    A frame is counted as showing an event only when it comes more than half a
    millisecond after the event start, and as clear of it only when it comes
    more than half a millisecond after the event end, because libass truncates
    frame times to milliseconds. Words merged into one state (same first frame)
    are checked against that state. A word shorter than one frame passes when
    it is shown for exactly one frame. Words that start after the last frame
    cannot be shown and are not counted.
    """
    margin = 0.0005
    events = {}
    for event in parsed["events"]:
        match = re.fullmatch(r"w(\d+(?:_\d+)*)", event["name"])
        if match:
            members = [int(i) for i in match[1].split("_")]
            for index in members:
                events.setdefault(index, (event, members))
    typical = sorted(b - a for a, b in zip(frames, frames[1:]) if b > a)
    tolerance = typical[len(typical) // 2] if typical else 1 / 30
    errors, findings = [], []
    for index, word in enumerate(words):
        if word["end"] <= word["start"]:
            continue
        if frames and word["start"] > frames[-1] + 1e-6:
            continue
        found = events.get(index)
        if found is None:
            findings.append(dict(word=index, reason="No rendered word event"))
            continue
        event, members = found
        at = bisect.bisect_right(frames, event["start"] + margin)
        if at >= len(frames):
            findings.append(dict(word=index, reason="No decoded frame in event"))
            continue
        error = frames[at] - word["start"]
        errors.append(error)
        if abs(error) > tolerance + 1e-6 or error < -1e-6:
            findings.append(dict(word=index, error_seconds=error))
        # The first frame without this state may come at most one frame after
        # the (latest) word in it ends. Ending earlier is expected when the next
        # word starts before this one finishes.
        after = bisect.bisect_right(frames, event["end"] + margin)
        stop = frames[after] if after < len(frames) else event["end"]
        end = max(words[i]["end"] for i in members if i < len(words))
        late = stop - end
        single_frame = stop - frames[at] <= tolerance + 1e-6
        if late > tolerance + 1e-6 and not single_frame:
            findings.append(dict(word=index, end_late_seconds=late))
    return dict(
        status="fail" if findings else "pass",
        words_checked=len(errors),
        max_abs_error_seconds=max(map(abs, errors), default=0),
        tolerance_seconds=tolerance,
        findings=findings,
    )
