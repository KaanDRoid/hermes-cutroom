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
