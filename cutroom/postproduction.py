"""Local, no-overwrite postproduction using FFmpeg and the standard library."""

import copy
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


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


def default_brand():
    """Positions/margins are fractions; font sizes use a 1080-pixel short side."""
    return dict(
        font="Arial",
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
    rotation = next(
        (
            item.get("rotation", 0)
            for item in video.get("side_data_list", [])
            if "rotation" in item
        ),
        video.get("tags", {}).get("rotate", 0),
    )
    if abs(float(rotation)) % 180 == 90:
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
    }
    if settings is None:
        settings = {}
    if not isinstance(settings, dict) or set(settings) - allowed:
        raise ValueError("Unknown settings fields")
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
    )
    result.update(settings)
    result["brand"] = brand
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


def _dimensions(info, settings):
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
    ratio = info["display_aspect_ratio"]
    content_width = max(2, min(width, math.floor(height * ratio / 2) * 2))
    content_height = max(2, min(height, math.floor(width / ratio / 2) * 2))
    return [
        f"scale={content_width}:{content_height}",
        "setsar=1",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
    ]


def _font(directory, family):
    paths = {
        "Arial": ["C:/Windows/Fonts/arial.ttf"],
        "DejaVu Sans": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
        "Liberation Sans": [
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"
        ],
    }
    path = next((Path(p) for p in paths[family] if Path(p).is_file()), None)
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


def _ass(directory, captions, brand, width, height):
    def timestamp(value):
        ticks = round(value * 100)
        return f"{ticks // 360000}:{ticks // 6000 % 60:02}:{ticks // 100 % 60:02}.{ticks % 100:02}"

    color = brand["subtitle_color"][1:]
    color = "&H00" + color[4:6] + color[2:4] + color[:2]
    size = brand["subtitle_size"] * min(width, height) / 1080
    margin = round(width * brand["safe_margin"])
    alignment = {"left": 1, "center": 2, "right": 3}[brand["alignment"]]
    content = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{brand['font']},{size},{color},{color},&H00000000,&H80000000,"
        f"0,0,0,0,100,100,0,0,1,2,0,{alignment},{margin},{margin},"
        f"{round(height * (1 - brand['subtitle_y']) - size * 2)},1\n"
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


def export_video(source, segments, output, settings=None, captions=None):
    """Render ordered source intervals. Approval is the caller's responsibility.

    Explicit aspects fit/pad, never crop. Source aspect fits its long-side target.
    Result upscaled describes content enlargement, not merely the padded canvas.
    """
    source = _path(source)
    output = _output_path(output, {".mp4", ".mkv", ".mov"})
    settings = _settings(settings)
    info = _probe(source, settings["timeout"])
    if not isinstance(segments, list) or not segments:
        raise ValueError("At least one segment is required")
    previous, duration = 0, 0
    graph, labels = [], []
    for index, item in enumerate(segments):
        if not isinstance(item, dict) or "start" not in item or "end" not in item:
            raise ValueError("Segments need start and end")
        start, end = (
            _number(item["start"], 0),
            _number(item["end"], 0, info["duration"]),
        )
        if start < previous or end <= start:
            raise ValueError("Segments must be ordered, non-overlapping intervals")
        previous, duration = end, duration + end - start
        graph.append(
            f"[0:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]"
        )
        labels.append(f"[v{index}]")
        if info["has_audio"]:
            graph.append(
                f"[0:a:0]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]"
            )
            labels.append(f"[a{index}]")
    graph.append(
        "".join(labels)
        + f"concat=n={len(segments)}:v=1:a={int(info['has_audio'])}[joined]"
        + ("[audio]" if info["has_audio"] else "")
    )
    captions = _captions(captions, duration)
    width, height = _dimensions(info, settings)
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
        if settings["title"]:
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
        if settings["lower_third"]:
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
        if captions:
            filters.append(_ass(directory, captions, brand, width, height))
        if info["has_audio"] and settings["normalize_audio"]:
            graph.append(
                f"[audio]loudnorm=I={settings['loudness_lufs']}:TP={settings['true_peak_db']}:LRA=11,"
                "aresample=48000[normalized]"
            )
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
        if output.suffix.lower() in (".mp4", ".mov"):
            args += ["-movflags", "+faststart"]
        _render_graph(
            args + [str(temporary)], cwd=directory, timeout=settings["timeout"]
        )
        result = _probe(temporary, settings["timeout"])
        result.pop("streams")
        os.link(temporary, output)
    return {
        **result,
        "output": str(output),
        "preset": settings["preset"],
        "aspect": settings["aspect"],
        "fit": "pad",
        "upscaled": min(width / info["width"], height / info["height"]) > 1.0001,
        "source_resolution": [info["width"], info["height"]],
        "captions_burned": len(captions),
        "effects": effects,
        "lower_third_y": lower_y,
        "expected_duration": duration,
        "audio_normalization": {
            "enabled": info["has_audio"] and settings["normalize_audio"],
            "target_lufs": settings["loudness_lufs"],
            "true_peak_db": settings["true_peak_db"],
            "method": "single-pass dynamic loudnorm"
            if info["has_audio"]
            else "no audio",
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
        if title:
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


def quality_report(video, settings=None, captions=None):
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
    if not info["has_audio"]:
        add("audio", "skip", {"reason": "No audio stream; no silence added"})
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
    try:
        valid = _captions(captions, info["duration"])
        brand = settings["brand"]
        size = brand["subtitle_size"] * min(info["width"], info["height"]) / 1080
        available = info["width"] * (1 - 2 * brand["safe_margin"])
        for index, item in enumerate(valid):
            cps = len(item["text"]) / (item["end"] - item["start"])
            estimated_lines = sum(
                max(1, math.ceil(len(line) * size / available))
                for line in item["text"].split("\n")
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
    return dict(
        checks=checks,
        passed=all(c["status"] in ("pass", "skip") for c in checks),
        limitations=limitations,
    )
