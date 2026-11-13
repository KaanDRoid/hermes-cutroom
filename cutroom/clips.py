"""Find standalone clips in a long recording and explain their scores.

A clip is a run of whole sentences, 20 to 90 seconds long, cut in the quiet
gap before its first word and after its last. Each candidate gets a score from
0 to 100 built from local, explainable signals (opening line, whether it
starts mid-thought, speaking pace, long pauses, how clearly the words were
heard, voice level variation and whether the speaker is on screen) plus the
plain-English reasons behind it. Nothing is downloaded or sent anywhere, and
the same transcript always gives the same candidates.
"""

import array
import bisect
import math
import operator
import re
import subprocess

DEFAULT_MIN_S = 20
DEFAULT_MAX_S = 90
SHORT_FORM_MAX_S = 60
DEFAULT_COUNT = 8
MAX_COUNT = 20
# A picked or typed range shorter than this is not a clip.
MIN_CLIP_S = 20.0
# Longer runs without an ending are split at their largest pause.
MAX_SENTENCE_S = 30.0
# In punctuated text a pause this long still ends a sentence.
PUNCTUATED_PAUSE_S = 2.0
LONG_PAUSE_S = 1.5
ENERGY_STEP = 0.02
ENERGY_RATE = 4000
ENERGY_TIMEOUT = 120
ENERGY_MAX_SOURCE_S = 3 * 3600
BLOCK_S = 0.5
# Candidates within this distance of an earlier pick lose a few points, so the
# list covers the whole recording rather than one strong passage.
SPREAD_S = 120.0
SPREAD_PENALTY = 6
BASE_SCORE = 55
PLATFORMS = ("custom", "instagram_reels", "youtube_shorts", "tiktok", "youtube")
SHORT_FORM = {
    "instagram_reels": "Reels",
    "youtube_shorts": "Shorts",
    "tiktok": "TikTok",
}

_END = re.compile(r"[.!?…。！？]+[\"'”’»)\]]*$")
_ABBREVIATIONS = {
    "mr.",
    "mrs.",
    "ms.",
    "dr.",
    "prof.",
    "sr.",
    "jr.",
    "st.",
    "vs.",
    "etc.",
    "e.g.",
    "i.e.",
    "u.s.",
    "u.k.",
    "no.",
    "approx.",
}
_DANGLING_STRONG = {"and", "but", "or", "because", "which", "plus", "nor", "cause"}
_DANGLING_WEAK = {"so", "then", "also", "however", "therefore", "anyway", "though"}
_POINTING_STRONG = {"it", "they", "he", "she", "them", "his", "her", "their", "its"}
_POINTING_WEAK = {"this", "that", "these", "those"}
_VIEWER = {"you", "your", "you're", "youre", "you've", "you'll", "yourself", "you'd"}
_QUESTION_START = {
    "what",
    "why",
    "how",
    "when",
    "who",
    "where",
    "which",
    "do",
    "does",
    "did",
    "is",
    "are",
    "can",
    "could",
    "would",
    "should",
    "have",
    "has",
}
_NUMBERS = {
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "hundred",
    "thousand",
    "million",
    "billion",
    "trillion",
    "percent",
    "half",
    "dozen",
}
_CLAIMS = {
    "never",
    "always",
    "every",
    "everyone",
    "everybody",
    "nobody",
    "nothing",
    "most",
    "biggest",
    "best",
    "worst",
    "only",
    "secret",
    "truth",
    "true",
    "mistake",
    "wrong",
    "problem",
    "simple",
    "important",
    "must",
    "need",
    "impossible",
    "surprising",
    "actually",
    "really",
    "huge",
    "matters",
}


def _bare(text):
    return re.sub(r"[^\w'’]+", "", text.lower()).replace("’", "'")


def _ends_sentence(text):
    lowered = text.lower()
    if lowered in _ABBREVIATIONS or re.fullmatch(r"[a-z]\.", lowered):
        return False
    return bool(_END.search(text))


def _number(value, name):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _ordered(words):
    return sorted(
        (w for w in words if isinstance(w, dict)),
        key=lambda w: (w["start"], w["id"]),
    )


def _punctuated(words):
    ends = sum(1 for w in words if _ends_sentence(w["text"]))
    return ends >= 1 and ends * 60 >= len(words)


def sentences(words):
    """Group timed words into sentences.

    Punctuated text is split after ``.``, ``?`` and ``!`` (not after common
    abbreviations) and at pauses of two seconds or more. Text without
    punctuation is split at pauses clearly longer than the usual gap between
    words. Runs longer than 30 seconds are split at their largest pause.
    ``first`` and ``last`` index the time-ordered word list.
    """
    words = _ordered(words)
    if not words:
        return []
    gaps = [max(0.0, b["start"] - a["end"]) for a, b in zip(words, words[1:])]
    punctuated = _punctuated(words)
    if punctuated:
        threshold = PUNCTUATED_PAUSE_S
    else:
        ordered = sorted(gaps)
        median = ordered[len(ordered) // 2] if ordered else 0.0
        threshold = min(1.0, max(0.4, 4 * median))
    groups, first = [], 0
    for index, word in enumerate(words):
        last = index == len(words) - 1
        if last or (punctuated and _ends_sentence(word["text"])):
            groups.append((first, index))
            first = index + 1
        elif gaps[index] >= threshold:
            groups.append((first, index))
            first = index + 1

    def split(first, last):
        if (
            words[last]["end"] - words[first]["start"] <= MAX_SENTENCE_S
            or first == last
        ):
            return [(first, last)]
        middle = (first + last) / 2
        cut = max(
            range(first, last),
            key=lambda i: (round(gaps[i], 3), -abs(i - middle)),
        )
        return split(first, cut) + split(cut + 1, last)

    result = []
    for first, last in groups:
        for a, b in split(first, last):
            text = words[b]["text"]
            if _ends_sentence(text):
                kind = "question" if "?" in text or "？" in text else "stop"
            else:
                kind = "pause"
            result.append(
                {
                    "index": len(result),
                    "first": a,
                    "last": b,
                    "first_id": words[a]["id"],
                    "last_id": words[b]["id"],
                    "start": words[a]["start"],
                    "end": words[b]["end"],
                    "text": " ".join(w["text"] for w in words[a : b + 1]),
                    "end_kind": kind,
                }
            )
    return result


def energy_profile(source, duration=None, timeout=ENERGY_TIMEOUT):
    """Voice level of the first audio stream in 20 ms frames (dB, floor -100).

    Decodes a 4 kHz mono copy with FFmpeg under a finite timeout. Returns
    ``None`` when the source is too long to measure cheaply.
    """
    from .childenv import child_env
    from .media import _local_path

    if duration is not None and duration > ENERGY_MAX_SOURCE_S:
        return None
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-i",
            str(_local_path(source)),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(ENERGY_RATE),
            "-f",
            "s16le",
            "pipe:1",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=timeout,
        shell=False,
        env=child_env(python=False),
    )
    samples = array.array("h")
    data = result.stdout
    samples.frombytes(data[: len(data) - len(data) % 2])
    size = int(ENERGY_RATE * ENERGY_STEP)
    scale = 32768.0 * 32768.0
    levels = []
    for offset in range(0, len(samples) - size + 1, size):
        chunk = samples[offset : offset + size]
        power = sum(map(operator.mul, chunk, chunk)) / (size * scale)
        levels.append(round(max(-100.0, 10 * math.log10(power + 1e-10)), 2))
    return {"step": ENERGY_STEP, "db": levels}


def _validated_energy(energy):
    if not energy:
        return None
    step = energy.get("step")
    levels = energy.get("db")
    if not isinstance(step, (int, float)) or step <= 0 or not isinstance(levels, list):
        return None
    if not levels:
        return None
    return float(step), levels


def _quietest(energy, low, high, preferred):
    """Time of the quietest frame in [low, high], nearest ``preferred`` on ties."""
    if energy is None or high <= low:
        return preferred
    step, levels = energy
    first = max(0, math.ceil(low / step - 1e-9))
    last = min(len(levels) - 1, math.floor(high / step + 1e-9))
    if last < first:
        return preferred
    floor = min(levels[first : last + 1])
    options = [i for i in range(first, last + 1) if levels[i] <= floor + 1.0]
    best = min(options, key=lambda i: (abs(i * step - preferred), i))
    return round(best * step, 3)


def _cut_before(words, index, energy):
    word = words[index]
    previous_end = words[index - 1]["end"] if index else 0.0
    gap = max(0.0, word["start"] - previous_end)
    preferred = word["start"] - min(0.25, gap / 2)
    low = max(0.0, word["start"] - 0.6, previous_end)
    return _quietest(energy, low, word["start"], preferred)


def _cut_after(words, index, energy, duration):
    word = words[index]
    next_start = words[index + 1]["start"] if index + 1 < len(words) else duration
    gap = max(0.0, next_start - word["end"])
    preferred = word["end"] + min(0.3, gap / 2)
    return min(
        duration,
        _quietest(
            energy, word["end"], min(duration, word["end"] + 0.6, next_start), preferred
        ),
    )


class _Context:
    """Prefix sums so every window is scored in constant time."""

    def __init__(self, words, duration, energy, faces, platform):
        self.words = _ordered(words)
        self.duration = duration
        self.energy = _validated_energy(energy)
        self.platform = platform
        self.sentences = sentences(self.words)
        self.punctuated = _punctuated(self.words)
        words = self.words
        prefix_end = [0.0]
        for word in words:
            prefix_end.append(max(prefix_end[-1], word["end"]))
        self.valid_starts = [
            prefix_end[s["first"]] <= s["start"]
            and (
                not self.punctuated
                or not s["index"]
                or self.sentences[s["index"] - 1]["end_kind"] in {"stop", "question"}
            )
            for s in self.sentences
        ]
        self.valid_ends = [
            prefix_end[s["last"] + 1] <= s["end"]
            and s["end"]
            <= (
                words[s["last"] + 1]["start"]
                if s["last"] + 1 < len(words)
                else duration
            )
            and (not self.punctuated or s["end_kind"] in {"stop", "question"})
            for s in self.sentences
        ]
        self.starts = [
            max(prefix_end[s["first"]], _cut_before(words, s["first"], self.energy))
            for s in self.sentences
        ]
        self.ends = [
            _cut_after(words, s["last"], self.energy, duration) for s in self.sentences
        ]
        self.prob = [0.0]
        self.long = [0]
        for index, word in enumerate(words):
            self.prob.append(self.prob[-1] + float(word.get("probability", 1.0)))
            gap = (
                words[index + 1]["start"] - word["end"] if index + 1 < len(words) else 0
            )
            self.long.append(self.long[-1] + (1 if gap >= LONG_PAUSE_S else 0))
        self.blocks = None
        if self.energy is not None:
            step, levels = self.energy
            per = max(1, round(BLOCK_S / step))
            values = []
            for offset in range(0, len(levels), per):
                chunk = levels[offset : offset + per]
                power = sum(10 ** (v / 10) for v in chunk) / len(chunk)
                values.append(10 * math.log10(power + 1e-10))
            ordered = sorted(values)
            floor = ordered[len(ordered) // 10] + 6 if ordered else 0
            speech = [v if v > floor else None for v in values]
            self.blocks = (per * step, speech)
            self.block_sum, self.block_sq, self.block_n = [0.0], [0.0], [0]
            for value in speech:
                self.block_sum.append(self.block_sum[-1] + (value or 0.0))
                self.block_sq.append(self.block_sq[-1] + (value or 0.0) ** 2)
                self.block_n.append(self.block_n[-1] + (value is not None))
            kept = [v for v in speech if v is not None]
            self.global_spread = _spread(sum(kept), sum(v * v for v in kept), len(kept))
        self.faces = None
        if faces:
            samples = sorted(
                (float(item[0]), bool(item[1]))
                for item in faces
                if isinstance(item, (list, tuple)) and len(item) >= 2
            )
            if samples:
                self.face_times = [t for t, _ in samples]
                self.face_seen = [0]
                for _, seen in samples:
                    self.face_seen.append(self.face_seen[-1] + seen)
                self.faces = True

    def spread(self, start, end):
        if self.blocks is None:
            return None
        size, speech = self.blocks
        a = max(0, int(start / size))
        b = min(len(speech), int(math.ceil(end / size)))
        n = self.block_n[b] - self.block_n[a]
        if n < 8:
            return None
        return _spread(
            self.block_sum[b] - self.block_sum[a],
            self.block_sq[b] - self.block_sq[a],
            n,
        )

    def face_ratio(self, start, end):
        if not self.faces:
            return None
        a = bisect.bisect_left(self.face_times, start)
        b = bisect.bisect_right(self.face_times, end)
        if b - a < 3:
            return None
        return (self.face_seen[b] - self.face_seen[a]) / (b - a)


def _spread(total, squares, count):
    if count < 2:
        return 0.0
    mean = total / count
    return math.sqrt(max(0.0, squares / count - mean * mean))


def _first_word(sentence_text):
    for token in sentence_text.split():
        bare = _bare(token)
        if bare:
            return token.strip("\"'“”‘’()[],.;:!?"), bare
    return "", ""


def _evaluate(context, i, j):
    """Score and reasons for the window of sentences i..j."""
    words = context.words
    first_sentence = context.sentences[i]
    last_sentence = context.sentences[j]
    a, b = first_sentence["first"], last_sentence["last"]
    start, end = context.starts[i], context.ends[j]
    duration = end - start
    reasons = []

    def note(text, points):
        if points:
            reasons.append({"text": text, "points": int(points)})

    # Opening line.
    opener = first_sentence["text"]
    tokens = [_bare(t) for t in opener.split()]
    hook = 0
    question = first_sentence["end_kind"] == "question" or (
        not context.punctuated and tokens and tokens[0] in _QUESTION_START
    )
    if question:
        note("Opens with a question", 12)
        hook += 12
    if any(re.search(r"\d", t) for t in tokens) or any(t in _NUMBERS for t in tokens):
        points = min(6, 20 - hook)
        note("Opens with a number", points)
        hook += points
    if any(t in _VIEWER for t in tokens):
        points = min(6, 20 - hook)
        note("Speaks to the viewer", points)
        hook += points
    if any(t in _CLAIMS for t in tokens):
        points = min(6, 20 - hook)
        note("Opens with a strong claim", points)
        hook += points
    if len(tokens) <= 10 and hook < 20:
        note("Short first line", min(3, 20 - hook))

    # Does it stand on its own?
    shown, bare = _first_word(opener)
    if bare in _DANGLING_STRONG:
        note(f'Starts mid-thought: "{shown}"', -15)
    elif bare in _DANGLING_WEAK:
        note(f'Starts mid-thought: "{shown}"', -8)
    elif bare in _POINTING_STRONG:
        note(f'Opens with "{shown}", which may point to something said earlier', -8)
    elif bare in _POINTING_WEAK:
        note(f'Opens with "{shown}", which may point to something said earlier', -4)
    if context.punctuated:
        if i > 0 and context.sentences[i - 1]["end_kind"] == "pause":
            note("Starts after a pause, not after a full stop", -4)
        if last_sentence["end_kind"] == "pause":
            note("Ends at a pause, not at a full stop", -4)
        else:
            note("Ends on a complete sentence", 5)

    # Delivery.
    count = b - a + 1
    span = max(0.1, words[b]["end"] - words[a]["start"])
    pace = count / span
    if pace < 1.6:
        note(f"Slow, with a lot of silence ({pace:.1f} words/s)", -6)
    elif pace > 4.2:
        note(f"Very fast speech ({pace:.1f} words/s)", -2)
    elif pace >= 2.0:
        note(f"Steady speaking pace ({pace:.1f} words/s)", 5)
    pauses = context.long[b] - context.long[a]
    if pauses:
        note(
            f"{pauses} long pause{'s' if pauses != 1 else ''} (over {LONG_PAUSE_S:g} s)",
            -min(12, 4 * pauses),
        )
    else:
        note("No long pauses", 3)
    clarity = (context.prob[b + 1] - context.prob[a]) / count
    if clarity < 0.6:
        note("Some words were hard to make out", -6)
    spread = context.spread(start, end)
    if spread is not None and context.global_spread:
        ratio = spread / context.global_spread
        if ratio >= 1.15:
            note("Lively delivery: the voice level varies", 4)
        elif ratio <= 0.8:
            note("Even, flat voice level", -2)
    seen = context.face_ratio(start, end)
    if seen is not None:
        if seen >= 0.9:
            note("Speaker on screen", 4)
        elif seen < 0.6:
            note(f"Speaker on screen only {round(seen * 100)} % of the time", -8)

    # Length.
    label = SHORT_FORM.get(context.platform)
    if label and duration > SHORT_FORM_MAX_S:
        note(f"Longer than the {SHORT_FORM_MAX_S} s that suits {label}", -5)
    elif 25 <= duration <= SHORT_FORM_MAX_S:
        note("A good length for short videos", 3)

    score = BASE_SCORE + sum(r["points"] for r in reasons)
    reasons.sort(key=lambda r: (-abs(r["points"]), r["text"]))
    return {
        "id": f"clip-{round(start * 1000)}-{round(end * 1000)}",
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 3),
        "speech_start": words[a]["start"],
        "speech_end": words[b]["end"],
        "first_word_id": words[a]["id"],
        "last_word_id": words[b]["id"],
        "sentence_count": j - i + 1,
        "word_count": count,
        "starts_after": "start"
        if i == 0
        else (
            "pause" if context.sentences[i - 1]["end_kind"] == "pause" else "sentence"
        ),
        "ends_with": "pause" if last_sentence["end_kind"] == "pause" else "sentence",
        "hook": opener[:300],
        "text": " ".join(w["text"] for w in words[a : b + 1])[:4000],
        "score": max(0, min(100, int(round(score)))),
        "reasons": reasons,
    }


def _bounds(min_s, max_s, count, platform):
    if platform is not None and platform not in PLATFORMS:
        raise ValueError(
            "Unsupported platform; expected one of: " + ", ".join(PLATFORMS)
        )
    default_max = SHORT_FORM_MAX_S if platform in SHORT_FORM else DEFAULT_MAX_S
    low = DEFAULT_MIN_S if min_s is None else _number(min_s, "min_s")
    high = default_max if max_s is None else _number(max_s, "max_s")
    if min_s is not None and max_s is None and high < low:
        high = DEFAULT_MAX_S
    if (
        not DEFAULT_MIN_S <= low <= DEFAULT_MAX_S
        or not DEFAULT_MIN_S <= high <= DEFAULT_MAX_S
    ):
        raise ValueError(
            f"Clip lengths must lie between {DEFAULT_MIN_S} and {DEFAULT_MAX_S} seconds"
        )
    if low > high:
        raise ValueError("min_s must not be larger than max_s")
    if count is None:
        count = DEFAULT_COUNT
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= MAX_COUNT
    ):
        raise ValueError(f"count must be a whole number from 1 to {MAX_COUNT}")
    as_int = lambda v: int(v) if float(v).is_integer() else v  # noqa: E731
    return as_int(low), as_int(high), count


def find_candidates(
    words,
    duration,
    *,
    min_s=None,
    max_s=None,
    count=None,
    platform=None,
    energy=None,
    faces=None,
):
    """Best non-overlapping sentence-bounded clips, ranked by score.

    ``energy`` is an :func:`energy_profile` result and ``faces`` the compact
    face samples of a Vision run (``[[time, [face, ...]], ...]``); both are
    optional. Returns the candidates with the settings that produced them.
    """
    low, high, count = _bounds(min_s, max_s, count, platform)
    duration = _number(duration, "duration")
    context = _Context(words or [], duration, energy, faces, platform)
    windows = []
    total = len(context.sentences)
    for i in range(total):
        if not context.valid_starts[i]:
            continue
        for j in range(i, total):
            length = context.ends[j] - context.starts[i]
            if length > high + 1e-9:
                break
            if context.valid_ends[j] and length >= low - 1e-9:
                windows.append(_evaluate(context, i, j))
    windows.sort(key=lambda w: (-w["score"], w["start"], w["end"]))
    picked = []
    while len(picked) < count:
        best, best_value = None, None
        for window in windows:
            if any(
                window["start"] < p["end"] and p["start"] < window["end"]
                for p in picked
            ):
                continue
            middle = (window["start"] + window["end"]) / 2
            near = sum(
                1
                for p in picked
                if abs((p["start"] + p["end"]) / 2 - middle) < SPREAD_S
            )
            value = window["score"] - SPREAD_PENALTY * near
            if best_value is None or value > best_value:
                best, best_value = window, value
        if best is None:
            break
        picked.append(best)
    picked.sort(key=lambda w: (-w["score"], w["start"]))
    for rank, item in enumerate(picked, 1):
        item["rank"] = rank
    return {
        "candidates": picked,
        "settings": {"min_s": low, "max_s": high, "count": count, "platform": platform},
        "mode": "punctuation" if context.punctuated else "pauses",
        "sentence_count": total,
        "energy": context.energy is not None,
        "faces": bool(context.faces),
    }


def score_range(
    words, duration, first_id, last_id, *, energy=None, faces=None, platform=None
):
    """Candidate record for the sentences from word ``first_id`` to ``last_id``."""
    context = _Context(
        words or [], _number(duration, "duration"), energy, faces, platform
    )
    starts = {s["first_id"]: s["index"] for s in context.sentences}
    ends = {s["last_id"]: s["index"] for s in context.sentences}
    if (
        first_id not in starts
        or last_id not in ends
        or ends[last_id] < starts[first_id]
        or not context.valid_starts[starts[first_id]]
        or not context.valid_ends[ends[last_id]]
    ):
        raise ValueError("Clips must start and end on sentence boundaries")
    return _evaluate(context, starts[first_id], ends[last_id])


def validate_pick(candidate_id=None, start=None, end=None):
    """Reject ambiguous picks before any project or media is opened."""
    if candidate_id is not None:
        if start is not None or end is not None:
            raise ValueError("Give a candidate_id or start and end, not both")
        if not isinstance(candidate_id, str) or not re.fullmatch(
            r"clip-[0-9]{1,10}-[0-9]{1,10}", candidate_id
        ):
            raise ValueError("Unknown clip candidate; Find clips again")
    else:
        if start is None or end is None:
            raise ValueError("Give a candidate_id or both start and end")
        start, end = _number(start, "start"), _number(end, "end")
        if not 0 <= start < end <= ENERGY_MAX_SOURCE_S:
            raise ValueError(
                "A range must end after it starts and fit inside three hours"
            )


def snap_range(words, duration, start, end, *, energy=None):
    """Snap a free range to the nearest sentence start and sentence end."""
    duration = _number(duration, "duration")
    start, end = _number(start, "start"), _number(end, "end")
    if not 0 <= start < end <= duration:
        raise ValueError("The range must lie inside the source and end after it starts")
    context = _Context(words or [], duration, energy, None, None)
    if not context.sentences:
        raise ValueError("Finding sentence boundaries needs a transcript with words")
    found = context.sentences
    eligible = [k for k in range(len(found)) if context.valid_starts[k]]
    if not eligible:
        raise ValueError("No safe sentence boundaries; check the word timings")
    i = min(eligible, key=lambda k: (abs(found[k]["start"] - start), k))
    later = [k for k in range(i, len(found)) if context.valid_ends[k]]
    if not later:
        raise ValueError("No safe sentence end; choose an earlier range")
    j = min(later, key=lambda k: (abs(found[k]["end"] - end), k))
    begin, finish = context.starts[i], context.ends[j]
    if finish - begin < MIN_CLIP_S:
        raise ValueError(
            f"A clip must be at least {MIN_CLIP_S:g} s of whole sentences; "
            "choose a longer range"
        )
    return {
        "start": round(begin, 3),
        "end": round(finish, 3),
        "first_word_id": found[i]["first_id"],
        "last_word_id": found[j]["last_id"],
    }
