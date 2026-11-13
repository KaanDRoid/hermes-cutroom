"""Long-form YouTube delivery: chapters, a 16:9 thumbnail, sidecar SRT and end-screen space.

Chapters live in program time (seconds of the edited video) and are written as
whole seconds, because YouTube reads description timestamps to the second; the
description block and the embedded MP4 chapters therefore always agree. The
rules (first chapter at 0:00, at least three, each at least 10 s) come from the
sourced YouTube profile in :mod:`cutroom.platforms`.

Chapter suggestions are local and lexical: sentence starts after pauses are
scored by how little the words before and after them overlap (a simple
TextTiling-like cohesion measure), and titles are the most distinctive words of
each section. They are suggestions for the person to edit, never facts.
"""

import html
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path

from .platforms import profile

_YOUTUBE = profile("youtube")
CHAPTER_RULES = _YOUTUBE["chapters"]
END_SCREEN = _YOUTUBE["end_screen"]
THUMBNAIL = _YOUTUBE["cover"]
DESCRIPTION_BYTES = _YOUTUBE["text"]["description_bytes"]
MAX_CHAPTERS = 100
THUMBNAIL_TEXT_CHARS = 100
# Sizes Cutroom offers, largest first; YouTube recommends 3840x2160.
THUMBNAIL_TIERS = ((3840, 2160), (1920, 1080), (1280, 720))

# Subtitle limits of Netflix's timed text style guides (general requirements and
# English), a widely used delivery standard; YouTube publishes none for SRT.
SUBTITLE_SOURCE = (
    "https://partnerhelp.netflixstudios.com/hc/en-us/articles/"
    "215758617-Timed-Text-Style-Guide-General-Requirements"
)
SUBTITLE_LINE_SOURCE = (
    "https://partnerhelp.netflixstudios.com/hc/en-us/articles/"
    "217350977-English-USA-Timed-Text-Style-Guide"
)
SUBTITLE_CHARS = 42
SUBTITLE_LINES = 2
SUBTITLE_MIN_S = 5 / 6
SUBTITLE_MAX_S = 7.0
SUBTITLE_PAUSE_S = 1.0

SETTING_KEYS = ("chapters", "thumbnail", "subtitles_file", "end_screen_s")

_CONTROL = re.compile(r"[\x00-\x1f\x7f\u2028\u2029]")


# ---------------------------------------------------------------------------
# Settings


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _plain_text(value, name, limit, *, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    text = value.strip()
    if _CONTROL.search(text) or any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        raise ValueError(f"{name} must be one line of plain text")
    if not text and not allow_empty:
        raise ValueError(f"{name} cannot be empty")
    if len(text) > limit:
        raise ValueError(f"{name} must be at most {limit} characters")
    return text


def validate_chapters(value):
    """Shape check; returns chapters sorted by start, or None to remove them.

    Breaking YouTube's rules (too few, too short, not at 0:00) is not an error
    here: the person may be halfway through editing. :func:`chapter_problems`
    reports those in plain words, and a final export is refused until fixed.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("chapters must be a list of {start, title}")
    if len(value) > MAX_CHAPTERS:
        raise ValueError(f"Use at most {MAX_CHAPTERS} chapters")
    limit = CHAPTER_RULES["title_chars"]
    chapters = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"start", "title"}:
            raise ValueError("Each chapter must be {start, title}")
        start = _finite(item.get("start"), "Chapter start")
        if start < 0:
            raise ValueError("Chapter start cannot be negative")
        title = _plain_text(item.get("title"), "Chapter title", limit)
        chapters.append({"start": round(start, 3), "title": title})
    return sorted(chapters, key=lambda chapter: chapter["start"])


def validate_thumbnail(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"time", "text"}:
        raise ValueError("thumbnail takes time (seconds) and text")
    result = {}
    if value.get("time") is not None:
        time = _finite(value["time"], "Thumbnail time")
        if time < 0:
            raise ValueError("Thumbnail time cannot be negative")
        result["time"] = round(time, 3)
    if value.get("text") is not None:
        text = _plain_text(
            value["text"], "Thumbnail text", THUMBNAIL_TEXT_CHARS, allow_empty=True
        )
        if text:
            result["text"] = text
    return result


def validate_end_screen(value):
    if value is None:
        return None
    seconds = _finite(value, "end_screen_s")
    low, high = END_SCREEN["min_s"], END_SCREEN["max_s"]
    if not low <= seconds <= high:
        raise ValueError(f"end_screen_s must be between {low} and {high} seconds")
    return int(seconds) if seconds.is_integer() else seconds


def normalize_settings(settings):
    """Normalised long-form values for the keys present; None means remove."""
    result = {}
    if "chapters" in settings:
        result["chapters"] = validate_chapters(settings["chapters"])
    if "thumbnail" in settings:
        result["thumbnail"] = validate_thumbnail(settings["thumbnail"])
    if "subtitles_file" in settings:
        value = settings["subtitles_file"]
        if value is not None and not isinstance(value, bool):
            raise ValueError("subtitles_file must be true or false")
        result["subtitles_file"] = value
    if "end_screen_s" in settings:
        result["end_screen_s"] = validate_end_screen(settings["end_screen_s"])
    return result


# ---------------------------------------------------------------------------
# Time


def program_duration(segments):
    return sum(segment["end"] - segment["start"] for segment in segments)


def program_to_source(segments, time):
    """Source time of a program moment; a boundary belongs to the next range."""
    offset = 0.0
    for segment in segments:
        length = segment["end"] - segment["start"]
        if time < offset + length:
            return segment["start"] + max(0.0, time - offset)
        offset += length
    return segments[-1]["end"] if segments else time


def source_to_program(segments, time):
    """Program time of a source moment; removed moments map to where the edit resumes."""
    offset = 0.0
    for segment in segments:
        if time < segment["start"]:
            return offset
        if time < segment["end"]:
            return offset + time - segment["start"]
        offset += segment["end"] - segment["start"]
    return offset


def whole(seconds):
    """Whole seconds as written in a description timestamp."""
    return int(math.floor(seconds + 1e-6))


def clock(seconds, hours=False):
    total = whole(seconds)
    hour, rest = divmod(total, 3600)
    minute, second = divmod(rest, 60)
    if hours:
        return f"{hour}:{minute:02}:{second:02}"
    return f"{hour * 60 + minute}:{second:02}"


# ---------------------------------------------------------------------------
# Chapter rules and output


def chapter_problems(chapters, duration):
    """Plain-language reasons the chapters break YouTube's rules; [] when valid."""
    if not chapters:
        return []
    problems = []
    count, shortest = CHAPTER_RULES["min_count"], CHAPTER_RULES["min_length_s"]
    hours = duration >= 3600
    if len(chapters) < count:
        missing = count - len(chapters)
        problems.append(
            f"YouTube needs at least three chapters; add {missing} more."
            if missing > 1
            else "YouTube needs at least three chapters; add 1 more."
        )
    if whole(chapters[0]["start"]) != CHAPTER_RULES["first_s"]:
        problems.append("The first chapter must start at 0:00.")
    for index, chapter in enumerate(chapters):
        start = whole(chapter["start"])
        label = f"“{chapter['title']}” ({clock(start, hours)})"
        if start >= duration:
            problems.append(
                f"{label} starts after the video ends ({clock(duration, hours)})."
            )
            continue
        end = (
            whole(chapters[index + 1]["start"])
            if index + 1 < len(chapters)
            else duration
        )
        length = min(end, duration) - start
        if length < shortest:
            problems.append(
                f"{label} is {max(0, int(length))} s long; chapters need at least "
                f"{shortest} s."
            )
    block = description_block(chapters, duration)
    if len(block.encode("utf-8")) > DESCRIPTION_BYTES:
        problems.append(
            "The chapter list is longer than a YouTube description allows "
            f"({DESCRIPTION_BYTES} bytes); shorten the titles."
        )
    return problems


def description_block(chapters, duration):
    """'0:00 Intro' lines for the video description; h:mm:ss from one hour."""
    hours = duration >= 3600
    return "".join(
        f"{clock(chapter['start'], hours)} {chapter['title']}\n" for chapter in chapters
    )


def _metadata_text(text):
    return re.sub(r"([=;#\\\n])", r"\\\1", text)


def ffmetadata(chapters, duration):
    """FFmpeg metadata file with one chapter per entry, in milliseconds."""
    lines = [";FFMETADATA1"]
    end_ms = int(round(duration * 1000))
    for index, chapter in enumerate(chapters):
        start = whole(chapter["start"]) * 1000
        end = (
            whole(chapters[index + 1]["start"]) * 1000
            if index + 1 < len(chapters)
            else end_ms
        )
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start}",
            f"END={min(end, end_ms)}",
            f"title={_metadata_text(chapter['title'])}",
        ]
    return "\n".join(lines) + "\n"


def follow_edit(chapters, old_segments, new_segments):
    """Move chapters with the footage they start on after the cut changed.

    Each chapter keeps its source moment: the moment is found under the old
    cut and placed under the new one. A moment that was cut away moves to where
    the edit resumes. The first chapter stays at 0:00. Returns the chapters and
    plain notes about moves and any rule the new cut breaks.
    """
    if not chapters:
        return chapters, []
    duration = program_duration(new_segments)
    hours = duration >= 3600
    moved, notes = [], []
    for index, chapter in enumerate(chapters):
        if index == 0 and whole(chapter["start"]) == 0:
            start = 0
        else:
            source = program_to_source(old_segments, chapter["start"])
            start = round(source_to_program(new_segments, source), 3)
        if whole(start) != whole(chapter["start"]):
            notes.append(
                f"Chapter “{chapter['title']}” moved from "
                f"{clock(chapter['start'], hours)} to {clock(start, hours)} to follow "
                "the cut."
            )
        moved.append({"start": start, "title": chapter["title"]})
    moved.sort(key=lambda chapter: chapter["start"])
    problems = chapter_problems(moved, duration)
    if problems:
        notes.append("Chapters need a fix: " + " ".join(problems))
    return moved, notes


# ---------------------------------------------------------------------------
# Suggestions

_STOPWORDS = frozenset(
    """a about above after again against all almost also although always am an and
    another any anybody anyone anything are around as at back be became because become
    been before being below between both but by came can cannot could did do does
    doing done down during each either else enough even ever every everybody
    everyone everything few for from further get gets getting go goes going gone got
    gotten had has have having he her here hers herself him himself his how however
    i if in into is isn it its itself just know knew like lot lots made make makes
    making many may maybe me might mine more most much must my myself need needs
    never no nobody none nor not nothing now of off often oh ok okay on once one
    only or other others our ours ourselves out over own per perhaps put quite rather
    really right said same say saying says see seem seems seen she should since so
    some somebody someone something sort still such sure take than that the their
    theirs them themselves then there these they thing things think this those
    though through thus to too toward towards two um uh under until up upon us very
    want wanted wants was way ways we well went were what whatever when where whether
    which while who whom whose why will with within without would yeah yes yet you
    your yours yourself yourselves actually basically kind lets let'll ll re ve
    gonna wanna didn doesn don isn wasn aren weren couldn shouldn wouldn won can't
    don't doesn't didn't isn't it's that's there's i'm you're we're they're i've
    you've we've i'd you'd he's she's let's what's""".split()
)
_STARTERS = frozenset(
    "so now next first second third finally okay anyway today then".split()
)


def _token(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[^\w'’-]+", "", text).replace("’", "'").strip("'-")
    return text


def _stem(token):
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _content(token):
    return (
        len(token) > 2
        and token not in _STOPWORDS
        and not token.isdigit()
        and token.isalpha()
    )


def target_count(duration):
    """About one chapter per two and a half minutes, three to twenty."""
    return max(CHAPTER_RULES["min_count"], min(20, round(duration / 150)))


def _sentences(words):
    sentences, current = [], []
    for index, word in enumerate(words):
        if current and word["start"] - words[index - 1]["end"] >= SUBTITLE_PAUSE_S:
            sentences.append(current)
            current = []
        current.append(index)
        if word["text"].strip().endswith((".", "?", "!")):
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    return sentences


def _cosine(left, right):
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0) for key, value in left.items())
    norm = math.sqrt(sum(v * v for v in left.values())) * math.sqrt(
        sum(v * v for v in right.values())
    )
    return dot / norm if norm else 0.0


def _title(sequence, surface, document_frequency, sections, used):
    """Title from the most distinctive words; ``sequence`` has None for stopwords."""
    section_tokens = [term for term in sequence if term]
    counts = Counter(section_tokens)
    if not counts:
        return None, []

    def idf(term):
        return math.log((1 + sections) / (1 + document_frequency[term])) + 1

    scores = {term: count * idf(term) for term, count in counts.items()}
    ranked = sorted(scores, key=lambda term: (-scores[term], term))
    keywords = [surface[term] for term in ranked[:4]]
    # Only words that were spoken next to each other form a two-word title.
    pairs = Counter((a, b) for a, b in zip(sequence, sequence[1:]) if a and b)
    best_pair = max(
        (
            (count * (scores[a] + scores[b]) / 2, (a, b))
            for (a, b), count in pairs.items()
            if a != b and count >= 2
        ),
        default=None,
    )
    candidates = []
    if best_pair and best_pair[0] >= 0.4 * scores[ranked[0]]:
        a, b = best_pair[1]
        candidates.append(f"{surface[a]} {surface[b]}")
    if len(ranked) > 1:
        candidates.append(f"{surface[ranked[0]]} and {surface[ranked[1]]}")
    candidates.append(surface[ranked[0]])
    for extra in ranked[2:6]:
        candidates.append(f"{surface[ranked[0]]} and {surface[extra]}")
    for candidate in candidates:
        title = candidate[:1].upper() + candidate[1:]
        if title.casefold() not in used:
            return title[:40], keywords
    return None, keywords


def suggest_chapters(words, duration, count=None):
    """Suggested chapters for program-time words ({start, end, text}).

    Boundaries are sentence starts at least 10 s from each other and from the
    ends, chosen by the lowest word overlap between about 120 words before and
    after them, with a small bonus for a pause before the sentence and for
    openers such as "so" or "next". Returns [] when the program is too short
    for three 10-second chapters or has no words.
    """
    shortest = CHAPTER_RULES["min_length_s"]
    words = sorted(
        (w for w in words if str(w.get("text", "")).strip()),
        key=lambda w: (w["start"], w["end"]),
    )
    if not words or duration < shortest * CHAPTER_RULES["min_count"]:
        return []
    count = count or target_count(duration)
    spacing = max(shortest, 0.5 * duration / count)
    tokens = [_token(word["text"]) for word in words]
    stems = [_stem(token) if _content(token) else None for token in tokens]
    sentences = _sentences(words)
    window = 120
    candidates = []
    for position, sentence in enumerate(sentences[1:], 1):
        first = sentence[0]
        start = whole(words[first]["start"])
        if start < spacing or duration - start < spacing:
            continue
        before = Counter(s for s in stems[max(0, first - window) : first] if s)
        after = Counter(s for s in stems[first : first + window] if s)
        overlap = _cosine(before, after)
        pause = words[first]["start"] - words[first - 1]["end"]
        opener = tokens[first] in _STARTERS
        score = (1 - overlap) + 0.15 * min(pause, 2.0) / 2.0 + (0.05 if opener else 0)
        reasons = [f"word overlap with the part before {overlap:.2f}"]
        if pause >= 0.5:
            reasons.append(f"pause of {pause:.1f} s")
        if opener:
            reasons.append(f"starts with “{words[first]['text'].strip()}”")
        candidates.append((score, start, first, "; ".join(reasons)))
    chosen = []
    for score, start, first, reason in sorted(candidates, key=lambda c: (-c[0], c[1])):
        if len(chosen) >= count - 1:
            break
        if all(abs(start - other[1]) >= spacing for other in chosen):
            chosen.append((score, start, first, reason))
    chosen.sort(key=lambda item: item[1])
    bounds = [(0, 0, "start of the video")] + [(s, f, r) for _, s, f, r in chosen]
    sections = []
    for index, (start, first, _) in enumerate(bounds):
        last = bounds[index + 1][1] if index + 1 < len(bounds) else len(words)
        sections.append(stems[first:last])
    surface = {}
    surface_counts = Counter(
        (stem, tokens[i]) for i, stem in enumerate(stems) if stem is not None
    )
    for (stem, form), _ in sorted(surface_counts.items(), key=lambda item: -item[1]):
        surface.setdefault(stem, form)
    frequency = Counter(term for section in sections for term in set(section) if term)
    used, result = set(), []
    for (start, first, reason), section in zip(bounds, sections):
        title, keywords = _title(section, surface, frequency, len(sections), used)
        title = title or f"Part {len(result) + 1}"
        used.add(title.casefold())
        result.append(
            {
                "start": start,
                "title": title,
                "start_word": words[first]["start"],
                "keywords": keywords,
                "reason": reason,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Subtitles


def _wrap(text):
    """One or two balanced lines of at most 42 characters; None if it cannot fit."""
    if len(text) <= SUBTITLE_CHARS:
        return [text]
    best = None
    for match in re.finditer(" ", text):
        top, bottom = text[: match.start()], text[match.end() :]
        if len(top) <= SUBTITLE_CHARS and len(bottom) <= SUBTITLE_CHARS:
            # Prefer a bottom-heavy pair and a break after punctuation.
            cost = abs(len(top) - len(bottom)) + (len(top) > len(bottom)) * 2
            cost -= 6 if top.endswith((",", ";", ":")) else 0
            if best is None or cost < best[0]:
                best = (cost, [top, bottom])
    return best[1] if best else None


def srt_cues(words):
    """Sentence-sized cues from program-time words ({start, end, text}).

    A cue ends at a sentence end, before a pause of a second or more, or before
    it would need more than two lines of 42 characters or last over 7 s. A cue
    shorter than 5/6 s is lengthened when the next cue leaves room. Cues never
    overlap. A single word longer than a line is split across lines.
    """
    words = [
        {**w, "text": " ".join(str(w["text"]).split())}
        for w in sorted(words, key=lambda w: (w["start"], w["end"]))
        if str(w.get("text", "")).strip()
    ]
    groups, current = [], []
    for index, word in enumerate(words):
        if current:
            text = " ".join(w["text"] for w in current + [word])
            if (
                word["start"] - current[-1]["end"] >= SUBTITLE_PAUSE_S
                or _wrap(text) is None
                or word["end"] - current[0]["start"] > SUBTITLE_MAX_S
            ):
                groups.append(current)
                current = []
        current.append(word)
        if word["text"].endswith((".", "?", "!")):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    # Co-timed zero-duration words cannot occupy separate non-overlapping cues.
    merged = []
    for group in groups:
        if merged and group[0]["start"] < merged[-1][0]["start"] + 0.001:
            merged[-1].extend(group)
        else:
            merged.append(group)
    groups = merged
    cues = []
    for index, group in enumerate(groups):
        text = " ".join(w["text"] for w in group)
        lines = _wrap(text)
        if lines is None:
            if len(text) > SUBTITLE_CHARS * SUBTITLE_LINES:
                raise ValueError(
                    "Subtitle text/token cannot fit losslessly in two lines; "
                    "shorten the token or correct co-timed word timestamps"
                )
            lines = [
                text[i : i + SUBTITLE_CHARS]
                for i in range(0, len(text), SUBTITLE_CHARS)
            ]
        start, end = group[0]["start"], max(w["end"] for w in group)
        following = groups[index + 1][0]["start"] if index + 1 < len(groups) else None
        if end - start < SUBTITLE_MIN_S:
            target = start + SUBTITLE_MIN_S
            end = max(end, min(target, following) if following is not None else target)
        if following is not None:
            end = min(end, following)
        end = min(end, start + SUBTITLE_MAX_S) if end - start > SUBTITLE_MAX_S else end
        end = max(end, start + 0.001)
        cues.append(
            {
                "start": start,
                "end": end,
                "lines": lines,
                "word_start": group[0]["start"],
                "word_end": max(w["end"] for w in group),
            }
        )
    return cues


def _stamp(seconds, separator):
    milliseconds = int(round(max(0.0, seconds) * 1000))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    second, millisecond = divmod(rest, 1000)
    return f"{hours:02}:{minutes:02}:{second:02}{separator}{millisecond:03}"


def write_srt(cues, path, format="srt"):
    """Write SRT (or WebVTT) exclusively; text is literal, lines are kept."""
    path = Path(path)
    separator = "," if format == "srt" else "."
    parts = ["WEBVTT\n\n"] if format == "vtt" else []
    previous = None
    for index, cue in enumerate(cues, 1):
        start, end = _stamp(cue["start"], separator), _stamp(cue["end"], separator)
        if cue["end"] <= cue["start"] or start == end:
            raise ValueError("Subtitle cue has no representable duration")
        if previous is not None and cue["start"] < previous:
            raise ValueError("Subtitle cues must not overlap")
        previous = cue["end"]
        text = "\n".join(html.escape(line, quote=False) for line in cue["lines"])
        number = f"{index}\n" if format == "srt" else ""
        parts.append(f"{number}{start} --> {end}\n{text}\n\n")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("".join(parts))
    return str(path)


_TIMING = re.compile(
    r"^(\d+):(\d{2}):(\d{2})[,.](\d{3}) --> (\d+):(\d{2}):(\d{2})[,.](\d{3})$"
)


def parse_srt(text):
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        if not lines or not lines[0].strip():
            continue
        if not lines[0].strip().isdigit() or len(lines) < 3:
            raise ValueError(f"Malformed subtitle block: {block[:40]!r}")
        match = _TIMING.match(lines[1].strip())
        if not match:
            raise ValueError(f"Malformed subtitle time: {lines[1][:40]!r}")
        h1, m1, s1, f1, h2, m2, s2, f2 = map(int, match.groups())
        cues.append(
            {
                "index": int(lines[0]),
                "start": h1 * 3600 + m1 * 60 + s1 + f1 / 1000,
                "end": h2 * 3600 + m2 * 60 + s2 + f2 / 1000,
                "lines": [html.unescape(line) for line in lines[2:]],
            }
        )
    return cues


def subtitle_report(text, words, frame):
    """Check an SRT file against the words it was made from."""
    try:
        parsed = parse_srt(text)
    except ValueError as error:
        return {"status": "fail", "problems": [str(error)]}
    problems = []
    # Compare delivered characters directly with the transcript, independently
    # of cue generation. Wrapping may insert whitespace inside a long token.
    original = "".join(
        re.sub(r"\s+", "", str(w.get("text", "")))
        for w in sorted(words, key=lambda w: (w["start"], w["end"]))
    )
    delivered = "".join(
        re.sub(r"\s+", "", line) for cue in parsed for line in cue["lines"]
    )
    if delivered != original:
        problems.append("Delivered subtitle text differs from the original transcript")
    try:
        expected = srt_cues(words)
    except ValueError as error:
        return {"status": "fail", "problems": problems + [str(error)]}
    if len(parsed) != len(expected):
        problems.append(f"{len(parsed)} cues in the file, {len(expected)} expected")
    previous_end, worst = 0.0, 0.0
    for number, cue in enumerate(parsed, 1):
        if cue["index"] != number:
            problems.append(f"Cue {number} is numbered {cue['index']}")
        if cue["start"] < previous_end - 0.0005:
            problems.append(f"Cue {number} overlaps the previous cue")
        if cue["end"] <= cue["start"]:
            problems.append(f"Cue {number} has no duration")
        if cue["end"] - cue["start"] > SUBTITLE_MAX_S + 0.0005:
            problems.append(f"Cue {number} lasts over {SUBTITLE_MAX_S:g} s")
        if len(cue["lines"]) > SUBTITLE_LINES or any(
            len(line) > SUBTITLE_CHARS for line in cue["lines"]
        ):
            problems.append(f"Cue {number} exceeds two lines of 42 characters")
        previous_end = cue["end"]
    for number, (cue, want) in enumerate(zip(parsed, expected), 1):
        if cue["lines"] != want["lines"]:
            problems.append(f"Cue {number} text differs from the transcript")
            continue
        offset = abs(cue["start"] - want["word_start"])
        worst = max(worst, offset)
        if offset > frame + 0.0005:
            problems.append(
                f"Cue {number} starts {offset:.3f} s from its first word (more than "
                "one frame)"
            )
        if (
            cue["end"] < want["word_end"] - frame - 0.0005
            and cue["end"] < want["end"] - 0.0005
        ):
            problems.append(f"Cue {number} ends before its last word")
    return {
        "status": "fail" if problems else "pass",
        "cues": len(parsed),
        "largest_start_offset_s": round(worst, 4),
        "frame_s": round(frame, 6),
        "limits": {
            "chars_per_line": SUBTITLE_CHARS,
            "lines": SUBTITLE_LINES,
            "min_s": round(SUBTITLE_MIN_S, 4),
            "max_s": SUBTITLE_MAX_S,
            "source": SUBTITLE_SOURCE,
        },
        "problems": problems[:20],
    }


# ---------------------------------------------------------------------------
# Thumbnail


def thumbnail_size(width, height):
    """Largest 16:9 tier the source fills without enlarging, else 1280x720.

    Returns (width, height, enlargement) where enlargement is how much the
    16:9 crop of the source is scaled up (1.0 means not at all).
    """
    crop_width = min(width, height * 16 / 9)
    for tier_width, tier_height in THUMBNAIL_TIERS:
        if crop_width >= tier_width - 0.5:
            return tier_width, tier_height, 1.0
    tier_width, tier_height = THUMBNAIL_TIERS[-1]
    return tier_width, tier_height, round(tier_width / crop_width, 4)


def _gaze_by_time(analysis):
    """Best gaze proxy per Vision frame time (largest face), when recorded."""
    result = {}
    for frame in (analysis or {}).get("frames") or []:
        faces = [f for f in frame.get("faces") or [] if f.get("box")]
        if not faces or not isinstance(frame.get("time"), (int, float)):
            continue
        face = max(
            faces,
            key=lambda f: (f["box"][2] - f["box"][0]) * (f["box"][3] - f["box"][1]),
        )
        if isinstance(face.get("gaze_score"), (int, float)):
            result[round(frame["time"], 3)] = face["gaze_score"]
    return result


def _largest(faces):
    return max(faces, key=lambda face: face[2] * face[3])


def default_thumbnail_time(analysis, segments):
    """Program time of a face-forward frame, else 10 % into the program.

    Uses Vision face samples inside the edit. The score favours a face turned
    to the camera (Vision's head and iris proxy), a large face, a closed mouth
    and a face away from the frame edge. Without samples the poster rule
    applies: 10 % into the program.
    """
    duration = program_duration(segments)
    gaze = _gaze_by_time(analysis)
    best = None
    for time, faces in (analysis or {}).get("face_samples") or []:
        if not faces or not any(s["start"] <= time < s["end"] for s in segments):
            continue
        cx, _, _, h, _, mouth = (list(_largest(faces)) + [None] * 6)[:6]
        facing = gaze.get(round(time, 3), 0.5)
        score = (
            h
            * facing**2
            * (1 - 0.5 * min(1.0, abs(cx - 0.5) * 2))
            * (1 - min(0.8, 2 * (mouth or 0)))
        )
        if best is None or score > best[0]:
            best = (score, time)
    if best is not None:
        return round(source_to_program(segments, best[1]), 3)
    return round(duration * 0.1, 3)


def face_box_at(analysis, time, tolerance=1.0):
    """Normalised box (x0, y0, x1, y1) of the largest face sampled near ``time``."""
    nearest = None
    for at, faces in (analysis or {}).get("face_samples") or []:
        if faces and abs(at - time) <= tolerance:
            if nearest is None or abs(at - time) < abs(nearest[0] - time):
                nearest = (at, faces)
    if nearest is None:
        return None
    cx, cy, w, h = _largest(nearest[1])[:4]
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]


def _run(arguments, timeout, cwd=None):
    from .childenv import child_env

    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=timeout,
        shell=False,
        cwd=cwd,
        env=child_env(python=False),
    )


def _display_size(video, timeout):
    from .postproduction import _probe

    info = _probe(video, timeout)
    width, height = info["width"], info["height"]
    ratio = info["display_aspect_ratio"]
    # Square display pixels: keep the height, correct the width.
    if abs(ratio - width / height) > 0.01:
        width = round(height * ratio)
    return width, height, info


def _balanced(words, count):
    """Split words into ``count`` lines with the shortest longest line."""
    if count <= 1 or len(words) <= 1:
        return [" ".join(words)]
    best = None
    for first in range(1, len(words) - count + 2):
        rest = _balanced(words[first:], count - 1)
        lines = [" ".join(words[:first]), *rest]
        key = (max(map(len, lines)), -len(lines[-1]))
        if best is None or key < best[0]:
            best = (key, lines)
    return best[1]


def _text_region(width, height, face):
    """Where the title may go: beside the face, else along the bottom.

    Regions stay inside the 5 % graphics-safe margins. Returns (x0, y0, x1,
    y1, anchor) in pixels; anchor is "top" or "bottom".
    """
    left, top, right, bottom = 0.05 * width, 0.05 * height, 0.95 * width, 0.95 * height
    if face is None:
        return left, top, 0.67 * width, bottom, "top"
    gap = 0.03 * width
    x0, _, x1, y1 = (
        face[0] * width,
        face[1] * height,
        face[2] * width,
        face[3] * height,
    )
    beside = [
        (min(right, x0 - gap) - left, (left, top, min(right, x0 - gap), bottom, "top")),
        # Right of the face, kept to the upper half: the duration badge sits bottom right.
        (
            right - max(left, x1 + gap),
            (max(left, x1 + gap), top, right, height * 0.6, "top"),
        ),
    ]
    room, region = max(beside, key=lambda item: item[0])
    if room >= 0.28 * width:
        return region
    return left, max(top, y1 + gap), right, bottom, "bottom"


def make_thumbnail(
    source,
    time,
    output,
    *,
    text="",
    font="Arial",
    max_bytes=None,
    size=None,
    face=None,
    timeout=300,
):
    """Write a 16:9 JPEG frame of ``source`` at ``time`` (source seconds).

    The 16:9 centre of the frame is scaled to the largest tier the source
    fills (3840x2160, 1920x1080) or enlarged to 1280x720 and reported. Optional
    text sits inside 5 % margins (EBU R 95 graphics-safe area) on a dark box,
    in the caption font: beside the face when ``face`` (a normalised source box)
    leaves room, else along the bottom, and never in the lower right where
    YouTube shows the duration. Lines are balanced and as large as fit. JPEG quality steps down until the file is
    under ``max_bytes`` (2 MB by default, YouTube's phone upload limit).
    """
    from .postproduction import _font_path

    max_bytes = max_bytes or THUMBNAIL["max_bytes"]
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Thumbnail already exists: {output}")
    text = _plain_text(
        text or "", "Thumbnail text", THUMBNAIL_TEXT_CHARS, allow_empty=True
    )
    display_width, display_height, info = _display_size(source, timeout)
    time = max(0.0, min(float(time), info["duration"] - 0.05))
    width, height, enlargement = thumbnail_size(display_width, display_height)
    if size is not None:
        width, height = size
    crop_width = min(display_width, display_height * 16 / 9)
    crop_height = crop_width * 9 / 16
    filters = [
        f"scale={display_width}:{display_height}",
        "setsar=1",
        f"crop={int(crop_width) // 2 * 2}:{int(crop_height) // 2 * 2}",
        f"scale={width}:{height}:flags=lanczos",
    ]
    box = None
    with tempfile.TemporaryDirectory(prefix=".thumbnail-", dir=output.parent) as temp:
        directory = Path(temp)
        if text:
            path = _font_path(font)
            if path is None:
                raise ValueError("Requested local font is unavailable: " + font)
            shutil.copyfile(path, directory / "font.ttf")
            from .captions import Measurer

            measure = Measurer(path)
            if face is not None:
                # Face box in the 16:9 crop, normalised.
                offset_x = (display_width - crop_width) / 2 / display_width
                offset_y = (display_height - crop_height) / 2 / display_height
                scale_x = display_width / crop_width
                scale_y = display_height / crop_height
                face = [
                    (face[0] - offset_x) * scale_x,
                    (face[1] - offset_y) * scale_y,
                    (face[2] - offset_x) * scale_x,
                    (face[3] - offset_y) * scale_y,
                ]
            rx0, ry0, rx1, ry1, anchor = _text_region(width, height, face)
            pad = round(height * 0.02)
            words = text.split()
            fontsize, lines = 12, [text]
            for count in (1, 2, 3):
                candidate = _balanced(words, min(count, len(words)))
                widest = max(measure(line, 100) for line in candidate) / 100
                size = int(
                    min(height * 0.11, (rx1 - rx0 - 2 * pad) / max(widest, 1e-6))
                )
                size = int(min(size, (ry1 - ry0 - 2 * pad) / (1.25 * len(candidate))))
                if size > fontsize:
                    fontsize, lines = size, candidate
                if size >= height * 0.075 or count >= len(words):
                    break
            fontsize = max(12, fontsize)
            pitch = round(fontsize * 1.25)
            block_w = (
                math.ceil(max(measure(line, fontsize) for line in lines)) + 2 * pad
            )
            block_h = pitch * len(lines) + 2 * pad
            bx = round(rx0)
            by = round(ry0) if anchor == "top" else round(ry1 - block_h)
            draws = [f"drawbox=x={bx}:y={by}:w={block_w}:h={block_h}:t=fill:color=%s"]
            for index, line in enumerate(lines):
                name = f"line{index}.txt"
                (directory / name).write_text(line, encoding="utf-8")
                draws.append(
                    f"drawtext=fontfile=font.ttf:textfile={name}:expansion=none"
                    f":fontsize={fontsize}:x={bx + pad}"
                    f":y={by + pad + index * pitch + round(fontsize * 0.1)}:fontcolor=%s"
                )
            chain = ",".join(draws)
            box = _text_box(
                directory,
                chain % (("white",) * (1 + len(lines))),
                width,
                height,
                timeout,
            )
            box.update(font_size=fontsize, lines=lines, region=anchor)
            if face is not None:
                fx0, fy0, fx1, fy1 = (
                    face[0] * width,
                    face[1] * height,
                    face[2] * width,
                    face[3] * height,
                )
                box["overlaps_face"] = not (
                    box["x1"] <= fx0
                    or box["x0"] >= fx1
                    or box["y1"] <= fy0
                    or box["y0"] >= fy1
                )
            filters.append(chain % ("black@0.62", *(["white"] * len(lines))))
        (directory / "filters.txt").write_text(",".join(filters), encoding="utf-8")
        temporary = directory / "thumbnail.jpg"
        quality = None
        for quality in (2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25, 31):
            temporary.unlink(missing_ok=True)
            _run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file",
                    "-ss",
                    f"{time:.3f}",
                    "-i",
                    str(Path(source).resolve()),
                    "-/vf",
                    "filters.txt",
                    "-frames:v",
                    "1",
                    "-an",
                    "-pix_fmt",
                    "yuvj420p",
                    "-c:v",
                    "mjpeg",
                    "-q:v",
                    str(quality),
                    "-f",
                    "image2",
                    "-update",
                    "1",
                    str(temporary),
                ],
                timeout,
                cwd=directory,
            )
            if temporary.stat().st_size <= max_bytes:
                break
        size_bytes = temporary.stat().st_size
        if size_bytes > max_bytes:
            raise RuntimeError("The thumbnail could not be made small enough")
        os.link(temporary, output)
    return {
        "output": str(output),
        "width": width,
        "height": height,
        "bytes": size_bytes,
        "quality": quality,
        "time": round(time, 3),
        "text": text,
        "upscaled": enlargement > 1.0001,
        "upscale_factor": enlargement,
        "source_size": [display_width, display_height],
        **({"text_box": box} if box else {}),
    }


def _text_box(directory, draw, width, height, timeout):
    """Pixel box of the title and its backing box, measured by FFmpeg's bbox."""
    result = _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-v",
            "info",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:size={width}x{height}:rate=1",
            "-vf",
            f"{draw},bbox=min_val=128",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        timeout,
        cwd=directory,
    )
    match = re.search(r"x1:(\d+) x2:(\d+) y1:(\d+) y2:(\d+)", result.stderr)
    if not match:
        raise RuntimeError("The thumbnail text could not be measured")
    x1, x2, y1, y2 = map(int, match.groups())
    return {"x0": x1, "y0": y1, "x1": x2 + 1, "y1": y2 + 1, "measurement": "bbox"}


# ---------------------------------------------------------------------------
# Delivery


def embed_chapters(video, chapters, duration, timeout=600):
    """Copy the streams into a new MP4 with chapter metadata, then replace it."""
    video = Path(video)
    with tempfile.TemporaryDirectory(prefix=".chapters-", dir=video.parent) as temp:
        directory = Path(temp)
        metadata = directory / "chapters.ffmeta"
        metadata.write_text(ffmetadata(chapters, duration), encoding="utf-8")
        temporary = directory / ("chaptered" + video.suffix)
        _run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-i",
                str(video),
                "-f",
                "ffmetadata",
                "-i",
                str(metadata),
                "-map",
                "0",
                "-map_metadata",
                "0",
                "-map_chapters",
                "1",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            timeout,
        )
        listed = probe_chapters(temporary, timeout)
        if [round(c["start"]) for c in listed] != [whole(c["start"]) for c in chapters]:
            raise RuntimeError("Chapter metadata was not written as expected")
        os.replace(temporary, video)
    return listed


def probe_chapters(video, timeout=120):
    data = json.loads(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-show_chapters",
                "-of",
                "json",
                str(video),
            ],
            timeout,
        ).stdout
    )
    return [
        {
            "start": float(item["start_time"]),
            "end": float(item["end_time"]),
            "title": (item.get("tags") or {}).get("title", ""),
        }
        for item in data.get("chapters", [])
    ]


def deliver(
    video,
    output_dir,
    duration,
    chapters=None,
    words=None,
    subtitles=True,
    thumbnail=None,
    timeout=900,
):
    """Long-form files next to a YouTube render: chapters, SRT/VTT, thumbnail.

    Chapters are embedded only when they follow YouTube's rules; otherwise the
    render keeps none and QA reports the problems.
    """
    output_dir = Path(output_dir)
    artifacts, result = {}, {"chapters_embedded": False}
    chapters = validate_chapters(chapters) or []
    problems = chapter_problems(chapters, duration)
    if chapters and not problems:
        embed_chapters(video, chapters, duration, timeout)
        path = output_dir / "chapters.txt"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(description_block(chapters, duration))
        artifacts["chapters"] = str(path)
        result["chapters_embedded"] = True
    result["chapter_problems"] = problems
    if subtitles and words:
        cues = srt_cues(words)
        if cues:
            artifacts["captions_srt"] = write_srt(cues, output_dir / "captions.srt")
            artifacts["captions_vtt"] = write_srt(
                cues, output_dir / "captions.vtt", format="vtt"
            )
            result["subtitle_cues"] = len(cues)
    if thumbnail:
        made = make_thumbnail(
            thumbnail["source"],
            thumbnail["time"],
            output_dir / "thumbnail.jpg",
            text=thumbnail.get("text") or "",
            font=thumbnail.get("font") or "Arial",
            face=thumbnail.get("face"),
            timeout=timeout,
        )
        made["program_time"] = thumbnail.get("program_time")
        artifacts["thumbnail"] = made["output"]
        result["thumbnail"] = made
    return {**result, "artifacts": artifacts}


# ---------------------------------------------------------------------------
# QA


def _thumbnail_check(path):
    try:
        data = json.loads(
            _run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file",
                    "-show_streams",
                    "-of",
                    "json",
                    str(path),
                ],
                120,
            ).stdout
        )
        stream = data["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        IndexError,
    ) as error:
        return "fail", {"error": str(error)}
    size = Path(path).stat().st_size
    problems = []
    if width * 9 != height * 16:
        problems.append(f"{width}×{height} is not 16:9")
    if width < THUMBNAIL_TIERS[-1][0]:
        problems.append(f"{width} px wide; Cutroom makes at least 1280 px")
    if width < THUMBNAIL["min_width"]:
        problems.append(f"YouTube needs at least {THUMBNAIL['min_width']} px wide")
    if size > THUMBNAIL["max_bytes"]:
        problems.append(f"{size} bytes is over the {THUMBNAIL['max_bytes']}-byte limit")
    if stream.get("codec_name") not in {"mjpeg", "png"}:
        problems.append("Not a JPEG or PNG image")
    detail = {
        "width": width,
        "height": height,
        "bytes": size,
        "codec": stream.get("codec_name"),
        "max_bytes": THUMBNAIL["max_bytes"],
        "recommended": [THUMBNAIL["width"], THUMBNAIL["height"]],
        "source": THUMBNAIL["source"],
        "problems": problems,
    }
    return ("fail" if problems else "pass"), detail


def quality_checks(add, video, info, longform, captions=None):
    """Add chapters, subtitles_file, thumbnail and end_screen checks."""
    duration = float(longform.get("duration") or info["duration"])
    hours = duration >= 3600
    chapters = validate_chapters(longform.get("chapters")) or []
    if not chapters:
        add("chapters", "skip", {"reason": "No chapters set"})
    else:
        problems = chapter_problems(chapters, duration)
        try:
            listed = probe_chapters(video)
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            listed, problems = [], problems + [f"Could not read chapters: {error}"]
        expected = [(whole(c["start"]), c["title"]) for c in chapters]
        found = [(c["start"], c["title"]) for c in listed]
        if not problems and (
            len(found) != len(expected)
            or any(
                abs(f[0] - e[0]) > 0.0015 or f[1] != e[1]
                for f, e in zip(found, expected)
            )
        ):
            problems.append("The video's chapter metadata does not match the chapters")
        block = None
        if longform.get("chapters_file"):
            block = Path(longform["chapters_file"]).read_text(encoding="utf-8")
            if not problems and block != description_block(chapters, duration):
                problems.append("chapters.txt does not match the chapters")
        elif not problems:
            problems.append("chapters.txt is missing")
        add(
            "chapters",
            "fail" if problems else "pass",
            {
                "chapters": [
                    {"start": clock(s, hours), "title": t} for s, t in expected
                ],
                "embedded": len(found),
                "problems": problems,
                "rules": {
                    key: CHAPTER_RULES[key]
                    for key in ("first_s", "min_count", "min_length_s", "source")
                },
            },
        )
    if longform.get("subtitles_file"):
        text = Path(longform["subtitles_file"]).read_text(encoding="utf-8")
        report = subtitle_report(
            text,
            longform.get("words") or [],
            float(longform.get("frame_interval") or 1 / 30),
        )
        add("subtitles_file", report.pop("status"), report)
    elif longform.get("subtitles_expected"):
        add("subtitles_file", "fail", {"problems": ["The subtitles file is missing"]})
    if longform.get("thumbnail"):
        status, detail = _thumbnail_check(longform["thumbnail"])
        upscale = longform.get("thumbnail_upscale_factor")
        if status == "pass" and upscale and upscale > 1.0001:
            status = "warning"
            detail["upscale_factor"] = upscale
            detail["note"] = (
                "The source is smaller than 1280x720, so the thumbnail is enlarged"
            )
        add("thumbnail", status, detail)
    seconds = longform.get("end_screen_s")
    if seconds:
        problems, notes = [], []
        needed = END_SCREEN["min_video_s"]
        if duration < needed:
            problems.append(
                f"YouTube shows end screens only on videos of at least {needed} s"
            )
        if duration < seconds:
            problems.append(f"The video is shorter than the {seconds:g} s end screen")
        start = max(0.0, duration - seconds)
        burned = longform.get("burned_captions") or captions or []
        late = [c for c in burned if c["end"] > start + 1e-3]
        if late:
            notes.append(
                f"{len(late)} burned caption{'s' if len(late) != 1 else ''} appear in "
                f"the last {seconds:g} s, where end-screen elements may cover them"
            )
        if longform.get("title"):
            notes.append("The on-screen title stays visible during the end screen")
        if longform.get("graphics"):
            notes.append("A graphic overlay stays visible during the end screen")
        add(
            "end_screen",
            "fail" if problems else "warning" if notes else "pass",
            {
                "seconds": seconds,
                "starts_at": round(start, 3),
                "problems": problems,
                "notes": notes,
                "area": "whole frame: end-screen elements can be placed anywhere",
                "source": END_SCREEN["source"],
            },
        )
