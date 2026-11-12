"""Local, no-overwrite postproduction using FFmpeg and the standard library."""

import copy
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

try:
    from . import platforms
    from .childenv import child_env
except ImportError:  # loaded as a standalone module file
    from cutroom import platforms
    from cutroom.childenv import child_env


def _number(value, low=None, high=None):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError("Expected a finite number")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError("Number outside allowed bounds")
    return float(value)


_FONT_PATHS = {
    "Arial": (
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ),
    "DejaVu Sans": ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",),
    "Liberation Sans": (
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ),
}


def _font_path(family):
    return next((Path(p) for p in _FONT_PATHS[family] if Path(p).is_file()), None)


def default_brand():
    """Positions/margins are fractions; font sizes use a 1080-pixel short side."""
    family = next(
        (name for name in _FONT_PATHS if _font_path(name) is not None), "Arial"
    )
    return dict(
        font=family,
        title_color="#FFFFFF",
        subtitle_color="#FFFFFF",
        graphic_color="#16324F",
        safe_margin=0.08,
        title_y=0.12,
        subtitle_y=0.82,
        title_size=54,
        subtitle_size=36,
        alignment="center",
        aspect="source",
        preset="preview",
    )


def validate_brand(brand):
    if not isinstance(brand, dict) or set(brand) - set(default_brand()):
        raise ValueError("Unknown brand fields")
    result = {**default_brand(), **copy.deepcopy(brand)}
    if result["font"] not in ("Arial", "DejaVu Sans", "Liberation Sans"):
        raise ValueError("Font must be an approved local family")
    for key in ("title_color", "subtitle_color", "graphic_color"):
        if not isinstance(result[key], str) or not re.fullmatch(
            r"#[0-9A-Fa-f]{6}", result[key]
        ):
            raise ValueError("Colors must be #RRGGBB")
    margin = _number(result["safe_margin"], 0.02, 0.25)
    for key in ("title_size", "subtitle_size"):
        _number(result[key], 12, 120)
    for key in ("title_y", "subtitle_y"):
        size = result["title_size" if key == "title_y" else "subtitle_size"]
        _number(result[key], margin, 1 - margin - size * 2 / 1080)
    if result["alignment"] not in ("left", "center", "right"):
        raise ValueError("Invalid alignment")
    if result["aspect"] not in ("source", "portrait", "landscape", "square"):
        raise ValueError("Invalid aspect")
    if result["preset"] not in ("preview", "final"):
        raise ValueError("Invalid preset")
    return result


def _path(value, exists=True):
    raw = os.fspath(value)
    normalized = raw.replace("\\", "/")
    tail = normalized[2:] if re.match(r"^[A-Za-z]:/", normalized) else normalized
    if not raw or "\0" in raw or ":" in tail or normalized.startswith("//"):
        raise ValueError("Only local files are allowed")
    path = Path(raw).resolve()
    if str(path).replace("\\", "/").startswith("//"):
        raise ValueError("Only local files are allowed")
    if exists and not path.is_file():
        raise FileNotFoundError(path)
    return path


def _write_brand(path, brand):
    path = _path(path, False)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".brand-", delete=False
    ) as stream:
        temporary = Path(stream.name)
        json.dump(brand, stream, ensure_ascii=False, allow_nan=False, indent=2)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return brand


def save_brand(path, brand):
    return _write_brand(path, validate_brand(brand))


def load_brand(path):
    return validate_brand(json.loads(_path(path).read_text(encoding="utf-8")))


def persist_correction(path, patch):
    if not isinstance(patch, dict):
        raise ValueError("Correction must be an object")
    return save_brand(path, {**load_brand(path), **patch})


def _run(args, *, cwd=None, timeout=300):
    return subprocess.run(
        args,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=True,
        timeout=timeout,
        env=child_env(python=False),
    )


def _render_graph(arguments, *, cwd, timeout):
    try:
        return _run(arguments, cwd=cwd, timeout=timeout)
    except subprocess.CalledProcessError as error:
        message = error.stderr or ""
        if "Unrecognized option" not in message or "/filter_complex" not in message:
            raise
        legacy = list(arguments)
        legacy[legacy.index("-/filter_complex")] = "-filter_complex_script"
        return _run(legacy, cwd=cwd, timeout=timeout)


def _quarter_turn(video):
    """True when the stream's display rotation swaps width and height."""
    rotation = next(
        (
            item.get("rotation", 0)
            for item in video.get("side_data_list", [])
            if "rotation" in item
        ),
        video.get("tags", {}).get("rotate", 0),
    )
    try:
        return abs(float(rotation)) % 180 == 90
    except (TypeError, ValueError):
        return False


def _source_video(info):
    """Source pixel grid in display orientation, for upscaling checks."""
    video = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    width, height = info["width"], info["height"]
    if _quarter_turn(video):
        width, height = height, width
    return dict(
        width=width, height=height, display_aspect_ratio=info["display_aspect_ratio"]
    )


def _content_size(ratio, width, height):
    """Size of the fitted (padded, never cropped) picture inside a frame."""
    return (
        max(2, min(width, math.floor(height * ratio / 2) * 2)),
        max(2, min(height, math.floor(width / ratio / 2) * 2)),
    )


def _content_upscale(source, width, height):
    """Fitted content size and its enlargement over the source pixel grid."""
    content = _content_size(source["display_aspect_ratio"], width, height)
    factor = max(content[0] / source["width"], content[1] / source["height"])
    return list(content), factor


def _probe(source, timeout=300):
    data = json.loads(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(source),
            ],
            timeout=timeout,
        ).stdout
    )
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("A video stream is required")
    duration = _number(
        float(data["format"].get("duration", video.get("duration", 0))), 0.000001
    )
    sar_parts = video.get("sample_aspect_ratio", "1:1").split(":")
    try:
        sar = float(sar_parts[0]) / float(sar_parts[1])
        if not math.isfinite(sar) or sar <= 0:
            sar = 1
    except (ValueError, IndexError, ZeroDivisionError):
        sar = 1
    display_ratio = int(video["width"]) * sar / int(video["height"])
    if _quarter_turn(video):
        display_ratio = 1 / display_ratio
    return dict(
        duration=duration,
        width=int(video["width"]),
        height=int(video["height"]),
        display_aspect_ratio=display_ratio,
        has_audio=any(s["codec_type"] == "audio" for s in data["streams"]),
        codec=video["codec_name"],
        streams=data["streams"],
    )


def _settings(settings):
    allowed = {
        "preset",
        "aspect",
        "brand",
        "title",
        "title_animation",
        "lower_third",
        "normalize_audio",
        "loudness_lufs",
        "true_peak_db",
        "timeout",
        "expected_duration",
        "black_min_duration",
        "freeze_min_duration",
        "silence_min_duration",
        "max_caption_chars",
        "max_caption_cps",
        "platform",
        "final_resolution",
        "source_video",
        "caption_style",
        "caption_highlight_color",
        "caption_word_y",
    }
    if settings is None:
        settings = {}
    if not isinstance(settings, dict) or set(settings) - allowed:
        raise ValueError("Unknown settings fields")
    from cutroom.captions import DEFAULT_HIGHLIGHT, validate_settings

    validate_settings(settings)
    brand = validate_brand(settings.get("brand", {}))
    result = dict(
        preset=brand["preset"],
        aspect=brand["aspect"],
        brand=brand,
        title="",
        title_animation=False,
        lower_third="",
        normalize_audio=True,
        loudness_lufs=-16,
        true_peak_db=-1.5,
        timeout=300,
        expected_duration=None,
        black_min_duration=0.1,
        freeze_min_duration=1,
        silence_min_duration=0.5,
        max_caption_chars=84,
        max_caption_cps=25,
        platform="custom",
        final_resolution=None,
        source_video=None,
        caption_style="classic",
        caption_highlight_color=DEFAULT_HIGHLIGHT,
        caption_word_y=0.8,
    )
    entry = platforms.profile(settings.get("platform", "custom"))
    if entry["loudness"] is not None:
        # A platform profile supplies the delivery loudness unless set explicitly.
        result["loudness_lufs"] = entry["loudness"]["integrated_lufs"]
        result["true_peak_db"] = entry["loudness"]["true_peak_db"]
    result.update(settings)
    result["brand"] = brand
    if result["final_resolution"] not in (None, *platforms.FINAL_RESOLUTIONS):
        raise ValueError("final_resolution must be '1080' or '2160'")
    validate_brand({**brand, "preset": result["preset"], "aspect": result["aspect"]})
    for key in ("title_animation", "normalize_audio"):
        if not isinstance(result[key], bool):
            raise ValueError(key + " must be boolean")
    for key in ("title", "lower_third"):
        _text(result[key], 240)
    _number(result["timeout"], 1, 7200)
    _number(result["loudness_lufs"], -30, -5)
    _number(result["true_peak_db"], -9, -0.1)
    for key in ("black_min_duration", "freeze_min_duration", "silence_min_duration"):
        _number(result[key], 0.01, 60)
    _number(result["max_caption_chars"], 1, 1000)
    _number(result["max_caption_cps"], 1, 100)
    if result["expected_duration"] is not None:
        _number(result["expected_duration"], 0.000001)
    source = result["source_video"]
    if source is not None:
        if not isinstance(source, dict) or set(source) != {
            "width",
            "height",
            "display_aspect_ratio",
        }:
            raise ValueError(
                "source_video needs width, height and display_aspect_ratio"
            )
        for key in ("width", "height"):
            if isinstance(source[key], bool) or not isinstance(source[key], int):
                raise ValueError("source_video width and height must be integers")
            _number(source[key], 1, 100000)
        _number(source["display_aspect_ratio"], 0.0001, 10000)
    return result


def _text(text, maximum):
    if (
        not isinstance(text, str)
        or len(text) > maximum
        or any(ord(c) < 32 and c != "\n" for c in text)
    ):
        raise ValueError("Invalid text or text too long")
    return text


def _captions(captions, duration):
    if captions is None:
        return []
    if not isinstance(captions, list):
        raise ValueError("Captions must be a list")
    previous = 0
    result = []
    for item in captions:
        if not isinstance(item, dict) or set(item) != {"start", "end", "text"}:
            raise ValueError("Each caption needs start, end, text")
        start, end = (
            _number(item["start"], 0, duration),
            _number(item["end"], 0, duration),
        )
        if start < previous or end <= start:
            raise ValueError(
                "Caption times must be ordered, positive and non-overlapping"
            )
        text = _text(item["text"], 1000)
        if not text.strip():
            raise ValueError("Caption text must not be empty")
        result.append(dict(start=start, end=end, text=text))
        previous = end
    return result


def _platform_entry(settings):
    """The settings' platform profile, or None for the 0.1 `custom` behaviour."""
    entry = platforms.profile(settings.get("platform") or "custom")
    return None if entry["frame"] is None else entry


def _dimensions(info, settings):
    if _platform_entry(settings) is not None:
        return platforms.frame_size(
            settings["platform"], settings["preset"], settings.get("final_resolution")
        )
    base = 1080 if settings["preset"] == "preview" else 2160
    aspect = settings["aspect"]
    if aspect == "portrait":
        return base, round(base * 16 / 9)
    if aspect == "landscape":
        return round(base * 16 / 9), base
    if aspect == "square":
        return base, base
    ratio = info["display_aspect_ratio"]
    if ratio >= 1:
        width = round(base * 16 / 9)
        return width, max(2, round(width / ratio / 2) * 2)
    height = round(base * 16 / 9)
    return max(2, round(height * ratio / 2) * 2), height


def _fit_filter(info, width, height):
    content_width, content_height = _content_size(
        info["display_aspect_ratio"], width, height
    )
    return [
        f"scale={content_width}:{content_height}",
        "setsar=1",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
    ]


# Conservative line height (multiple of the font size) for layout boxes.
_LINE = 1.25


def platform_layout(settings, width, height, *, title=None, captions=False):
    """Pixel boxes for title, lower third and caption band inside the safe zone.

    Returns None for `custom`. The renderer draws text from these boxes and the
    quality report recomputes them, so both use one geometry. Widths assume a
    full em per character, which bounds real glyphs from above.
    """
    entry = _platform_entry(settings)
    if entry is None:
        return None
    zone, brand = entry["safe_zone"], settings["brand"]
    margin = brand["safe_margin"]
    pad = max(2.0, 0.01 * min(width, height))
    x0 = width * max(zone["left"], margin) + pad
    x1 = width * (1 - max(zone["right"], margin)) - pad
    y0 = height * max(zone["top"], margin) + pad
    y1 = height * (1 - max(zone["bottom"], margin)) - pad
    available = x1 - x0
    short = min(width, height)
    boxes = {}
    # Captions are a two-line band; platform_caption_cues keeps events to it.
    caption_size = min(
        brand["subtitle_size"] * short / 1080, (y1 - y0) / (2 * _LINE), available
    )
    band = 2 * _LINE * caption_size
    caption_bottom = min(
        max(height * brand["subtitle_y"] + 2 * caption_size, y0 + band), y1
    )
    caption_top = max(caption_bottom - band, y0)
    text = settings["title"] if title is None else title
    if text:
        lines = text.split("\n")
        longest = max(1, max(map(len, lines)))
        size = min(brand["title_size"] * short / 1080, available / longest)
        y = min(max(height * brand["title_y"], y0), y1 - len(lines) * _LINE * size)
        if y < y0:
            y = y0
            size = min(size, (y1 - y0) / (len(lines) * _LINE))
        w = longest * size
        x = {
            "left": x0,
            "center": x0 + (available - w) / 2,
            "right": x1 - w,
        }[brand["alignment"]]
        boxes["title"] = dict(x=x, y=y, w=w, h=len(lines) * _LINE * size, size=size)
    if settings.get("lower_third"):
        h = 0.09 * height
        if y1 - y0 < h + (pad + band if captions else 0) - 1e-9:
            raise ValueError("No safe band is available for lower-third and captions")
        if captions:
            # The lower third sits above the captions; push both down if needed.
            if caption_top - h - pad < y0:
                caption_top = y0 + h + pad
                caption_bottom = caption_top + band
            y = caption_top - h - pad
        else:
            y = min(max(height * (brand["subtitle_y"] - 0.015), y0), y1 - h)
        lines = settings["lower_third"].split("\n")
        longest = max(1, max(map(len, lines)))
        size = min(
            brand["subtitle_size"] * short / 1080,
            (available - 2 * pad) / longest,
            (h - pad) / (len(lines) * _LINE),
        )
        boxes["lower_third"] = dict(
            x=x0,
            y=y,
            w=available,
            h=h,
            size=size,
            text_y=y + (h - len(lines) * _LINE * size) / 2,
        )
    if captions:
        boxes["captions"] = dict(
            x=x0,
            y=caption_top,
            w=available,
            h=caption_bottom - caption_top,
            size=caption_size,
            # Full-em widths bound real glyphs, so lines this long never wrap.
            chars_per_line=max(1, math.floor(available / caption_size)),
        )
    return dict(
        platform=settings["platform"],
        safe=dict(x0=x0, y0=y0, x1=x1, y1=y1),
        boxes=boxes,
    )


def platform_caption_cues(captions, layout, *, measure=None):
    """Split cues so every burned event fits the two-line caption band.

    Words are wrapped at the band's characters per line (longer words are
    broken), lines are paired into events, and each event gets a share of the
    cue's time proportional to its characters. No text is dropped.
    """
    band = (layout or {}).get("boxes", {}).get("captions")
    if band is None:
        return [dict(item) for item in captions]
    import textwrap

    width = band["chars_per_line"]
    result = []
    for item in captions:
        lines = [
            line
            for paragraph in item["text"].split("\n")
            for line in textwrap.wrap(
                paragraph, width, break_long_words=True, break_on_hyphens=False
            )
        ] or [item["text"].strip()]
        if measure is not None:
            from cutroom.captions import wrap_lines

            lines = wrap_lines(item["text"], band["w"] - 16, band["size"], measure)
        events = [
            "\n".join(lines[index : index + 2]) for index in range(0, len(lines), 2)
        ]
        weights = [max(1, len(event.replace("\n", ""))) for event in events]
        total, done = sum(weights), 0
        start, span = item["start"], item["end"] - item["start"]
        for index, (event, weight) in enumerate(zip(events, weights)):
            done += weight
            end = (
                item["end"]
                if index == len(events) - 1
                else (item["start"] + span * done / total)
            )
            result.append(dict(start=start, end=end, text=event))
            start = end
    return result


def safe_zone_findings(boxes, zone, width, height):
    """List every box that reaches into the profile's unsafe margins."""
    limits = dict(
        left=zone["left"] * width,
        right=(1 - zone["right"]) * width,
        top=zone["top"] * height,
        bottom=(1 - zone["bottom"]) * height,
    )
    findings = []
    for name, box in boxes.items():
        sides = [
            side
            for side, outside in (
                ("left", box["x"] < limits["left"] - 0.5),
                ("right", box["x"] + box["w"] > limits["right"] + 0.5),
                ("top", box["y"] < limits["top"] - 0.5),
                ("bottom", box["y"] + box["h"] > limits["bottom"] + 0.5),
            )
            if outside
        ]
        if sides:
            findings.append(dict(box=name, sides=sides, bounds=box))
    return findings


def _platform_text(
    directory, text, filename, color, size, box, alignment, y, *, animated=False
):
    """drawtext placed inside a layout box; real glyphs are narrower than the box."""
    (directory / filename).write_text(text, encoding="utf-8")
    left, width = box["x"], box["w"]
    x = {
        "left": f"{left}",
        "center": f"{left}+({width}-text_w)/2",
        "right": f"{left + width}-text_w",
    }[alignment]
    alpha = ":alpha='min(1,t/0.35)'" if animated else ""
    return (
        f"drawtext=fontfile=font.ttf:textfile={filename}:expansion=none:fontsize={size}"
        f":fontcolor={color}:x={x}:y={y}:fix_bounds=1{alpha}"
    )


def _platform_title(directory, text, settings, layout, *, animated=False):
    brand = settings["brand"]
    box = layout["boxes"]["title"]
    safe = layout["safe"]
    span = dict(x=safe["x0"], w=safe["x1"] - safe["x0"])
    return _platform_text(
        directory,
        text,
        "title.txt",
        brand["title_color"],
        box["size"],
        span,
        brand["alignment"],
        box["y"],
        animated=animated,
    )


def _font(directory, family):
    path = _font_path(family)
    if path is None:
        raise ValueError("Requested local font is unavailable: " + family)
    shutil.copyfile(path, directory / "font.ttf")


def _draw_text(
    directory, text, filename, brand, width, height, *, subtitle=False, animated=False
):
    (directory / filename).write_text(text, encoding="utf-8")
    short = min(width, height)
    size = brand["subtitle_size" if subtitle else "title_size"] * short / 1080
    # Conservative full-em bound keeps even wide glyphs inside the safe area.
    longest = max(map(len, text.split("\n")), default=1)
    size = min(
        size,
        width * (1 - 2 * brand["safe_margin"]) / max(1, longest),
        height
        * (1 - brand["safe_margin"] - brand["subtitle_y" if subtitle else "title_y"])
        / max(2, len(text.split("\n")) * 2),
    )
    margin = width * brand["safe_margin"]
    x = {"left": str(margin), "center": "(w-text_w)/2", "right": f"w-text_w-{margin}"}[
        brand["alignment"]
    ]
    y = height * brand["subtitle_y" if subtitle else "title_y"]
    color = brand["subtitle_color" if subtitle else "title_color"]
    alpha = ":alpha='min(1,t/0.35)'" if animated else ""
    return (
        f"drawtext=fontfile=font.ttf:textfile={filename}:expansion=none:fontsize={size}"
        f":fontcolor={color}:x={x}:y={y}:fix_bounds=1{alpha}"
    )


def _ass(directory, captions, brand, width, height, layout=None):
    def timestamp(value):
        ticks = round(value * 100)
        return f"{ticks // 360000}:{ticks // 6000 % 60:02}:{ticks // 100 % 60:02}.{ticks % 100:02}"

    color = brand["subtitle_color"][1:]
    color = "&H00" + color[4:6] + color[2:4] + color[:2]
    size = brand["subtitle_size"] * min(width, height) / 1080
    margin = round(width * brand["safe_margin"])
    margin_left = margin_right = margin
    margin_vertical = round(height * (1 - brand["subtitle_y"]) - size * 2)
    # Platform cues are pre-wrapped to the band; libass must not add lines.
    wrap_style = 0 if layout is None else 2
    if layout is not None:
        band = layout["boxes"]["captions"]
        size = band["size"]
        margin_left = math.ceil(band["x"])
        margin_right = math.ceil(width - band["x"] - band["w"])
        margin_vertical = math.ceil(height - band["y"] - band["h"])
    alignment = {"left": 1, "center": 2, "right": 3}[brand["alignment"]]
    content = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: {wrap_style}\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{brand['font']},{size},{color},{color},&H00000000,&H80000000,"
        f"0,0,0,0,100,100,0,0,1,2,0,{alignment},{margin_left},{margin_right},"
        f"{margin_vertical},1\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    for item in captions:
        # Fullwidth literal delimiters disable ASS overrides and backslash escapes.
        text = (
            item["text"]
            .replace("\\", "＼")
            .replace("{", "｛")
            .replace("}", "｝")
            .replace("\n", r"\N")
        )
        content += f"Dialogue: 0,{timestamp(item['start'])},{timestamp(item['end'])},Default,,0,0,0,,{text}\n"
    (directory / "captions.ass").write_text(content, encoding="utf-8-sig")
    return "ass=filename=captions.ass:fontsdir=."


def _output_path(output, suffixes):
    original = Path(output)
    path = _path(output, False)
    if original.is_symlink() or path.exists() or path.is_symlink():
        raise FileExistsError(path)
    if path.suffix.lower() not in suffixes:
        raise ValueError("Unsupported output extension")
    if not path.parent.is_dir():
        raise FileNotFoundError(path.parent)
    return path


def _measure_loudness(source, audio_graph, directory, settings):
    """First loudnorm pass over the exact cut audio; returns FFmpeg's measurements."""
    script = directory / "measure.txt"
    script.write_text(
        ";\n".join(
            audio_graph
            + [
                f"[audio]loudnorm=I={settings['loudness_lufs']}:"
                f"TP={settings['true_peak_db']}:LRA=11:print_format=json[measured]"
            ]
        ),
        encoding="utf-8",
    )
    completed = _render_graph(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-v",
            "info",
            "-protocol_whitelist",
            "file",
            "-i",
            str(source),
            "-/filter_complex",
            "measure.txt",
            "-map",
            "[measured]",
            "-f",
            "null",
            "-",
        ],
        cwd=directory,
        timeout=settings["timeout"],
    )
    text = completed.stderr or ""
    start = text.rfind("{")
    end = text.rfind("}")
    try:
        data = json.loads(text[start : end + 1])
        values = {
            key: float(data[key])
            for key in (
                "input_i",
                "input_tp",
                "input_lra",
                "input_thresh",
                "target_offset",
            )
        }
    except (ValueError, KeyError):
        return None
    # Silent or near-silent programs report -inf; linear correction is undefined.
    if not all(math.isfinite(value) for value in values.values()):
        return None
    return values


def _frame_aligned(ranges, rate, source_duration, start_time=None):
    """Snap kept ranges to whole source frames without cumulative drift.

    Each trimmed range otherwise rounds to whole frames independently and the
    concat filter pads audio to match, so many cuts lengthen the program. Frame
    counts follow the rounded running total, keeping the output within half a
    frame of the requested duration. Boundaries sit halfway between frame
    timestamps so small container jitter cannot change which frames are kept.
    Ranges shorter than one frame at their position are dropped.
    """
    numerator, _, denominator = rate.partition("/")
    fps = Fraction(int(numerator), int(denominator or 1))
    try:
        origin = Fraction(str(float(start_time or 0)))
    except ValueError:
        origin = Fraction(0)
    last_frame = int((Fraction(str(source_duration)) - origin) * fps)
    aligned, exact, emitted = [], Fraction(0), 0
    for start, end in ranges:
        exact += Fraction(str(end)) - Fraction(str(start))
        first = max(0, round((Fraction(str(start)) - origin) * fps))
        count = round(exact * fps) - emitted
        stop = min(first + count, last_frame)
        if stop - first < 1:
            continue
        emitted += stop - first

        def edge(frame):
            return max(0.0, float(origin + (frame - Fraction(1, 2)) / fps))

        aligned.append((round(edge(first), 6), round(edge(stop), 6)))
    return aligned


def export_video(
    source,
    segments,
    output,
    settings=None,
    captions=None,
    caption_words=None,
    caption_script=None,
):
    """Render ordered source intervals. Approval is the caller's responsibility.

    Explicit aspects fit/pad, never crop. Source aspect fits its long-side target.
    Result upscaled describes content enlargement, not merely the padded canvas.
    """
    source = _path(source)
    output = _output_path(output, {".mp4", ".mkv", ".mov"})
    script_output = (
        _output_path(caption_script, {".ass"}) if caption_script is not None else None
    )
    settings = _settings(settings)
    info = _probe(source, settings["timeout"])
    if not isinstance(segments, list) or not segments:
        raise ValueError("At least one segment is required")
    previous, duration = 0, 0
    graph, labels, audio_graph, audio_labels = [], [], [], []
    ranges = []
    for item in segments:
        if not isinstance(item, dict) or "start" not in item or "end" not in item:
            raise ValueError("Segments need start and end")
        start, end = (
            _number(item["start"], 0),
            _number(item["end"], 0, info["duration"]),
        )
        if start < previous or end <= start:
            raise ValueError("Segments must be ordered, non-overlapping intervals")
        previous, duration = end, duration + end - start
        ranges.append((start, end))
    video_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    rate = video_stream.get("r_frame_rate")
    constant_rate = bool(
        rate and rate == video_stream.get("avg_frame_rate") and rate != "0/0"
    )
    if constant_rate:
        ranges = _frame_aligned(
            ranges, rate, info["duration"], video_stream.get("start_time")
        )
        if not ranges:
            raise ValueError("Segments are shorter than one video frame")
    # Loudness processing can extend the tail; never let audio outlast the cut.
    program = sum(end - start for start, end in ranges)
    for index, (start, end) in enumerate(ranges):
        graph.append(
            f"[0:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]"
        )
        labels.append(f"[v{index}]")
        if info["has_audio"]:
            trim = (
                f"[0:a:0]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]"
            )
            graph.append(trim)
            labels.append(f"[a{index}]")
            audio_graph.append(trim)
            audio_labels.append(f"[a{index}]")
    graph.append(
        "".join(labels)
        + f"concat=n={len(ranges)}:v=1:a={int(info['has_audio'])}[joined]"
        + ("[audio]" if info["has_audio"] else "")
    )
    if info["has_audio"]:
        audio_graph.append(
            "".join(audio_labels) + f"concat=n={len(ranges)}:v=0:a=1[audio]"
        )
    captions = _captions(captions, duration)
    width, height = _dimensions(info, settings)
    layout = platform_layout(settings, width, height, captions=bool(captions))
    from cutroom import captions as animated_captions

    measure = animated_captions.Measurer(_font_path(settings["brand"]["font"]))
    events = (
        platform_caption_cues(captions, layout, measure=measure) if layout else captions
    )
    animated = settings["caption_style"] != "classic"
    caption_plan = None
    if animated and captions:
        caption_plan = animated_captions.build(
            caption_words
            if caption_words is not None
            else animated_captions.words_from_cues(captions),
            settings,
            width,
            height,
            layout,
            frame_rate=rate or "30/1",
            duration=duration,
        )
        events = caption_plan["events"]
    effects = []
    lower_y = None
    with tempfile.TemporaryDirectory(
        prefix=".postproduction-", dir=output.parent
    ) as temp:
        directory = Path(temp)
        filters = _fit_filter(info, width, height)
        brand = settings["brand"]
        if settings["title"] or settings["lower_third"] or captions:
            _font(directory, brand["font"])
        if settings["title"] and layout is not None:
            filters.append(
                _platform_title(
                    directory,
                    settings["title"],
                    settings,
                    layout,
                    animated=settings["title_animation"],
                )
            )
            effects.append("title_fade" if settings["title_animation"] else "title")
        elif settings["title"]:
            filters.append(
                _draw_text(
                    directory,
                    settings["title"],
                    "title.txt",
                    brand,
                    width,
                    height,
                    animated=settings["title_animation"],
                )
            )
            effects.append("title_fade" if settings["title_animation"] else "title")
        if settings["lower_third"] and layout is not None:
            box = layout["boxes"]["lower_third"]
            lower_y = box["y"] / height
            filters.append(
                f"drawbox=x={box['x']}:y={box['y']}:w={box['w']}:h={box['h']}"
                f":color={brand['graphic_color']}@0.85:t=fill"
            )
            filters.append(
                _platform_text(
                    directory,
                    settings["lower_third"],
                    "lower.txt",
                    brand["subtitle_color"],
                    box["size"],
                    box,
                    brand["alignment"],
                    box["text_y"],
                )
            )
            effects.append("lower_third")
        elif settings["lower_third"]:
            margin = brand["safe_margin"]
            lower_y = max(margin, min(brand["subtitle_y"] - 0.015, 1 - margin - 0.09))
            if captions:
                lower_y = brand["subtitle_y"] - 0.15
                if lower_y < margin:
                    lower_y = (
                        brand["subtitle_y"]
                        + brand["subtitle_size"]
                        * min(width, height)
                        / 1080
                        / height
                        * 2
                        + 0.04
                    )
                if lower_y + 0.09 > 1 - margin:
                    raise ValueError(
                        "No safe band is available for lower-third and captions"
                    )
            lower_brand = {**brand, "subtitle_y": lower_y + 0.015}
            filters.append(
                f"drawbox=x=iw*{margin}:y=ih*{lower_y}:w=iw*{1 - 2 * margin}:"
                f"h=ih*0.09:color={brand['graphic_color']}@0.85:t=fill"
            )
            filters.append(
                _draw_text(
                    directory,
                    settings["lower_third"],
                    "lower.txt",
                    lower_brand,
                    width,
                    height,
                    subtitle=True,
                )
            )
            effects.append("lower_third")
        if caption_plan is not None:
            (directory / "captions.ass").write_text(
                caption_plan["script"], encoding="utf-8-sig"
            )
            filters.append("ass=filename=captions.ass:fontsdir=.")
        elif captions:
            filters.append(_ass(directory, events, brand, width, height, layout))
        normalization_method = "no audio"
        if info["has_audio"] and settings["normalize_audio"]:
            measured = _measure_loudness(source, audio_graph, directory, settings)
            loudnorm = (
                f"loudnorm=I={settings['loudness_lufs']}:"
                f"TP={settings['true_peak_db']}:LRA=11"
            )
            if measured:
                loudnorm += (
                    f":measured_I={measured['input_i']}"
                    f":measured_TP={measured['input_tp']}"
                    f":measured_LRA={measured['input_lra']}"
                    f":measured_thresh={measured['input_thresh']}"
                    f":offset={measured['target_offset']}:linear=true"
                )
                normalization_method = "two-pass measured loudnorm"
            else:
                normalization_method = "single-pass dynamic loudnorm"
            graph.append(
                f"[audio]{loudnorm},aresample=48000,"
                f"atrim=duration={program:.6f}[normalized]"
            )
        elif info["has_audio"]:
            normalization_method = "disabled"
        graph.append("[joined]" + ",".join(filters) + "[video]")
        (directory / "filters.txt").write_text(";\n".join(graph), encoding="utf-8")
        temporary = directory / ("render" + output.suffix)
        args = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-v",
            "error",
            "-n",
            "-protocol_whitelist",
            "file",
            "-i",
            str(source),
            "-filter_complex_threads",
            "2",
            "-/filter_complex",
            "filters.txt",
            "-map",
            "[video]",
        ]
        if info["has_audio"]:
            args += [
                "-map",
                "[normalized]" if settings["normalize_audio"] else "[audio]",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ]
        args += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20" if settings["preset"] == "final" else "25",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
        ]
        video_stream = next(
            (s for s in info.get("streams", []) if s.get("codec_type") == "video"), {}
        )
        rate = video_stream.get("r_frame_rate")
        if rate and rate == video_stream.get("avg_frame_rate") and rate != "0/0":
            # Constant-rate sources: keep the final frame's duration in the container.
            args += ["-fps_mode", "cfr", "-r", rate]
        if output.suffix.lower() in (".mp4", ".mov"):
            args += ["-movflags", "+faststart"]
        _render_graph(
            args + [str(temporary)], cwd=directory, timeout=settings["timeout"]
        )
        result = _probe(temporary, settings["timeout"])
        result.pop("streams")
        os.link(temporary, output)
        if script_output is not None and captions:
            os.link(directory / "captions.ass", script_output)
    extra = {}
    if layout is not None:
        extra = {
            "platform": settings["platform"],
            "final_resolution": settings["final_resolution"],
            "safe_zone_layout": layout,
        }
    source_video = _source_video(info)
    content, factor = _content_upscale(source_video, width, height)
    return {
        **result,
        **extra,
        "output": str(output),
        "preset": settings["preset"],
        "aspect": settings["aspect"],
        "fit": "pad",
        "upscaled": factor > 1.0001,
        "upscale_factor": factor,
        "content_size": content,
        "source_resolution": [info["width"], info["height"]],
        "source_video": source_video,
        "captions_burned": len(captions),
        "caption_events": len(events),
        **(
            {
                "caption_style": settings["caption_style"],
                "caption_measurement": measure.method,
            }
            if animated
            else {}
        ),
        "effects": effects,
        "lower_third_y": lower_y,
        "expected_duration": duration,
        "audio_normalization": {
            "enabled": info["has_audio"] and settings["normalize_audio"],
            "target_lufs": settings["loudness_lufs"],
            "true_peak_db": settings["true_peak_db"],
            "method": normalization_method,
        },
    }


def make_cover(video, output, title="", settings=None, time=0):
    """Extract an actual JPEG/PNG with fitted, safe-area text, never overwrite."""
    video = _path(video)
    output = _output_path(output, {".jpg", ".jpeg", ".png"})
    settings = _settings(settings)
    _text(title, 240)
    info = _probe(video, settings["timeout"])
    time = _number(time, 0, info["duration"])
    if time >= info["duration"]:
        raise ValueError("Cover time must precede end of video")
    width, height = _dimensions(info, settings)
    with tempfile.TemporaryDirectory(
        prefix=".postproduction-", dir=output.parent
    ) as temp:
        directory = Path(temp)
        filters = _fit_filter(info, width, height)
        layout = platform_layout(settings, width, height, title=title)
        if title and layout is not None:
            _font(directory, settings["brand"]["font"])
            filters.append(_platform_title(directory, title, settings, layout))
        elif title:
            _font(directory, settings["brand"]["font"])
            filters.append(
                _draw_text(
                    directory, title, "title.txt", settings["brand"], width, height
                )
            )
        (directory / "filters.txt").write_text(",".join(filters), encoding="utf-8")
        temporary = directory / ("cover" + output.suffix)
        _run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-v",
                "error",
                "-n",
                "-protocol_whitelist",
                "file",
                "-ss",
                str(time),
                "-i",
                str(video),
                "-/vf",
                "filters.txt",
                "-frames:v",
                "1",
                "-threads",
                "2",
                "-update",
                "1",
                str(temporary),
            ],
            cwd=directory,
            timeout=settings["timeout"],
        )
        data = json.loads(
            _run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-of",
                    "json",
                    str(temporary),
                ],
                timeout=settings["timeout"],
            ).stdout
        )
        image = data["streams"][0]
        os.link(temporary, output)
    return dict(
        output=str(output),
        width=int(image["width"]),
        height=int(image["height"]),
        codec=image["codec_name"],
        time=time,
        safe_area=True,
        safe_margin=settings["brand"]["safe_margin"],
        title=title,
    )


def _intervals(log, prefix, duration):
    opened = None
    result = []
    for kind, raw in re.findall(r"\b" + prefix + r"_(start|end):\s*([-+\deE.]+)", log):
        value = min(duration, max(0.0, float(raw)))
        if kind == "start":
            opened = value
        elif opened is not None:
            result.append(
                {"start": opened, "end": value, "duration": max(0.0, value - opened)}
            )
            opened = None
    if opened is not None:
        result.append({"start": opened, "end": duration, "duration": duration - opened})
    return result


def _signal_evidence(path):
    """Read all metadata rows, retaining timing and luma, not the full pixel data."""
    frames = []
    current = None
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            match = re.search(r"frame:(\d+)\s+pts:.*pts_time:([-+\deE.]+)", line)
            if match:
                current = dict(frame=int(match[1]), time=float(match[2]))
                frames.append(current)
            elif current is not None and line.startswith("lavfi.signalstats."):
                key, value = line.strip().split("=", 1)
                current[key.rsplit(".", 1)[-1]] = float(value)
    flashes = []
    for before, frame, after in zip(frames, frames[1:], frames[2:]):
        previous, value, following = before["YAVG"], frame["YAVG"], after["YAVG"]
        if (
            abs(value - previous) > 45
            and abs(value - following) > 45
            and abs(previous - following) < 20
        ):
            flashes.append(
                {
                    "frame": frame["frame"],
                    "time": frame["time"],
                    "luma": value,
                    "previous_luma": previous,
                    "next_luma": following,
                    "reason": "isolated luma excursion; inspect this exact frame",
                }
            )
    return dict(
        frames_scanned=len(frames),
        sampling="every decoded frame",
        first_time=frames[0]["time"] if frames else None,
        last_time=frames[-1]["time"] if frames else None,
        min_luma=min((f["YMIN"] for f in frames), default=None),
        max_luma=max((f["YMAX"] for f in frames), default=None),
        flash_candidates=flashes,
    )


def _frame_rate(info):
    stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    numerator, _, denominator = str(stream.get("avg_frame_rate") or "0/0").partition(
        "/"
    )
    try:
        rate = float(numerator) / float(denominator or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return rate if math.isfinite(rate) and rate > 0 else None


def _platform_checks(add, entry, info, settings, actual_resolution):
    """Frame, length and frame-rate checks against the settings' profile."""
    name = settings["platform"]
    expected = list(_dimensions(info, settings))
    add(
        "platform_frame",
        "pass" if expected == actual_resolution else "fail",
        dict(
            platform=name,
            actual=actual_resolution,
            expected=expected,
            preset=settings["preset"],
            final_resolution=settings["final_resolution"],
            source=entry["frame"]["source"],
        ),
    )
    limit = entry["max_duration_s"]["value"]
    recommended = (entry["recommended_max_s"] or {}).get("value")
    duration = info["duration"]
    add(
        "platform_duration",
        "fail"
        if limit is not None and duration > limit
        else "warning"
        if recommended is not None and duration > recommended
        else "pass",
        dict(
            platform=name,
            actual=duration,
            max_seconds=limit,
            recommended_max_seconds=recommended,
            source=entry["max_duration_s"]["source"],
        ),
    )
    source = settings["source_video"]
    if source is None:
        add(
            "platform_upscale",
            "skip",
            dict(platform=name, reason="Source video size was not supplied"),
        )
    else:
        content, factor = _content_upscale(source, *actual_resolution)
        add(
            "platform_upscale",
            "warning" if factor > 1.0001 else "pass",
            dict(
                platform=name,
                source=[source["width"], source["height"]],
                content=content,
                frame=actual_resolution,
                factor=factor,
                upscaled=factor > 1.0001,
                preset=settings["preset"],
                final_resolution=settings["final_resolution"],
                meaning="the fitted picture is larger than the source pixel grid "
                "(display orientation); detail is interpolated, not recorded",
            ),
        )


def _platform_fps(add, entry, info, settings, deltas):
    """Frame-rate check; NTSC 30000/1001 meets a 30 fps minimum."""
    minimum = entry["min_fps"]["value"]
    rate = _frame_rate(info)
    slowest = variable = None
    if deltas:
        typical = sorted(deltas)[len(deltas) // 2]
        slowest = 1 / max(deltas)
        variable = (
            max(deltas) > typical * 1.05 + 0.0005
            or min(deltas) < typical * 0.95 - 0.0005
        )
    threshold = None if minimum is None else minimum * 1000 / 1001 - 0.001
    low = threshold is not None and (
        rate is None or rate < threshold or bool(variable) and slowest < threshold
    )
    add(
        "platform_fps",
        "skip" if minimum is None else "warning" if low else "pass",
        dict(
            platform=settings["platform"],
            actual=rate,
            min_fps=minimum,
            threshold_fps=threshold,
            min_instantaneous_fps=slowest,
            variable_frame_rate=variable,
            method="average frame rate, and for variable-rate video the "
            "slowest frame interval; NTSC 30000/1001 counts as 30",
            source=entry["min_fps"]["source"],
        ),
    )


def quality_report(
    video, settings=None, captions=None, caption_words=None, caption_script=None
):
    """Decode all frames; findings are heuristics, never editorial certification."""
    from statistics import median

    video = _path(video)
    requested = settings
    settings = _settings(settings)
    checks = []

    def add(name, status, detail):
        checks.append(dict(name=name, status=status, detail=detail))

    limitations = [
        "Heuristics cannot certify absence of single-frame artifacts; review flagged timestamps and the full export.",
        "Static scenes, intentional fades, edits and silence may be legitimate; flagged events require human review.",
        "Safe-area and caption layout estimates do not replace visual glyph/layout inspection.",
        "No-audio sources are valid. Audio checks only apply when an audio stream exists.",
    ]
    try:
        info = _probe(video, settings["timeout"])
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        ValueError,
        KeyError,
    ) as error:
        add(
            "probe",
            "fail",
            {"error": str(error), "stderr": getattr(error, "stderr", "")},
        )
        return dict(checks=checks, passed=False, limitations=limitations)
    add(
        "probe",
        "pass",
        {
            key: info[key]
            for key in ("duration", "codec", "width", "height", "has_audio")
        },
    )
    actual_resolution = [info["width"], info["height"]]
    enforce_resolution = requested is not None and (
        "preset" in requested
        or "aspect" in requested
        or "preset" in requested.get("brand", {})
        or "aspect" in requested.get("brand", {})
    )
    target = list(_dimensions(info, settings)) if enforce_resolution else None
    add(
        "resolution",
        "skip" if target is None else "pass" if target == actual_resolution else "fail",
        dict(
            actual=actual_resolution,
            expected=target,
            fit="pad; no crop",
            reason="Target checked only when preset/aspect is explicitly supplied",
        ),
    )
    limitations.append(
        "Encoded dimensions alone cannot establish source detail or upscaling provenance; use the export report."
    )
    expected = settings["expected_duration"]
    add(
        "duration",
        "fail"
        if expected is not None and abs(info["duration"] - expected) > 0.12
        else "pass",
        dict(actual=info["duration"], expected=expected, tolerance_seconds=0.12),
    )
    entry = _platform_entry(settings)
    if entry is not None:
        _platform_checks(add, entry, info, settings, actual_resolution)
    deltas = None
    points = []
    with tempfile.TemporaryDirectory(
        prefix=".postproduction-qa-", dir=os.environ.get("TMPDIR")
    ) as temp:
        directory = Path(temp)
        filters = (
            f"blackdetect=d={settings['black_min_duration']}:pix_th=0.10:pic_th=0.98,"
            f"freezedetect=n=-60dB:d={settings['freeze_min_duration']},"
            "signalstats,metadata=mode=print:file=frames.txt"
        )
        (directory / "filters.txt").write_text(filters, encoding="utf-8")
        try:
            decoded = _run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-v",
                    "info",
                    "-xerror",
                    "-protocol_whitelist",
                    "file",
                    "-i",
                    str(video),
                    "-map",
                    "0:v:0",
                    "-an",
                    "-/vf",
                    "filters.txt",
                    "-fps_mode",
                    "passthrough",
                    "-f",
                    "null",
                    "-",
                ],
                cwd=directory,
                timeout=settings["timeout"],
            )
            evidence = _signal_evidence(directory / "frames.txt")
            add("decode", "pass", {"method": "full FFmpeg decode with -xerror"})
            add(
                "signalstats",
                "warning" if evidence["flash_candidates"] else "pass",
                evidence,
            )
            black = _intervals(decoded.stderr, "black", info["duration"])
            frozen = _intervals(decoded.stderr, "freeze", info["duration"])
            add(
                "black_frames",
                "warning" if black else "pass",
                {"intervals": black, "meaning": "near-black frame runs"},
            )
            add(
                "freeze_frames",
                "warning" if frozen else "pass",
                {"intervals": frozen, "meaning": "near-identical frame runs"},
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            add(
                "decode",
                "fail",
                {"error": str(error), "stderr": getattr(error, "stderr", "")},
            )
        try:
            frames = json.loads(
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
                        "frame=best_effort_timestamp_time,duration_time,pkt_duration_time",
                        "-of",
                        "json",
                        str(video),
                    ],
                    timeout=settings["timeout"],
                ).stdout
            )["frames"]
            points = [
                float(f["best_effort_timestamp_time"])
                for f in frames
                if "best_effort_timestamp_time" in f
            ]
            deltas = [b - a for a, b in zip(points, points[1:]) if b > a]
            typical = median(deltas) if deltas else info["duration"]
            gaps = [
                {"after": a, "before": b, "seconds": b - a}
                for a, b in zip(points, points[1:])
                if b - a > typical * 1.5 + 0.001 or b <= a
            ]
            if points and points[0] > max(0.1, typical * 1.5):
                gaps.insert(0, dict(after=0, before=points[0], seconds=points[0]))
            if points and info["duration"] - points[-1] > max(0.15, typical * 2):
                gaps.append(
                    dict(
                        after=points[-1],
                        before=info["duration"],
                        seconds=info["duration"] - points[-1],
                    )
                )
            add(
                "frame_timing",
                "warning" if gaps else "pass",
                dict(
                    frames=len(points),
                    typical_frame_seconds=typical,
                    gaps=gaps,
                    meaning="gaps above 1.5x median frame interval; VFR may be intentional",
                ),
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            ValueError,
            KeyError,
        ) as error:
            add("frame_timing", "fail", {"error": str(error)})
    if entry is not None:
        _platform_fps(add, entry, info, settings, deltas)
    if not info["has_audio"]:
        add("audio", "skip", {"reason": "No audio stream; no silence added"})
        if entry is not None:
            add("platform_loudness", "skip", {"reason": "No audio stream"})
    else:
        try:
            analysis = _run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-v",
                    "info",
                    "-xerror",
                    "-protocol_whitelist",
                    "file",
                    "-i",
                    str(video),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-af",
                    f"volumedetect,ebur128=peak=true,silencedetect=noise=-50dB:d={settings['silence_min_duration']}",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=settings["timeout"],
            ).stderr

            def measured(pattern):
                values = re.findall(pattern, analysis)
                if not values:
                    return None
                value = float(values[-1])
                return value if math.isfinite(value) else None

            integrated = measured(r"I:\s*([-+\d.inf]+) LUFS")
            peak = measured(r"Peak:\s*([-+\d.inf]+) dBFS")
            volume = measured(r"max_volume:\s*([-+\d.inf]+) dB")
            mean = measured(r"mean_volume:\s*([-+\d.inf]+) dB")
            add(
                "audio",
                "pass" if volume is not None else "fail",
                dict(
                    integrated_lufs=integrated,
                    true_peak_dbfs=peak,
                    max_volume_db=volume,
                    mean_volume_db=mean,
                    method="full-track volumedetect and ebur128=true-peak scan; first audio stream",
                ),
            )
            clipping = (
                volume is not None and volume >= -0.1 or peak is not None and peak >= 0
            )
            add(
                "audio_clipping",
                "warning" if clipping else "pass",
                dict(
                    max_volume_db=volume,
                    true_peak_dbfs=peak,
                    meaning="near-full-scale samples or true-peak overs; possible clipping, not proof of waveform damage",
                ),
            )
            loudness_issue = (
                integrated is not None
                and abs(integrated - settings["loudness_lufs"]) > 1
                or peak is not None
                and peak > settings["true_peak_db"] + 0.3
            )
            add(
                "audio_loudness",
                "warning" if loudness_issue else "pass",
                dict(
                    integrated_lufs=integrated,
                    target_lufs=settings["loudness_lufs"],
                    true_peak_dbfs=peak,
                    target_peak_db=settings["true_peak_db"],
                    tolerance_lu=1,
                ),
            )
            if entry is not None:
                target = entry["loudness"]
                off_target = (
                    integrated is None
                    or abs(integrated - settings["loudness_lufs"]) > 1
                    or peak is not None
                    and peak > settings["true_peak_db"] + 0.3
                )
                add(
                    "platform_loudness",
                    "warning" if off_target else "pass",
                    dict(
                        platform=settings["platform"],
                        integrated_lufs=integrated,
                        target_lufs=settings["loudness_lufs"],
                        true_peak_dbfs=peak,
                        target_peak_db=settings["true_peak_db"],
                        tolerance_lu=1,
                        source=target["source"],
                    ),
                )
            silences = _intervals(analysis, "silence", info["duration"])
            add(
                "audio_gaps",
                "warning" if silences else "pass",
                dict(
                    intervals=silences,
                    threshold_db=-50,
                    meaning="potential unexpected gaps; intentional silence requires editorial confirmation",
                ),
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            add(
                "audio",
                "fail",
                {"error": str(error), "stderr": getattr(error, "stderr", "")},
            )
    issues = []
    layout = None
    try:
        if entry is not None:
            layout = platform_layout(
                settings, info["width"], info["height"], captions=bool(captions)
            )
        valid = _captions(captions, info["duration"])
        brand = settings["brand"]
        size = brand["subtitle_size"] * min(info["width"], info["height"]) / 1080
        available = info["width"] * (1 - 2 * brand["safe_margin"])
        if entry is not None:
            zone = entry["safe_zone"]
            available = info["width"] * (
                1
                - max(zone["left"], brand["safe_margin"])
                - max(zone["right"], brand["safe_margin"])
            )
        for index, item in enumerate(valid):
            cps = len(item["text"]) / (item["end"] - item["start"])
            estimated_lines = sum(
                max(1, math.ceil(len(line) * size / available))
                for line in item["text"].split("\n")
            )
            if layout is not None:
                # Platform renders split long cues into two-line events.
                estimated_lines = max(
                    len(event["text"].split("\n"))
                    for event in platform_caption_cues([item], layout)
                )
            if (
                len(item["text"]) > settings["max_caption_chars"]
                or cps > settings["max_caption_cps"]
                or estimated_lines > 2
            ):
                issues.append(
                    dict(
                        index=index,
                        start=item["start"],
                        end=item["end"],
                        text=item["text"],
                        characters=len(item["text"]),
                        cps=cps,
                        estimated_lines=estimated_lines,
                        reason="caption length, reading speed, or two-line safe-area limit",
                    )
                )
    except ValueError as error:
        issues.append(dict(reason=str(error)))
    add(
        "captions",
        "fail" if issues else "pass",
        dict(
            issues=issues,
            max_chars=settings["max_caption_chars"],
            max_cps=settings["max_caption_cps"],
        ),
    )
    add(
        "safe_area",
        "pass",
        dict(
            margin=settings["brand"]["safe_margin"],
            title_y=settings["brand"]["title_y"],
            subtitle_y=settings["brand"]["subtitle_y"],
            method="validated normalized positions; renderer auto-fits title; caption estimates above",
        ),
    )
    if entry is not None:
        try:
            layout = platform_layout(
                settings, info["width"], info["height"], captions=bool(captions)
            )
            findings = safe_zone_findings(
                layout["boxes"], entry["safe_zone"], info["width"], info["height"]
            )
            add(
                "safe_zone",
                "fail" if findings else "pass",
                dict(
                    platform=settings["platform"],
                    zone={
                        side: entry["safe_zone"][side]
                        for side in ("top", "bottom", "left", "right")
                    },
                    boxes=layout["boxes"],
                    findings=findings,
                    source=entry["safe_zone"]["source"],
                    method="render geometry of title, lower third and caption band; "
                    "glyph pixels are not inspected",
                ),
            )
        except ValueError as error:
            add("safe_zone", "fail", {"error": str(error)})
    if settings["caption_style"] != "classic" and captions:
        from cutroom import captions as animated_captions

        words = (
            caption_words
            if caption_words is not None
            else animated_captions.words_from_cues(captions)
        )
        if caption_script is not None:
            script = _path(caption_script).read_text(encoding="utf-8-sig")
        else:
            script = animated_captions.build(
                words,
                settings,
                info["width"],
                info["height"],
                layout,
                frame_rate=str(_frame_rate(info) or 30),
                duration=info["duration"],
            )["script"]
        parsed = animated_captions.parse_script(script)
        # A script made for another frame size (a preview's script checked
        # against a final) cannot vouch for this video's timing or placement.
        size_error = (
            None
            if parsed["play_res"] == (info["width"], info["height"])
            else "Caption script was made for frame size {}x{}, not this video's "
            "{}x{}".format(*parsed["play_res"], info["width"], info["height"])
        )
        timing = animated_captions.timing_report(parsed, words, points)
        status = timing.pop("status")
        if size_error:
            status = "fail"
            timing["error"] = size_error
        timing["script"] = "render" if caption_script is not None else "reconstructed"
        add("caption_timing", status, timing)
        measure = animated_captions.Measurer(_font_path(settings["brand"]["font"]))
        boxes = animated_captions.event_boxes(parsed, measure)
        zone = (
            entry["safe_zone"]
            if entry
            else {
                side: settings["brand"]["safe_margin"]
                for side in ("top", "bottom", "left", "right")
            }
        )
        findings = safe_zone_findings(
            {str(i): box for i, box in enumerate(boxes)},
            zone,
            info["width"],
            info["height"],
        )
        if size_error:
            findings = [dict(error=size_error)]
        add(
            "caption_bounds",
            "fail" if findings else "pass",
            dict(
                boxes=boxes,
                findings=findings,
                measurement=measure.method,
                method="ASS event positions and measured glyph bounds, not decoded pixels",
            ),
        )
    return dict(
        checks=checks,
        passed=all(c["status"] in ("pass", "skip") for c in checks),
        limitations=limitations,
    )
