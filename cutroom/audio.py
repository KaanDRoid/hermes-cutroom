"""Local audio assets and deterministic speech-aware mixing."""

import array
import bisect
import math
import re
import subprocess
import time
from pathlib import Path

from .project import file_digest

MUSIC_MAX_BYTES = 256 * 1024 * 1024
_DATA_FORMATS = {
    "wav",
    "mp3",
    "flac",
    "ogg",
    "aac",
    "mov",
    "mp4",
    "m4a",
    "3gp",
    "3g2",
    "mj2",
    "aiff",
    "matroska",
    "webm",
}
_COMPUTED = {"sha256", "duration", "format"}


def _number(value, low, high):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError("Audio number outside allowed bounds")
    return float(value)


def _asset(spec, allowed, maximum_duration):
    import json
    import subprocess

    from .postproduction import _path, _run

    if (
        not isinstance(spec, dict)
        or set(spec) - allowed - _COMPUTED
        or not isinstance(spec.get("path"), str)
        or not spec["path"]
    ):
        raise ValueError("Audio asset needs a local path and known fields")
    if not Path(spec["path"]).is_absolute():
        # A relative path would depend on the server's working directory.
        raise ValueError(
            "Audio asset path must be absolute (for example C:/Music/bed.wav)"
        )
    path = _path(spec["path"])
    if path.stat().st_size > MUSIC_MAX_BYTES:
        raise ValueError("Audio asset is larger than 256 MiB")
    if path.stat().st_size == 0:
        raise ValueError("Audio asset is empty")
    before = file_digest(path)
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
                    "-show_format",
                    "-of",
                    "json",
                    str(path),
                ],
                timeout=30,
            ).stdout
        )
        formats = data["format"]["format_name"]
        if not set(formats.split(",")) <= _DATA_FORMATS or not any(
            s.get("codec_type") == "audio" for s in data["streams"]
        ):
            raise ValueError("A local audio data file is required")
        duration = _number(float(data["format"]["duration"]), 0.001, maximum_duration)
    except (subprocess.SubprocessError, KeyError, TypeError) as error:
        raise ValueError("Cannot probe audio data file") from error
    if before != file_digest(path):
        raise PermissionError("Audio file changed during validation")
    return dict(path=str(path), sha256=before, duration=duration, format=formats)


def normalize_music(spec):
    if spec is None:
        return None
    result = _asset(
        spec,
        {
            "path",
            "volume_db",
            "fade_in",
            "fade_out",
            "duck",
            "duck_db",
            "loop",
            "start_offset",
            "source_note",
        },
        86400,
    )
    for key, default, low, high in (
        ("volume_db", -18, -60, 0),
        ("fade_in", 0.5, 0, 30),
        ("fade_out", 0.5, 0, 30),
        ("duck_db", 12, 12, 36),
        ("start_offset", 0, 0, result["duration"]),
    ):
        result[key] = _number(spec.get(key, default), low, high)
    if result["start_offset"] >= result["duration"]:
        raise ValueError("Music offset must precede the end")
    for key in ("duck", "loop"):
        value = spec.get(key, True)
        if not isinstance(value, bool):
            raise ValueError(key + " must be boolean")
        result[key] = value
    note = spec.get("source_note", "")
    if (
        not isinstance(note, str)
        or len(note) > 2000
        or any(ord(c) < 32 and c != "\n" for c in note)
    ):
        raise ValueError("Invalid music source note")
    result["source_note"] = note
    return result


def normalize_cut_sfx(spec):
    if spec is None:
        return None
    result = _asset(spec, {"path", "volume_db"}, 5)
    result["volume_db"] = _number(spec.get("volume_db", -12), -60, 0)
    return result


def validate_voice_cleanup(value):
    if value not in ("off", "light", "strong"):
        raise ValueError("voice_cleanup must be off, light or strong")
    return value


# afftdn delays its output by half of its 50 ms analysis window. At a fixed
# 48 kHz input that is 1200 samples; without compensation speech drifts 25 ms
# behind the picture.
DENOISE_LATENCY = 1200


def cleanup_filters(value):
    validate_voice_cleanup(value)
    if value == "off":
        return []
    filters = [
        "highpass=f=80:p=2",
        "aresample=48000",
        f"apad=pad_len={DENOISE_LATENCY}",
        "afftdn=nf=-25:nr=" + ("18" if value == "strong" else "12"),
        f"atrim=start_sample={DENOISE_LATENCY}",
        "asetpts=PTS-STARTPTS",
        "acompressor=threshold=0.125:ratio=2:attack=10:release=100:makeup=1",
    ]
    if value == "strong":
        filters.append("deesser=i=0.2")
    return filters


def limit_peaks(path, directory, gain_db, ceiling_db, timeout, name="mix-limited.wav"):
    """Raise a mix by gain_db and limit its peaks to ceiling_db.

    Used when the loudness gain would push peaks over the true-peak limit. The
    mix is 32-bit float, so the gain cannot clip before the limiter. The limiter
    runs at 4x the sample rate to catch inter-sample peaks, and its look-ahead
    delay is compensated so speech stays on its frames.
    """
    from .postproduction import _run

    limit = min(1.0, max(0.0625, 10 ** (ceiling_db / 20)))
    output = directory / name
    chain = f"volume={gain_db:.3f}dB,aresample=192000,alimiter=limit={limit:.6f}:attack=1:release=50:level=0:latency=1,aresample=48000"
    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-protocol_whitelist",
            "file",
            "-i",
            str(path),
            "-af",
            chain,
            "-c:a",
            "pcm_f32le",
            str(output),
        ],
        timeout=timeout,
    )
    return output


def parse_levels(path):
    result, moment = [], None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.search(r"pts_time:([-+\deE.]+)", line)
        if match:
            moment = float(match[1])
        elif moment is not None and "RMS_level=" in line:
            value = float(line.split("=", 1)[1])
            result.append((moment, max(-120.0, value)))
    return result


def speech_intervals(levels, window=0.05):
    finite = [level for _, level in levels if math.isfinite(level)]
    threshold = max(-50, max(finite, default=-120) - 30)
    result = []
    for moment, level in levels:
        if level <= threshold:
            continue
        end = round(moment + window, 6)
        if result and moment - result[-1][1] <= 0.25:
            result[-1] = (result[-1][0], end)
        else:
            result.append((moment, end))
    return result


ATTACK = 0.15
RELEASE = 0.25
RATE = 48000
_CHUNK = 1 << 20
# Loops with more copies than this repeat a buffered segment instead.
_CONCAT_LIMIT = 16
# Short fade that closes music followed by silence, avoiding a click.
ANTI_CLICK = 0.01


def envelope_gain(intervals, depth):
    """Reference ducking gain at one time; slow, kept for tests and spot checks."""
    floor = 10 ** (-depth / 20)

    def gain(time):
        amount = max(
            (
                max(
                    0,
                    min(1, (time - (start - 0.15)) / 0.15, (end + 0.25 - time) / 0.25),
                )
                for start, end in intervals
            ),
            default=0,
        )
        return 1 - amount * (1 - floor)

    return gain


def _first_at_or_after(x):
    """Smallest sample index whose time is >= x."""
    index = max(0, math.ceil(x * RATE))
    while index > 0 and (index - 1) / RATE >= x:
        index -= 1
    while index / RATE < x:
        index += 1
    return index


def _first_after(x):
    """Smallest sample index whose time is > x."""
    index = _first_at_or_after(x)
    while index / RATE <= x:
        index += 1
    return index


def envelope_chunks(intervals, depth, count, typecode="h"):
    """Yield the ducking gain for samples 0..count-1 as arrays.

    Same values as envelope_gain, built piecewise: each speech interval adds an
    attack ramp, a floor plateau and a release ramp. Runs at unity or at the
    floor are filled by array repetition, single ramps come from cached
    tables, and only overlapping ramps are evaluated sample by sample. typecode
    "h" yields 16-bit PCM (round(32767 * gain)), "d" the gain itself.
    """
    floor = 10 ** (-depth / 20)
    span = 1 - floor
    pcm = typecode == "h"

    def convert(value):
        return round(32767 * value) if pcm else value

    pieces = []  # (first, stop, kind, start, end): kind 0 attack, 1 plateau, 2 release
    for start, end in intervals:
        a = _first_at_or_after(start - ATTACK)
        b = _first_at_or_after(start)
        c = _first_after(end)
        d = _first_at_or_after(end + RELEASE)
        for first, stop, kind in ((a, b, 0), (b, c, 1), (c, d, 2)):
            first, stop = min(first, count), min(stop, count)
            if first < stop:
                pieces.append((first, stop, kind, start, end))
    tables = {}

    def amount(piece, index):
        _, _, kind, start, end = piece
        t = index / RATE
        if kind == 1:
            return 1.0
        if kind == 0:
            return max(0.0, min(1.0, (t - (start - ATTACK)) / ATTACK))
        return max(0.0, min(1.0, (end + RELEASE - t) / RELEASE))

    def table(piece):
        first, stop, kind, start, end = piece
        # Ramps on the same sample phase share one table.
        origin = (start - ATTACK) * RATE if kind == 0 else (end + RELEASE) * RATE
        key = (kind, stop - first, round(origin - first, 6))
        if key not in tables:
            gains = array.array(
                "d", (1 - amount(piece, first + k) * span for k in range(stop - first))
            )
            tables[key] = (
                gains,
                array.array(typecode, (convert(g) for g in gains)) if pcm else gains,
            )
        return tables[key]

    def constant(value, length):
        unit = array.array(typecode, [convert(value)])
        while length > 0:
            size = min(length, _CHUNK)
            yield unit * size
            length -= size

    bounds = sorted({0, count, *(p[0] for p in pieces), *(p[1] for p in pieces)})
    pieces.sort()
    active, cursor = [], 0
    for left, right in zip(bounds, bounds[1:]):
        while cursor < len(pieces) and pieces[cursor][0] <= left:
            active.append(pieces[cursor])
            cursor += 1
        active = [p for p in active if p[1] > left]
        if not active:
            yield from constant(1.0, right - left)
        elif any(p[2] == 1 for p in active):
            yield from constant(floor, right - left)
        elif len(active) == 1:
            piece = active[0]
            yield table(piece)[1][left - piece[0] : right - piece[0]]
        else:
            # Overlapping ramps between close speech runs: the deepest gain wins.
            gains = array.array(
                "d",
                (
                    1 - max(amount(p, index) for p in active) * span
                    for index in range(left, right)
                ),
            )
            yield array.array(typecode, (convert(g) for g in gains)) if pcm else gains


def write_envelope(path, intervals, depth, count, *, deadline):
    """Write the ducking gain as 48 kHz mono 16-bit PCM before the deadline."""
    import wave

    if time.monotonic() > deadline:
        raise subprocess.TimeoutExpired("ducking envelope", 0)
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        for block in envelope_chunks(intervals, depth, count):
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired("ducking envelope", 0)
            stream.writeframes(block.tobytes())
    return path


def validate_settings(spec, *, check_hash=True):
    if spec is None:
        return None
    if not isinstance(spec, dict) or set(spec) - {"music", "cut_sfx", "voice_cleanup"}:
        raise ValueError("Unknown audio settings")
    result = {"voice_cleanup": validate_voice_cleanup(spec.get("voice_cleanup", "off"))}
    for key, normalize, label in (
        ("music", normalize_music, "Music"),
        ("cut_sfx", normalize_cut_sfx, "Sound effect"),
    ):
        value = spec.get(key)
        if value is not None:
            normalized = normalize(value)
            if (
                check_hash
                and value.get("sha256")
                and value["sha256"] != normalized["sha256"]
            ):
                raise PermissionError(label + " file changed; select the file again")
            result[key] = normalized
    return result if len(result) > 1 or result["voice_cleanup"] != "off" else None


def _levels(path, directory, name, timeout):
    from .postproduction import _run

    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-i",
            str(path),
            "-af",
            "aresample=48000,asetnsamples=n=2400:p=0,astats=metadata=1:reset=1,"
            + f"ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file={name}",
            "-f",
            "null",
            "-",
        ],
        cwd=directory,
        timeout=timeout,
    )
    return parse_levels(directory / name)


def _duck_measurement(levels, intervals, duration, requested):
    speech, pauses = [], []
    ordered = sorted(intervals)
    starts = [start for start, _ in ordered]
    ends = [end for _, end in ordered]
    # Speech runs are sorted and disjoint, so the latest run starting before a
    # time is the only one that can contain it (and the latest end bounds it).
    for moment, level in levels:
        index = bisect.bisect_right(starts, moment - 0.2) - 1
        late = bisect.bisect_right(starts, moment + 0.3) - 1
        if index >= 0 and moment <= ends[index] - 0.25:
            speech.append(level)
        elif 0.6 <= moment <= duration - 0.6 and not (
            late >= 0 and moment <= ends[late] + 0.4
        ):
            pauses.append(level)

    def energy(values):
        return 10 * math.log10(sum(10 ** (v / 10) for v in values) / len(values))

    depth = energy(pauses) - energy(speech) if speech and pauses else None
    return dict(
        depth_db=depth,
        requested_db=requested,
        speech_windows=len(speech),
        pause_windows=len(pauses),
        method="measured music stem RMS in speech/pause plateaus before final normalization",
        intervals=intervals,
    )


def prepare_mix(
    source, audio_graph, directory, duration, spec, ranges, *, has_audio, timeout
):
    """Render an exact-length PCM mix before the final two-pass loudnorm scan.

    timeout bounds the whole preparation, not each step.
    """
    from .postproduction import _render_graph, _run

    deadline = time.monotonic() + timeout

    def remaining():
        left = deadline - time.monotonic()
        if left <= 0:
            raise subprocess.TimeoutExpired("audio mix", timeout)
        return left

    voice = directory / "voice.wav"
    chain = cleanup_filters(spec["voice_cleanup"])
    chain += ["aresample=48000", f"apad,atrim=duration={duration:.6f}"]
    if has_audio:
        graph = audio_graph + ["[audio]" + ",".join(chain) + "[voice]"]
        (directory / "voice.txt").write_text(";\n".join(graph), encoding="utf-8")
        _render_graph(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-protocol_whitelist",
                "file",
                "-i",
                str(source),
                "-/filter_complex",
                "voice.txt",
                "-map",
                "[voice]",
                "-c:a",
                "pcm_f32le",
                str(voice),
            ],
            cwd=directory,
            timeout=remaining(),
        )
    else:
        _run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r=48000:cl=mono:d={duration}",
                "-c:a",
                "pcm_f32le",
                str(voice),
            ],
            timeout=remaining(),
        )
    levels = _levels(voice, directory, "speech.txt", remaining())
    intervals = speech_intervals(levels)
    inputs = ["-protocol_whitelist", "file", "-i", str(voice)]
    graph, tracks = [], ["[0:a:0]"]
    report = dict(
        voice_cleanup=spec["voice_cleanup"], music={"present": False}, cut_sfx=None
    )
    music = spec.get("music")
    if music:
        offset = music["start_offset"]
        segment = music["duration"] - offset
        looped = music["loop"] and segment < duration
        # Every copy starts at the offset, so a loop repeats the chosen segment.
        repeats = math.ceil(duration / segment) + 1 if looped else 1
        copies = repeats if repeats <= _CONCAT_LIMIT else 1
        for _ in range(copies):
            inputs += [
                "-ss",
                f"{offset:.6f}",
                "-protocol_whitelist",
                "file",
                "-i",
                music["path"],
            ]
        head = "".join(f"[{1 + i}:a:0]" for i in range(copies))
        bed_filters = [f"concat=n={copies}:v=0:a=1"] if copies > 1 else []
        bed_filters += ["asetpts=PTS-STARTPTS", "aresample=48000"]
        if looped and copies == 1:
            # A very short segment loops in memory; it is under 1/16 of the program.
            bed_filters += [
                f"aloop=loop=-1:size={math.ceil(segment * RATE)}",
                "asetpts=N/SR/TB",
            ]
        bed_filters += [
            f"volume={music['volume_db']}dB",
            "apad",
            f"atrim=duration={duration:.6f}",
        ]
        # Without a loop, short music ends (and fades out) where the music ends.
        end = duration if music["loop"] or segment >= duration else segment
        fade_in = min(music["fade_in"], end)
        fade_out = min(music["fade_out"], end)
        if end < duration:
            # Silence follows the music, so always close it with a short fade.
            fade_out = max(fade_out, min(ANTI_CLICK, end))
        if fade_in:
            bed_filters.append(f"afade=t=in:st=0:d={fade_in:.6f}")
        if fade_out:
            bed_filters.append(f"afade=t=out:st={end - fade_out:.6f}:d={fade_out:.6f}")
        graph.append(head + ",".join(bed_filters) + "[bed]")
        if music["duck"]:
            envelope = directory / "envelope.wav"
            # A small guard absorbs sample quantization and codec leakage at the floor.
            write_envelope(
                envelope,
                intervals,
                music["duck_db"] + 0.75,
                round(duration * RATE),
                deadline=deadline,
            )
            inputs += ["-protocol_whitelist", "file", "-i", str(envelope)]
            graph.append(f"[bed][{1 + copies}:a:0]amultiply[music]")
        else:
            graph.append("[bed]anull[music]")
        # Keep the actual stem for an auditable depth measurement, not a configured claim.
        stem_script = directory / "music.txt"
        stem_script.write_text(";\n".join(graph), encoding="utf-8")
        stem = directory / "music.wav"
        _render_graph(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                *inputs,
                "-/filter_complex",
                "music.txt",
                "-map",
                "[music]",
                "-c:a",
                "pcm_f32le",
                str(stem),
            ],
            cwd=directory,
            timeout=remaining(),
        )
        measured = _levels(stem, directory, "music-levels.txt", remaining())
        report["music"] = dict(
            present=True,
            source_note=music["source_note"],
            sha256=music["sha256"],
            ducking=_duck_measurement(measured, intervals, duration, music["duck_db"])
            if music["duck"]
            else None,
        )
        # The mix now reads the rendered stem, keeping both loudnorm passes identical.
        inputs = [
            "-protocol_whitelist",
            "file",
            "-i",
            str(voice),
            "-protocol_whitelist",
            "file",
            "-i",
            str(stem),
        ]
        graph = []
        tracks.append("[1:a:0]")
    sfx = spec.get("cut_sfx")
    if sfx:
        cuts, elapsed = [], 0.0
        for start, end in ranges[:-1]:
            elapsed += end - start
            cuts.append(round(elapsed, 6))
        report["cut_sfx"] = dict(cuts=cuts, sha256=sfx["sha256"])
        if cuts:
            index = 2 if music else 1
            inputs += ["-protocol_whitelist", "file", "-i", sfx["path"]]
            # adelay counts samples at its input rate, so the effect is resampled first.
            graph.append(
                f"[{index}:a:0]aresample=48000,asplit={len(cuts)}"
                + "".join(f"[sfx{i}]" for i in range(len(cuts)))
            )
            for i, cut in enumerate(cuts):
                graph.append(
                    f"[sfx{i}]volume={sfx['volume_db']}dB,adelay={round(cut * 48000)}S:all=1[hit{i}]"
                )
                tracks.append(f"[hit{i}]")
    graph.append(
        "".join(tracks)
        + f"amix=inputs={len(tracks)}:normalize=0:duration=first,aresample=48000,atrim=duration={duration:.6f}[mix]"
    )
    (directory / "mix.txt").write_text(";\n".join(graph), encoding="utf-8")
    mix = directory / "mix.wav"
    _render_graph(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-n",
            *inputs,
            "-/filter_complex",
            "mix.txt",
            "-map",
            "[mix]",
            "-c:a",
            "pcm_f32le",
            str(mix),
        ],
        cwd=directory,
        timeout=remaining(),
    )
    # Recheck assets after reading; Studio also verifies before publication.
    validate_settings(spec)
    return mix, report
