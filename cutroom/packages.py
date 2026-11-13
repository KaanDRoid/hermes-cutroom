"""Local delivery packages: an approved final, a cover, post text and checksums.

A package is a new folder under ``<workspace>/projects/<id>/packages/`` named
``<platform>-<UTC timestamp>``. It holds the final video (a hard link when the
workspace volume allows it, otherwise a copy; the original is never moved or
changed), a cover image for the platform, ``post.txt`` with the text to paste,
``README.txt`` in plain words and ``manifest.json`` with the size and SHA-256 of
every other file. Nothing is uploaded or posted.

Post text is checked against the sourced limits in ``platforms.py``. Counting
follows each platform's unit: Instagram counts characters, TikTok UTF-16 code
units and YouTube description bytes (UTF-8). A package that breaks a hard limit
is refused with a sentence that names the field and the limit.
"""

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .platforms import profile
from .project import file_digest

FORMAT = "cutroom-delivery-package"
NOTICE = "Nothing has been posted. Upload these files yourself."
PACKAGE_NAME = re.compile(
    r"^[a-z_]{1,32}-\d{8}-\d{6}(?:-\d{1,3})?(?:-[a-z0-9-]{1,40})?$"
)
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
MANIFEST_MAX_BYTES = 1_000_000
COVER_MAX_BYTES = 2_000_000
# Bounds on stored text; platform limits are checked separately and are smaller.
TITLE_INPUT = 1000
CAPTION_INPUT = 20000
HASHTAG_INPUT = 100
HASHTAG_CHARS = 100
SUGGESTED_CAPTION = 300
PLATFORMS = ("instagram_reels", "youtube_shorts", "tiktok", "youtube")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u2028\u2029]")
_HASHTAG = re.compile(r"(?<![\w&])#\w+")
_MENTION = re.compile(r"(?<![\w@])@[\w.]+")
_TAG_SHAPE = re.compile(r"^#\w{1,99}$")


def _platform(name):
    if name not in PLATFORMS:
        raise ValueError(
            "Delivery packages need a platform profile; choose Instagram Reels, "
            "YouTube Shorts, TikTok or YouTube first"
        )
    return profile(name)


def post_limits(platform):
    """Text limits of one platform, with their sources, for checks and the UI."""
    entry = _platform(platform)
    text = entry["text"]
    common = {
        "label": entry["label"],
        "source": text["source"],
        "checked": text["checked"],
        "note": text.get("note", ""),
    }
    if platform in {"youtube", "youtube_shorts"}:
        return {
            **common,
            "fields": ["title", "description"],
            "title": {
                "max": text["title_chars"],
                "unit": "characters",
                "required": True,
            },
            "description": {"max": text["description_bytes"], "unit": "bytes"},
            "hashtags": {"max": text["hashtags"], "source": text["hashtags_source"]},
            "mentions": None,
            "forbidden": text["forbidden"],
        }
    unit = "utf16" if platform == "tiktok" else "characters"
    hashtags = text.get("hashtags")
    mentions = text.get("mentions")
    return {
        **common,
        "fields": ["caption"],
        "caption": {"max": text["caption_chars"], "unit": unit},
        "hashtags": {"max": hashtags} if hashtags else None,
        "mentions": {"max": mentions} if mentions else None,
        "forbidden": "",
    }


def measure(text, unit):
    if unit == "bytes":
        return len(text.encode("utf-8"))
    if unit == "utf16":
        return len(text.encode("utf-16-le")) // 2
    return len(text)


def _plain(value, name, limit, *, lines):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    value = value.strip().replace("\r\n", "\n")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name} contains invalid text") from error
    if len(value) > limit:
        raise ValueError(f"{name} must be at most {limit:,} characters")
    if _CONTROL.search(value) or (not lines and ("\n" in value or "\t" in value)):
        raise ValueError(f"{name} contains characters that cannot be posted")
    return value


def normalize_post(value):
    """Validate the stored post text: title, caption and a list of hashtags."""
    if not isinstance(value, dict):
        raise ValueError("Post text must be an object with title, caption and hashtags")
    unknown = set(value) - {"title", "caption", "hashtags"}
    if unknown:
        raise ValueError("Unsupported post fields: " + ", ".join(sorted(unknown)))
    post = {
        "title": _plain(value.get("title", ""), "Title", TITLE_INPUT, lines=False),
        "caption": _plain(
            value.get("caption", ""), "Caption", CAPTION_INPUT, lines=True
        ).replace("\r\n", "\n"),
        "hashtags": [],
    }
    tags = value.get("hashtags", [])
    if not isinstance(tags, list) or len(tags) > HASHTAG_INPUT:
        raise ValueError(f"Hashtags must be a list of at most {HASHTAG_INPUT}")
    seen = set()
    for tag in tags:
        if not isinstance(tag, str):
            raise ValueError("Each hashtag must be text")
        tag = tag.strip()
        tag = tag if tag.startswith("#") else "#" + tag
        if not _TAG_SHAPE.fullmatch(tag) or len(tag) > HASHTAG_CHARS:
            raise ValueError(
                f"“{tag[:40]}” is not a hashtag: use one word without spaces, # or < >"
            )
        if tag.casefold() not in seen:
            seen.add(tag.casefold())
            post["hashtags"].append(tag)
    return post


def compose(platform, post, chapters_text=""):
    """The text a person pastes: a caption, or a YouTube title and description."""
    post = {"title": "", "caption": "", "hashtags": [], **post}
    tags = " ".join(post["hashtags"])
    if platform in {"youtube", "youtube_shorts"}:
        parts = [post["caption"].strip(), chapters_text.strip(), tags]
        return {
            "title": post["title"].strip(),
            "description": "\n\n".join(part for part in parts if part),
        }
    _platform(platform)
    parts = [post["caption"].strip(), tags]
    return {"caption": "\n\n".join(part for part in parts if part)}


def _n(value):
    return f"{value:,}"


def check_post(platform, post, chapters_text=""):
    """Counts per field and a plain sentence for every broken limit."""
    limits = post_limits(platform)
    label = limits["label"]
    text = compose(platform, post, chapters_text)
    fields, problems = {}, []
    unit_words = {"characters": "characters", "utf16": "characters", "bytes": "bytes"}
    for name in limits["fields"]:
        rule = limits[name]
        count = measure(text[name], rule["unit"])
        fields[name] = {"count": count, "max": rule["max"], "unit": rule["unit"]}
        if count > rule["max"]:
            unit = unit_words[rule["unit"]]
            extra = ""
            if rule["unit"] == "utf16":
                extra = " (TikTok counts in UTF-16 units: emoji and some symbols count as two)"
            elif rule["unit"] == "bytes":
                extra = " (letters outside English can take 2 to 4 bytes each)"
            what = "description" if name == "description" else name
            problems.append(
                f"The {what} has {_n(count)} {unit}; {label} allows at most "
                f"{_n(rule['max'])} {unit}{extra}. Shorten it by "
                f"{_n(count - rule['max'])}."
            )
        if rule.get("required") and not text[name]:
            problems.append(f"{label} needs a title.")
    combined = "\n".join(text.values())
    hashtags = len(_HASHTAG.findall(combined))
    fields["hashtags"] = {
        "count": hashtags,
        "max": (limits["hashtags"] or {}).get("max"),
    }
    if limits["hashtags"] and hashtags > limits["hashtags"]["max"]:
        problems.append(
            f"There are {hashtags} hashtags; {label} allows at most "
            f"{limits['hashtags']['max']}."
            + (
                " With more, YouTube ignores all of them."
                if platform in {"youtube", "youtube_shorts"}
                else ""
            )
        )
    if limits["mentions"]:
        mentions = len(_MENTION.findall(combined))
        fields["mentions"] = {"count": mentions, "max": limits["mentions"]["max"]}
        if mentions > limits["mentions"]["max"]:
            problems.append(
                f"There are {mentions} @ mentions; {label} allows at most "
                f"{limits['mentions']['max']}."
            )
    for name in limits["fields"]:
        if any(mark in text[name] for mark in limits["forbidden"]):
            problems.append(f"The {name} cannot contain < or >; {label} rejects them.")
    return {"text": text, "fields": fields, "problems": problems}


def _trim(text, limit):
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + "…"


def suggest_post(platform, name, title, words):
    """Default text from the project, without a network or invented claims.

    The title is the project's title setting or name; the caption is the first
    sentences the speaker says in the edit (at most 300 characters). Hashtags
    stay empty: choosing them is the person's call.
    """
    limit = post_limits(platform)
    text, caption = "", ""
    for word in words:
        token = str(word.get("text", "")).strip()
        if not token:
            continue
        text = f"{text} {token}".strip()
        if len(text) > SUGGESTED_CAPTION:
            break
        if token.endswith((".", "!", "?")):
            caption = text
            if len(caption) >= 120:
                break
    caption = _trim(caption or text, SUGGESTED_CAPTION)
    title = (title or name or "").strip().replace("\n", " ")
    if limit.get("forbidden"):
        title = re.sub(r"[<>]", "", title)
        caption = re.sub(r"[<>]", "", caption)
    if "title" in limit:
        title = _trim(title, limit["title"]["max"])
    return normalize_post(
        {"title": title[:TITLE_INPUT], "caption": caption, "hashtags": []}
    )


def jpeg_size(path):
    """(width, height) from a JPEG's start-of-frame marker."""
    with Path(path).open("rb") as stream:
        if stream.read(2) != b"\xff\xd8":
            raise ValueError("Not a JPEG file")
        while True:
            marker = stream.read(2)
            if len(marker) < 2 or marker[0] != 0xFF:
                raise ValueError("JPEG has no frame header")
            if marker[1] in (0xD8, 0x01) or 0xD0 <= marker[1] <= 0xD7:
                continue
            length = int.from_bytes(stream.read(2), "big")
            if marker[1] in (
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            ):
                data = stream.read(5)
                return int.from_bytes(data[3:5], "big"), int.from_bytes(
                    data[1:3], "big"
                )
            stream.seek(length - 2, 1)


def make_cover(video, time, output, size, timeout=120):
    """One centred, cropped frame of ``video`` at ``time`` as a JPEG under 2 MB."""
    from .longform import _run

    width, height = size
    crop = (
        f"crop='min(iw,ih*{width}/{height})':'min(ih,iw*{height}/{width})',"
        f"scale={width}:{height}:flags=lanczos,setsar=1"
    )
    for quality in (2, 4, 7, 10):
        _run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-protocol_whitelist",
                "file",
                "-ss",
                f"{max(0.0, time):.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-an",
                "-vf",
                crop,
                "-q:v",
                str(quality),
                "-f",
                "image2",
                "-c:v",
                "mjpeg",
                str(output),
            ],
            timeout,
        )
        if Path(output).stat().st_size <= COVER_MAX_BYTES:
            return {"width": width, "height": height, "quality": quality}
    raise RuntimeError("The cover could not be kept under 2 MB")


def clock(seconds):
    total = int(max(0.0, seconds) + 1e-6)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def new_directory(root, platform, now=None):
    """A new, empty package folder; earlier packages are never reused."""
    now = now or datetime.now(timezone.utc)
    root.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    for attempt in range(1, 100):
        name = f"{platform}-{stamp}" + ("" if attempt == 1 else f"-{attempt}")
        try:
            (root / name).mkdir()
            return root / name
        except FileExistsError:
            continue
    raise RuntimeError("Too many packages in one second; try again")


def place_video(source, target):
    """Hard-link the final when possible, otherwise copy it. Never moves it."""
    try:
        os.link(source, target)
        return "hardlink"
    except OSError:
        with Path(source).open("rb") as incoming, Path(target).open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
        return "copy"


def copy_file(source, target):
    with Path(source).open("rb") as incoming, Path(target).open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)


def _write_text(path, text):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def post_file(platform, check, *, cover_line, extra_lines=()):
    limits = post_limits(platform)
    label = limits["label"]
    fields = check["fields"]
    lines = [
        f"{label}: text to paste",
        NOTICE,
        "",
    ]
    tags = fields["hashtags"]
    tag_note = (
        f", {tags['count']} of {tags['max']} hashtags"
        if tags.get("max")
        else f", {tags['count']} hashtags"
    )
    for name in limits["fields"]:
        field = fields[name]
        unit = "bytes" if field["unit"] == "bytes" else "characters"
        heading = name.capitalize()
        note = tag_note if name in {"caption", "description"} else ""
        lines += [
            f"{heading} ({_n(field['count'])} of {_n(field['max'])} {unit}{note}):",
            "-----",
            check["text"][name],
            "-----",
            "",
        ]
    lines.append(cover_line)
    lines += list(extra_lines)
    lines += [
        "",
        f"Limits checked against {limits['source']} on {limits['checked']}.",
    ]
    return "\n".join(lines) + "\n"


def readme_file(label, files, project_name, linked=False):
    lines = [
        f"Cutroom delivery package for {label}",
        "",
        NOTICE,
        "",
        f"Project: {project_name}",
        "",
        "Files:",
    ]
    lines += [f"- {name}: {role}" for name, role in files]
    lines += [
        "- manifest.json: the size and SHA-256 checksum of every file above.",
        "",
        "To check that nothing changed, use Check package in Cutroom Studio (Export).",
    ]
    if linked:
        lines += [
            "video.mp4 shares its storage with the approved final in Cutroom, so",
            "it takes no extra space. To edit or trim it, make a copy first;",
            "changing this file changes the final too.",
        ]
    lines += [
        "Cutroom made these files on this computer. It did not upload, share or",
        "post anything.",
    ]
    return "\n".join(lines) + "\n"


def file_entries(directory, roles):
    files = {}
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        if path.name == "manifest.json":
            continue
        files[path.name] = {
            "size": path.stat().st_size,
            "sha256": file_digest(path),
            "role": roles.get(path.name, ""),
        }
    return files


def write_manifest(directory, manifest):
    _write_text(
        directory / "manifest.json",
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )


def summary(directory, manifest):
    """The shape the REST API, agent tool and Desktop page show for a package."""
    files = manifest.get("files") if isinstance(manifest, dict) else None
    files = files if isinstance(files, dict) else {}
    if (directory / "manifest.json").is_file():
        files = {
            **files,
            "manifest.json": {
                "size": (directory / "manifest.json").stat().st_size,
                "sha256": file_digest(directory / "manifest.json"),
                "role": "checksum manifest (not self-hashed)",
            },
        }
    return {
        "name": directory.name,
        "directory": str(directory),
        "platform": manifest.get("platform"),
        "created_at": manifest.get("created_at"),
        "posted": False,
        "video_link": manifest.get("video_link"),
        "notice": NOTICE,
        "files": [
            {
                "name": name,
                "size": entry.get("size"),
                "sha256": entry.get("sha256"),
                "role": entry.get("role", ""),
            }
            for name, entry in sorted(files.items())
            if isinstance(entry, dict)
        ],
    }


def read_manifest(directory):
    path = directory / "manifest.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("manifest.json is missing")
    if path.stat().st_size > MANIFEST_MAX_BYTES:
        raise ValueError("manifest.json is too large")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ValueError("manifest.json is not a Cutroom package manifest")
    if (
        not isinstance(manifest.get("files"), dict)
        or not 1 <= len(manifest["files"]) <= 32
    ):
        raise ValueError("manifest.json must list 1 to 32 files")
    return manifest


def verify(directory):
    """Re-hash every file and report each difference in plain words."""
    directory = Path(directory)
    problems = []
    try:
        manifest = read_manifest(directory)
    except (OSError, ValueError, UnicodeDecodeError) as error:
        problem = (
            str(error) if isinstance(error, ValueError) else "missing or unreadable"
        )
        if isinstance(error, json.JSONDecodeError):
            problem = "manifest.json is unreadable"
        return {
            "ok": False,
            "directory": str(directory),
            "checked": 0,
            "problems": [{"file": "manifest.json", "problem": problem}],
            "summary": "The package cannot be checked: " + problem + ".",
        }
    listed = manifest["files"]
    checked = 0
    for name, entry in sorted(listed.items()):
        if (
            not FILE_NAME.fullmatch(name)
            or name == "manifest.json"
            or not isinstance(entry, dict)
            or type(entry.get("size")) is not int
            or entry["size"] < 0
            or not isinstance(entry.get("sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])
        ):
            problems.append(
                {"file": name[:100], "problem": "is not a valid file entry"}
            )
            continue
        path = directory / name
        if path.is_symlink() or not path.is_file():
            problems.append({"file": name, "problem": "is missing"})
            continue
        checked += 1
        size = path.stat().st_size
        if size != entry.get("size"):
            problems.append(
                {
                    "file": name,
                    "problem": f"size changed ({_n(size)} bytes, expected "
                    f"{_n(entry.get('size') or 0)}); contents changed (checksum differs)",
                }
            )
        elif file_digest(path) != entry.get("sha256"):
            problems.append(
                {"file": name, "problem": "contents changed (checksum differs)"}
            )
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        if path.name != "manifest.json" and path.name not in listed:
            problems.append(
                {"file": path.name, "problem": "is not listed in the manifest"}
            )
    ok = not problems
    return {
        "ok": ok,
        "directory": str(directory),
        "name": directory.name,
        "platform": manifest.get("platform"),
        "checked": checked,
        "problems": problems,
        "summary": f"All {checked} files match the checksums."
        if ok
        else f"{len(problems)} problem{'s' if len(problems) != 1 else ''} found.",
    }


def manifest_record(**values):
    return {"format": FORMAT, "version": 1, "posted": False, **values}


def created_at(now=None):
    return (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
