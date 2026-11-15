"""Local F3 evidence: punch-ins, shortened pauses and crossfades on real footage.

Runs the real Studio jobs (transcribe, vision, preview, QA) on a local clip for
Instagram Reels with face-tracked framing, then measures the render against a
plain render of the same edit: audio offset per range, picture offset per
range, stream lengths, pauses between kept words, and the face size and
position redetected on the output. Frames around each cut are written as PNG.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from cutroom.postproduction import _run, export_video  # noqa: E402
from cutroom.reframe import face_samples  # noqa: E402
from cutroom.speech import remap_words  # noqa: E402
from cutroom.studio import Studio  # noqa: E402
from cutroom.vision import analyze_faces  # noqa: E402

PACING = {"punch_in": "alternate", "max_pause": 0.5, "transition": "crossfade"}


def pauses(words, segments):
    spans, last = [], None
    for item in remap_words(words, segments):
        if spans and item["source_id"] == last:
            spans[-1][1] = item["end"]
        else:
            spans.append([item["start"], item["end"]])
            last = item["source_id"]
    return [b[0] - a[1] for a, b in zip(spans, spans[1:])]


def _binary(arguments):
    return subprocess.run(
        arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=600,
        shell=False,
    ).stdout


def pcm(path):
    data = _binary(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "f32le",
            "-",
        ]
    )
    return np.frombuffer(data, dtype=np.float32)


def luma_frames(path, width=90, height=160):
    raw = _binary(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"scale={width}:{height},format=gray",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width)
    return frames.astype(np.float32)


def best_lag(a, b, limit):
    """Lag (in samples of b relative to a) with the highest normalised correlation."""
    best, value = 0, -2.0
    for lag in range(-limit, limit + 1):
        if lag >= 0:
            x, y = a[: len(a) - lag], b[lag : lag + len(a) - lag]
        else:
            x, y = a[-lag:], b[: len(a) + lag]
        n = min(len(x), len(y))
        if n < 16:
            continue
        x = (x[:n] - x[:n].mean()) / (x[:n].std() + 1e-9)
        y = (y[:n] - y[:n].mean()) / (y[:n].std() + 1e-9)
        score = float(np.dot(x, y) / n)
        if score > value:
            best, value = lag, score
    return best, value


def frame(video, index, target):
    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-i",
            str(video),
            "-vf",
            f"select=eq(n\\,{index})",
            "-frames:v",
            "1",
            "-fps_mode",
            "passthrough",
            str(target),
        ],
        timeout=300,
    )
    return str(target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument(
        "models", help="Directory with whisper-tiny and face_landmarker.task"
    )
    parser.add_argument(
        "output", help="New local evidence directory (never overwritten)"
    )
    args = parser.parse_args()
    models = Path(args.models)
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    studio = Studio(directory / "workspace")
    project = studio.create(args.source, "Pacing evidence")
    project = studio.update(
        project["id"],
        {
            "settings": {
                "platform": "instagram_reels",
                "framing": "face_track",
                "face_model": str(models / "face_landmarker.task"),
                "whisper_model": str(models / "whisper-tiny"),
                "frame_step": 5,
                "captions": True,
                "caption_style": "highlight",
            },
            "segments": [{"start": 0.0, "end": 12.0}, {"start": 14.0, "end": 30.0}],
        },
        project["revision"],
    )
    timings = {}

    def job(action):
        started = time.monotonic()
        record = studio.submit(project["id"], action)
        while record["status"] not in {"completed", "failed", "cancelled"}:
            time.sleep(0.2)
            record = studio.job(record["id"])
        if record["status"] != "completed":
            raise RuntimeError(f"{action}: {record['error']}")
        timings[action] = round(time.monotonic() - started, 2)
        return record

    job("transcribe")
    job("vision")
    before = studio.get(project["id"])
    words = [
        w
        for w in before["transcript"]["words"]
        if w["id"] not in set(before["excluded_word_ids"])
    ]
    pauses_before = pauses(words, before["segments"])
    project = studio.update(
        project["id"], {"settings": {"pacing": PACING}}, before["revision"]
    )
    pauses_after = pauses(words, project["segments"])
    preview = job("preview")
    qa = job("qa")
    rendered = preview["result"]
    video = Path(rendered["output"])
    report = rendered["pacing"]

    # A plain render of the same (shortened) edit and framing, without pacing.
    plain_settings = studio._render_settings(project, "preview")
    plain_settings.pop("pacing")
    plain_settings.pop("pacing_analysis", None)
    plain = export_video(
        project["source"],
        project["segments"],
        directory / "plain.mp4",
        settings=plain_settings,
    )
    plain_video = Path(plain["output"])

    fps = report["fps"]
    ranges = report["ranges"]
    rate = 48000
    paced_audio, plain_audio = pcm(video), pcm(plain_video)
    paced_luma, plain_luma = luma_frames(video), luma_frames(plain_video)
    audio_offsets, video_offsets = [], []
    for item in ranges:
        start = item["start_frame"] / fps
        length = item["frames"] / fps
        if length < 0.5:
            continue
        a0 = int((start + length * 0.2) * rate)
        a1 = int((start + length * 0.8) * rate)
        lag, score = best_lag(plain_audio[a0:a1], paced_audio[a0 - 480 : a1 + 480], 480)
        audio_offsets.append(
            {
                "range_start_s": round(start, 4),
                "lag_samples": lag - 480,
                "correlation": round(score, 4),
            }
        )
        f0 = item["start_frame"] + 8
        f1 = item["start_frame"] + item["frames"] - 8
        if f1 - f0 > 20:
            motion_plain = np.abs(np.diff(plain_luma[f0 - 5 : f1 + 5], axis=0)).mean(
                axis=(1, 2)
            )
            motion_paced = np.abs(np.diff(paced_luma[f0 - 5 : f1 + 5], axis=0)).mean(
                axis=(1, 2)
            )
            lag, score = best_lag(motion_plain[5:-5], motion_paced, 5)
            video_offsets.append(
                {
                    "range_start_frame": item["start_frame"],
                    "lag_frames": lag - 5,
                    "correlation": round(score, 4),
                }
            )

    # Redetect faces on both renders; compare size and position on the same frames.
    zone = report["zone"]
    detected = {}
    for name, path in (("paced", video), ("plain", plain_video)):
        compact = face_samples(
            analyze_faces(
                str(path), str(models / "face_landmarker.task"), frame_step=3
            )["frames"]
        )
        detected[name] = {
            int(round(t * fps)): max(faces, key=lambda f: f[2] * f[3])
            for t, faces in compact
            if faces
        }
    zoomed = {
        i
        for item in ranges
        if max(item["zoom"]) > 1
        for i in range(
            item["start_frame"] + 8, item["start_frame"] + item["frames"] - 8
        )
    }
    normal = {
        i
        for item in ranges
        if max(item["zoom"]) <= 1
        for i in range(
            item["start_frame"] + 8, item["start_frame"] + item["frames"] - 8
        )
    }

    def compare(indices):
        ratios, inside, total, shift = [], 0, 0, []
        for i in sorted(indices):
            a, b = detected["paced"].get(i), detected["plain"].get(i)
            if a is None:
                continue
            total += 1
            inside += (
                zone["left"] <= a[0] <= 1 - zone["right"]
                and zone["top"] <= a[1] <= 1 - zone["bottom"]
            )
            if b is not None:
                ratios.append(a[3] / b[3])
                shift.append([a[0] - b[0], a[1] - b[1]])
        return {
            "frames_with_face": total,
            "inside_safe_area": inside,
            "inside_fraction": inside / total if total else None,
            "face_height_ratio_median": float(np.median(ratios)) if ratios else None,
            "face_centre_shift_median": [
                float(np.median([s[0] for s in shift])),
                float(np.median([s[1] for s in shift])),
            ]
            if shift
            else None,
            "compared_frames": len(ratios),
        }

    frames = []
    for number, cut in enumerate(report["cuts"][:4], 1):
        for label, index in (("before", cut - 6), ("blend", cut), ("after", cut + 6)):
            frames.append(frame(video, index, directory / f"cut{number}-{label}.png"))
    for item in ranges[:4]:
        index = item["start_frame"] + item["frames"] // 2
        kind = "zoom" if max(item["zoom"]) > 1 else "normal"
        frames.append(
            frame(video, index, directory / f"range{ranges.index(item) + 1}-{kind}.png")
        )
        frames.append(
            frame(
                plain_video,
                index,
                directory / f"range{ranges.index(item) + 1}-plain.png",
            )
        )

    def streams(path):
        data = json.loads(
            _run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,duration,start_time,nb_frames",
                    "-of",
                    "json",
                    str(path),
                ]
            ).stdout
        )["streams"]
        return {
            s["codec_type"]: {
                k: s.get(k) for k in ("duration", "start_time", "nb_frames")
            }
            for s in data
        }

    summary = {
        "source": args.source,
        "edit": before["segments"],
        "settings": {
            "platform": "instagram_reels",
            "framing": "face_track",
            "pacing": PACING,
        },
        "timings_s": timings,
        "pauses": {
            "kept_words": len(words),
            "longest_before_s": max(pauses_before, default=0),
            "over_limit_before": sum(p > 0.5 + 1e-6 for p in pauses_before),
            "longest_after_s": max(pauses_after, default=0),
            "over_limit_after": sum(p > 0.5 + 1e-6 for p in pauses_after),
            "segments_before": len(before["segments"]),
            "segments_after": len(project["segments"]),
            "program_before_s": sum(s["end"] - s["start"] for s in before["segments"]),
            "program_after_s": sum(s["end"] - s["start"] for s in project["segments"]),
        },
        "plan": {
            "ranges": len(ranges),
            "cuts": len(report["cuts"]),
            "transitions": len(report["transitions"]),
            "transition_frames": report["transition_frames"],
            "zooms": sorted({round(max(r["zoom"]), 4) for r in ranges}),
            "max_upscale_factor": report["max_upscale_factor"],
            "framing_upscale": report["base_upscale"],
            "warnings": report["warnings"],
        },
        "checks": [
            c
            for c in qa["result"]["checks"]
            if c["name"].startswith(("pacing", "framing", "caption", "safe"))
            or c["name"] in {"duration", "platform_upscale", "frame_timing"}
        ],
        "audio_offset_vs_plain": audio_offsets,
        "video_offset_vs_plain": video_offsets,
        "redetected": {
            "method": "MediaPipe FaceLandmarker on every third output frame of both "
            "renders, largest face; ranges trimmed by 8 frames at each cut",
            "zoomed_ranges": compare(zoomed),
            "normal_ranges": compare(normal),
        },
        "streams": {"paced": streams(video), "plain": streams(plain_video)},
        "frames": frames,
    }
    (directory / "measurements.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "checks"}, indent=2))
    for check in summary["checks"]:
        print(check["name"], check["status"])


if __name__ == "__main__":
    main()
