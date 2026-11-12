"""Local transcription, non-destructive text edits, and subtitle exports."""

import html
import json
import math
import subprocess
import unicodedata
from pathlib import Path

from .childenv import child_env
from .media import PROCESS_TIMEOUT, _local_path, _number, _run


def _validate_words(words, duration=None):
    if not isinstance(words, list):
        raise ValueError("Words must be a list")
    if duration is not None:
        duration = _number(duration)
        if duration < 0:
            raise ValueError("Duration must be non-negative")
    last_id, last_start = -1, 0.0
    for word in words:
        if not isinstance(word, dict):
            raise ValueError("Each word must be an object")
        identifier = word.get("id")
        if type(identifier) is not int or identifier <= last_id:
            raise ValueError("Word IDs must be non-negative and strictly increasing")
        start, end = _number(word.get("start")), _number(word.get("end"))
        if (
            start < last_start
            or end < start
            or (duration is not None and end > duration)
        ):
            raise ValueError("Word times must be ordered and within the source")
        probability = _number(word.get("probability"))
        if not 0 <= probability <= 1:
            raise ValueError("Word probability must be between zero and one")
        if not isinstance(word.get("text"), str) or not word["text"].strip():
            raise ValueError("Word text must be non-empty")
        last_id, last_start = identifier, start
    return words


def validate_transcript(data, duration=None):
    """Validate without mutation; word starts and IDs are ordered, overlaps are allowed."""
    if not isinstance(data, dict):
        raise ValueError("Transcript must be an object")
    if data.get("language") is not None and (
        not isinstance(data["language"], str) or not data["language"].strip()
    ):
        raise ValueError("Language must be a language code or null")
    if "language" not in data or not isinstance(data.get("text"), str):
        raise ValueError("Transcript requires language and text")
    if not isinstance(data.get("engine"), str) or not data["engine"].strip():
        raise ValueError("Transcript requires an engine")
    if data.get("status") not in ("ok", "no_audio"):
        raise ValueError("Unsupported transcript status")
    _validate_words(data.get("words"), duration)
    if data["status"] == "no_audio" and (data["words"] or data["text"]):
        raise ValueError("A no-audio transcript must be empty")
    return data


def word_segments(words, excluded_ids=None, padding=0.04, duration=None):
    """Union kept word intervals, never padding across explicitly excluded audio.

    Overlapping excluded timestamps take precedence over kept timestamps. The
    caller must approve exclusions; this function does not identify fillers.
    """
    _validate_words(words, duration)
    padding = _number(padding)
    if padding < 0:
        raise ValueError("Padding must be non-negative")
    excluded_ids = [] if excluded_ids is None else excluded_ids
    if not isinstance(excluded_ids, (list, tuple, set, frozenset)) or any(
        type(identifier) is not int for identifier in excluded_ids
    ):
        raise ValueError("Excluded IDs must be a collection of integers")
    excluded = set(excluded_ids)
    if not excluded <= {word["id"] for word in words}:
        raise ValueError("Excluded IDs must exist in the transcript")
    blocked = [word for word in words if word["id"] in excluded]
    intervals = []
    for word in words:
        if word["id"] in excluded or word["end"] == word["start"]:
            continue
        start = max(0.0, word["start"] - padding)
        end = word["end"] + padding
        if duration is not None:
            end = min(duration, end)
        if not __import__("math").isfinite(end):
            raise ValueError("Padded boundary must be finite")
        pieces = [(start, end)]
        for removed in blocked:
            remaining = []
            for left, right in pieces:
                if removed["end"] <= left or removed["start"] >= right:
                    remaining.append((left, right))
                else:
                    if left < removed["start"]:
                        remaining.append((left, removed["start"]))
                    if removed["end"] < right:
                        remaining.append((removed["end"], right))
            pieces = remaining
        intervals.extend(pieces)
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1]["end"]:
            merged[-1]["end"] = max(end, merged[-1]["end"])
        else:
            merged.append({"start": float(start), "end": float(end)})
    return merged


def _validate_segments(segments):
    if not isinstance(segments, list):
        raise ValueError("Segments must be a list")
    previous_end = 0.0
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Each segment must be an object")
        start, end = _number(segment.get("start")), _number(segment.get("end"))
        if start < previous_end or end <= start:
            raise ValueError("Segments must be positive, ordered, and non-overlapping")
        previous_end = end
    return segments


def remap_words(words, segments):
    """Clip into half-open source intervals and map each fragment to output time.

    Output IDs are new, ordered fragment IDs. source_id and source_start/end
    preserve the original word; kept_source_start/end identify the kept fragment.
    A word crossing multiple kept intervals produces multiple timed fragments.
    """
    _validate_words(words)
    _validate_segments(segments)
    output, offset = [], 0.0
    for segment in segments:
        for word in words:
            start = max(word["start"], segment["start"])
            end = min(word["end"], segment["end"])
            if start >= end:
                continue
            output.append(
                {
                    **word,
                    "id": len(output),
                    "source_id": word["id"],
                    "source_start": word["start"],
                    "source_end": word["end"],
                    "kept_source_start": start,
                    "kept_source_end": end,
                    "start": offset + start - segment["start"],
                    "end": offset + end - segment["start"],
                }
            )
        offset += segment["end"] - segment["start"]
        if not math.isfinite(offset):
            raise ValueError("Output duration must be finite")
    return output


def filler_suggestions(words, language="en"):
    """Lexical candidates only: ordinary uses of 'like' or 'yani' need review."""
    _validate_words(words)
    if not isinstance(language, str):
        raise ValueError("Language must be a language code")
    lexicons = {
        "en": (
            "um",
            "uh",
            "er",
            "erm",
            "hmm",
            "like",
            "you know",
            "i mean",
            "sort of",
            "kind of",
        ),
        "tr": (
            "şey",
            "yani",
            "hani",
            "eee",
            "ıı",
            "ııı",
            "ıııı",
            "ee",
            "bir bakıma",
            "işte",
        ),
    }
    phrases = sorted(
        (
            tuple(item.split())
            for item in lexicons.get(language.lower().split("-")[0], ())
        ),
        key=len,
        reverse=True,
    )

    def normalize(text):
        text = unicodedata.normalize("NFC", text)
        if language.lower().startswith("tr"):
            text = text.replace("I", "ı").replace("İ", "i")
        return "".join(
            c for c in text.casefold() if not unicodedata.category(c).startswith("P")
        ).strip()

    tokens = [normalize(word["text"]) for word in words]
    suggestions, cursor = [], 0
    while cursor < len(words):
        for phrase in phrases:
            selected = words[cursor : cursor + len(phrase)]
            if tuple(tokens[cursor : cursor + len(phrase)]) != phrase or any(
                right["start"] - left["end"] > 0.5
                for left, right in zip(selected, selected[1:])
            ):
                continue
            suggestions.append(
                dict(
                    word_ids=[w["id"] for w in selected],
                    start=selected[0]["start"],
                    end=max(w["end"] for w in selected),
                    text=" ".join(w["text"] for w in selected),
                    reason="lexical_filler_candidate",
                    status="suggestion",
                    requires_review=True,
                )
            )
            cursor += len(phrase)
            break
        else:
            cursor += 1
    return suggestions


def caption_cues(words, max_words=6, max_duration=3):
    """Group timed words greedily; repeat an overlong word across bounded cues.

    Input overlap is retained rather than fabricating word timing. Zero-duration
    words join adjacent words; a wholly zero-duration group has no display cue.
    """
    _validate_words(words)
    max_duration = _number(max_duration)
    if type(max_words) is not int or max_words < 1 or max_duration <= 0:
        raise ValueError(
            "Caption limits must be positive; max_words must be an integer"
        )
    cues, group = [], []

    def emit(selected):
        start = selected[0]["start"]
        end = max(word["end"] for word in selected)
        text = " ".join(word["text"].strip() for word in selected)
        while start < end:
            boundary = min(end, start + max_duration)
            if boundary <= start:
                raise ValueError("Caption duration is below timeline precision")
            cues.append(
                dict(
                    start=start,
                    end=boundary,
                    text=text,
                    word_ids=[word["id"] for word in selected],
                )
            )
            start = boundary

    for word in words:
        if group and (
            len(group) >= max_words
            or max(word["end"], *(w["end"] for w in group)) - group[0]["start"]
            > max_duration
        ):
            emit(group)
            group = []
        group.append(word)
    if group:
        emit(group)
    return sorted(cues, key=lambda cue: (cue["start"], cue["end"]))


def _subtitle_tick(seconds, rate):
    scaled = _number(seconds) * rate
    if scaled < 0 or not math.isfinite(scaled):
        raise ValueError("Subtitle timestamp is outside representable bounds")
    return int(scaled + 0.5)


def _subtitle_time(ticks, rate, separator):
    whole, fraction = divmod(ticks, rate)
    hours, remainder = divmod(whole, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{fraction:0{3 if rate == 1000 else 2}}"


def write_subtitles(cues, path, format="srt", brand=None):
    """Write a local UTF-8 subtitle file exclusively, with literal cue text."""
    if format not in ("srt", "vtt", "ass"):
        raise ValueError("Subtitle format must be srt, vtt, or ass")
    style = None
    if brand is not None or format == "ass":
        from .postproduction import validate_brand

        style = validate_brand({} if brand is None else brand)
    if not isinstance(cues, list):
        raise ValueError("Cues must be a list")
    requested = Path(path)
    if requested.is_symlink():
        raise FileExistsError("Output is an existing symbolic link")
    path = _local_path(path, must_exist=False)
    previous_start, entries = 0.0, []
    for index, cue in enumerate(cues, 1):
        if not isinstance(cue, dict):
            raise ValueError("Each cue must be an object")
        start, end = _number(cue.get("start")), _number(cue.get("end"))
        if start < previous_start or end <= start:
            raise ValueError("Cues require ordered starts and positive durations")
        if not isinstance(cue.get("text"), str) or not cue["text"].strip():
            raise ValueError("Cue text must be non-empty")
        literal = " ".join(cue["text"].replace("\x00", "").split())
        text = html.escape(literal, quote=False)
        rate = 100 if format == "ass" else 1000
        start_tick = _subtitle_tick(start, rate)
        end_tick = max(start_tick + 1, _subtitle_tick(end, rate))
        if format == "ass":
            text = literal.translate(str.maketrans({"\\": "＼", "{": "｛", "}": "｝"}))
            entries.append(
                f"Dialogue: 0,{_subtitle_time(start_tick, rate, '.')},"
                f"{_subtitle_time(end_tick, rate, '.')},Default,,0,0,0,,{text}\n"
            )
        else:
            separator = "," if format == "srt" else "."
            entries.append(
                f"{index}\n{_subtitle_time(start_tick, rate, separator)} --> "
                f"{_subtitle_time(end_tick, rate, separator)}\n{text}\n\n"
            )
        previous_start = start
    header = "WEBVTT\n\n" if format == "vtt" else ""
    if format == "ass":
        color = style["subtitle_color"].lstrip("#")
        bgr = color[4:6] + color[2:4] + color[0:2]
        alignment = {"left": 1, "center": 2, "right": 3}[style["alignment"]]
        margin = round(style["safe_margin"] * 1080)
        margin_v = round((1 - style["subtitle_y"]) * 1080)
        header = (
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1080\n"
            "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,{style['font']},{style['subtitle_size']:g},&H00{bgr},&H00{bgr},"
            f"&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,{alignment},{margin},{margin},{margin_v},1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
    content = header + "".join(entries)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    return dict(path=str(path), format=format, cue_count=len(cues))


def local_model_files(model_path):
    """Validate the local model and enumerate inference assets for job fingerprints."""
    if not isinstance(model_path, (str, Path)) or not str(model_path):
        raise ValueError("Configure an existing local Whisper model directory")
    model_path = _local_path(model_path, must_exist=False)
    if not model_path.is_dir():
        raise FileNotFoundError("Model must be an existing local directory")
    files = []
    required = ("config.json", "model.bin", "tokenizer.json")
    optional = ("vocabulary.txt", "vocabulary.json", "preprocessor_config.json")
    for filename in (*required, *optional):
        requested = model_path / filename
        if (
            filename in optional
            and not requested.exists()
            and not requested.is_symlink()
        ):
            continue
        asset = _local_path(requested)
        if asset.parent != model_path or asset.stat().st_size == 0:
            raise ValueError(
                "Model assets must be non-empty local files within the model directory"
            )
        files.append(asset)
    return files


def transcribe(source, model_path, language=None):
    """Transcribe local audio or video; silent media never loads a model."""
    source = _local_path(source)
    metadata = json.loads(
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
            ]
        ).stdout
    )
    if not any(stream.get("codec_type") == "audio" for stream in metadata["streams"]):
        return dict(
            language=None, words=[], text="", engine="faster-whisper", status="no_audio"
        )
    model_path = local_model_files(model_path)[0].parent
    if language is not None and (not isinstance(language, str) or not language.strip()):
        raise ValueError("Language must be a language code or null")
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "Local transcription requires the optional faster-whisper package"
        ) from error
    model = WhisperModel(
        str(model_path), device="cpu", compute_type="int8", local_files_only=True
    )
    import numpy as np

    decoded = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-protocol_whitelist",
            "file",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "f32le",
            "pipe:1",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        env=child_env(python=False),
        timeout=PROCESS_TIMEOUT,
        shell=False,
    )
    audio = np.frombuffer(decoded.stdout, dtype="<f4").copy()
    segments, info = model.transcribe(audio, language=language, word_timestamps=True)
    words, texts = [], []
    for segment in segments:
        texts.append(segment.text.strip())
        for item in segment.words or []:
            if not item.word.strip():
                continue
            words.append(
                dict(
                    id=len(words),
                    start=float(item.start),
                    end=float(item.end),
                    text=item.word.strip(),
                    probability=float(item.probability),
                )
            )
    result = dict(
        language=info.language,
        words=words,
        text=" ".join(texts).strip(),
        engine="faster-whisper",
        status="ok",
    )
    duration = _number(float(metadata["format"]["duration"]))
    return validate_transcript(result, duration=duration)
