"""Local, subprocess-backed FFmpeg media operations."""

import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

try:
    from .childenv import child_env
except ImportError:  # loaded as a standalone module file
    from cutroom.childenv import child_env

PROCESS_TIMEOUT = 300


def _local_path(value, *, must_exist=True):
    raw = os.fspath(value)
    normalized = raw.replace("\\", "/")
    drive = re.match(r"^[A-Za-z]:/", normalized)
    if (
        not raw
        or "\x00" in raw
        or normalized.startswith("//")
        or ":" in (normalized[2:] if drive else normalized)
    ):
        raise ValueError("Only local file paths are allowed")
    path = Path(raw).resolve()
    if str(path).replace("\\", "/").startswith("//"):
        raise ValueError("Network paths are not allowed")
    if must_exist and not path.is_file():
        raise FileNotFoundError(f"Input is not a regular file: {path}")
    return path


def _number(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError("Expected a finite number")
    return float(value)


def _run(arguments):
    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=PROCESS_TIMEOUT,
        shell=False,
        env=child_env(python=False),
    )


def render(source: str | Path, segments: list[dict], output: str | Path) -> dict:
    """Re-encode kept intervals and publish without replacing an existing file."""
    source = _local_path(source)
    requested_output = Path(output).expanduser()
    output = _local_path(requested_output, must_exist=False)
    if requested_output.is_symlink() or output.exists() or output.is_symlink():
        raise FileExistsError(f"Output already exists: {output}")
    metadata = probe(source)
    has_audio = metadata["has_audio"]
    if not isinstance(segments, list) or not segments:
        raise ValueError("At least one segment is required")
    filters = []
    labels = []
    previous_end = 0.0
    for index, segment in enumerate(segments):
        if (
            not isinstance(segment, dict)
            or "start" not in segment
            or "end" not in segment
        ):
            raise ValueError("Each segment requires start and end")
        start, end = _number(segment["start"]), _number(segment["end"])
        if start < previous_end or end <= start or end > metadata["duration"]:
            raise ValueError(
                "Segments must be ordered, non-overlapping, and within the source duration"
            )
        previous_end = end
        filters.append(
            f"[0:v:0]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]"
        )
        labels.append(f"[v{index}]")
        if has_audio:
            filters.append(
                f"[0:a:0]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]"
            )
            labels.append(f"[a{index}]")
    filters.append(
        "".join(labels)
        + f"concat=n={len(segments)}:v=1:a={int(has_audio)}[v]"
        + ("[a]" if has_audio else "")
    )
    directory = Path(tempfile.mkdtemp(prefix=".cutroom-", dir=output.parent))
    intermediate = directory / ("render" + output.suffix)
    try:
        _run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-n",
                "-protocol_whitelist",
                "file",
                "-i",
                str(source),
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[v]",
                *(["-map", "[a]"] if has_audio else []),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                str(intermediate),
            ]
        )
        metadata = probe(intermediate)
        os.link(intermediate, output)
        return {"output": str(output), **metadata}
    finally:
        intermediate.unlink(missing_ok=True)
        directory.rmdir()


def detect_silences(source: str | Path, noise_db=-35.0, min_duration=0.5) -> list[dict]:
    """Return silence intervals, including silence ending at EOF."""
    noise_db, min_duration = _number(noise_db), _number(min_duration)
    if min_duration <= 0:
        raise ValueError("Minimum silence duration must be positive")
    metadata = probe(source)
    if not metadata["has_audio"]:
        return []
    result = _run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-protocol_whitelist",
            "file",
            "-i",
            str(_local_path(source)),
            "-vn",
            "-af",
            f"silencedetect=noise={noise_db}dB:d={min_duration}",
            "-f",
            "null",
            "-",
        ]
    )
    duration = metadata["duration"]
    intervals = []
    start = None
    for kind, value in re.findall(
        r"silence_(start|end):\s*([\d.eE+\-]+)", result.stderr
    ):
        point = min(duration, max(0.0, float(value)))
        if kind == "start":
            start = point
        elif start is not None:
            if point > start:
                intervals.append({"start": start, "end": point})
            start = None
    if start is not None and start < duration:
        intervals.append({"start": start, "end": duration})
    return intervals


def probe(source: str | Path) -> dict:
    """Read actual media metadata using ffprobe."""
    source = _local_path(source)
    result = _run(
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
    )
    data = json.loads(result.stdout)
    video = next(
        (stream for stream in data["streams"] if stream["codec_type"] == "video"),
        None,
    )
    if video is None:
        raise ValueError(
            "A video stream is required; audio-only files are not supported"
        )
    duration = _number(float(data["format"]["duration"]))
    if duration <= 0:
        raise ValueError("Media duration must be positive")
    return {
        "duration": duration,
        "width": int(video["width"]),
        "height": int(video["height"]),
        "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
    }
