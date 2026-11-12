"""Local audio assets and deterministic speech-aware mixing."""

import math
import re
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
    result, time = [], None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.search(r"pts_time:([-+\deE.]+)", line)
        if match:
            time = float(match[1])
        elif time is not None and "RMS_level=" in line:
            value = float(line.split("=", 1)[1])
            result.append((time, max(-120.0, value)))
    return result


def speech_intervals(levels, window=0.05):
    finite = [level for _, level in levels if math.isfinite(level)]
    threshold = max(-50, max(finite, default=-120) - 30)
    result = []
    for time, level in levels:
        if level <= threshold:
            continue
        end = round(time + window, 6)
        if result and time - result[-1][1] <= 0.25:
            result[-1] = (result[-1][0], end)
        else:
            result.append((time, end))
    return result


def envelope_gain(intervals, depth):
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
    for time, level in levels:
        if any(start + 0.2 <= time <= end - 0.25 for start, end in intervals):
            speech.append(level)
        elif 0.6 <= time <= duration - 0.6 and not any(
            start - 0.3 <= time <= end + 0.4 for start, end in intervals
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
    """Render an exact-length PCM mix before the final two-pass loudnorm scan."""
    import array
    import wave

    from .postproduction import _render_graph, _run

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
            timeout=timeout,
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
            timeout=timeout,
        )
    levels = _levels(voice, directory, "speech.txt", timeout)
    intervals = speech_intervals(levels)
    inputs = ["-protocol_whitelist", "file", "-i", str(voice)]
    graph, tracks = [], ["[0:a:0]"]
    report = dict(
        voice_cleanup=spec["voice_cleanup"], music={"present": False}, cut_sfx=None
    )
    music = spec.get("music")
    if music:
        inputs += ["-stream_loop", "-1"] if music["loop"] else []
        inputs += [
            "-ss",
            str(music["start_offset"]),
            "-protocol_whitelist",
            "file",
            "-i",
            music["path"],
        ]
        bed_filters = [
            "asetpts=PTS-STARTPTS",
            "aresample=48000",
            f"volume={music['volume_db']}dB",
            "apad",
            f"atrim=duration={duration:.6f}",
        ]
        for key in ("fade_in", "fade_out"):
            fade = min(music[key], duration)
            if fade:
                bed_filters.append(
                    f"afade=t={'in' if key == 'fade_in' else 'out'}:st={0 if key == 'fade_in' else duration - fade}:d={fade}"
                )
        graph.append("[1:a:0]" + ",".join(bed_filters) + "[bed]")
        if music["duck"]:
            # A small guard absorbs sample quantization and codec leakage at the floor.
            gain = envelope_gain(intervals, music["duck_db"] + 0.75)
            envelope = directory / "envelope.wav"
            with wave.open(str(envelope), "wb") as stream:
                stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                count = round(duration * 48000)
                for start in range(0, count, 48000):
                    block = array.array(
                        "h",
                        (
                            round(32767 * gain(index / 48000))
                            for index in range(start, min(start + 48000, count))
                        ),
                    )
                    stream.writeframes(block.tobytes())
            inputs += ["-protocol_whitelist", "file", "-i", str(envelope)]
            graph.append("[bed][2:a:0]amultiply[music]")
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
            timeout=timeout,
        )
        measured = _levels(stem, directory, "music-levels.txt", timeout)
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
        timeout=timeout,
    )
    # Recheck assets after reading; Studio also verifies before publication.
    validate_settings(spec)
    return mix, report
