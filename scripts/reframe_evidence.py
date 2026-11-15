"""Local F2 evidence: real Studio vision, preview, QA and output face sampling."""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cutroom.postproduction import _run, export_video
from cutroom.reframe import face_samples
from cutroom.studio import Studio
from cutroom.vision import analyze_faces


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("face_model")
    parser.add_argument(
        "output", help="New local evidence directory (never overwritten)"
    )
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    studio = Studio(directory / "workspace")
    project = studio.create(args.source, "Reframing evidence")
    project = studio.update(
        project["id"],
        {
            "settings": {
                "platform": "instagram_reels",
                "framing": "face_track",
                "face_model": args.face_model,
                "frame_step": 5,
            },
            "segments": [{"start": 2.0, "end": 17.0}],
        },
        project["revision"],
    )

    def job(action):
        started = time.monotonic()
        record = studio.submit(project["id"], action)
        while record["status"] not in {"completed", "failed", "cancelled"}:
            time.sleep(0.1)
            record = studio.job(record["id"])
        if record["status"] != "completed":
            raise RuntimeError(record["error"])
        return record, time.monotonic() - started

    vision, vision_seconds = job("vision")
    preview, preview_seconds = job("preview")
    qa, qa_seconds = job("qa")
    rendered = preview["result"]
    video = rendered["output"]
    paths = []
    for timestamp in (0, 3, 6, 9, 12, 14):
        target = directory / f"face-track-{timestamp:02d}.png"
        _run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-n",
                "-ss",
                str(timestamp),
                "-i",
                video,
                "-frames:v",
                "1",
                str(target),
            ]
        )
        paths.append(str(target))
    blur = export_video(
        args.source,
        [{"start": 3, "end": 3.5}],
        directory / "blur-fill.mp4",
        settings={
            "platform": "instagram_reels",
            "preset": "preview",
            "framing": "blur_fill",
        },
    )
    target = directory / "blur-fill.png"
    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-i",
            blur["output"],
            "-frames:v",
            "1",
            str(target),
        ]
    )
    output_faces = analyze_faces(video, args.face_model, frame_step=5)
    compact = face_samples(output_faces["frames"])
    zone = rendered["framing"]["zone"]
    inside = detected = 0
    for _, faces in compact:
        if not faces:
            continue
        face = max(faces, key=lambda f: f[2] * f[3])
        detected += 1
        inside += (
            zone["left"] <= face[0] <= 1 - zone["right"]
            and zone["top"] <= face[1] <= 1 - zone["bottom"]
        )
    streams = json.loads(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,duration,start_time,nb_frames",
                "-of",
                "json",
                video,
            ]
        ).stdout
    )["streams"]
    measures = {
        s["codec_type"]: {k: s.get(k) for k in ("duration", "start_time", "nb_frames")}
        for s in streams
    }
    v, a = measures["video"], measures["audio"]
    summary = {
        "source": args.source,
        "source_range": [2.0, 17.0],
        "project_id": project["id"],
        "preview": video,
        "vision_seconds": vision_seconds,
        "preview_seconds": preview_seconds,
        "qa_seconds": qa_seconds,
        "inference": {
            "frame_step": 5,
            "samples": len(vision["result"]["face_samples"]),
            "width": 640,
        },
        "frame": [rendered["width"], rendered["height"]],
        "upscale_factor": rendered["upscale_factor"],
        "crop": rendered["framing"]["crop"],
        "checks": [
            c
            for c in qa["result"]["checks"]
            if c["name"].startswith("framing")
            or c["name"] in {"duration", "platform_upscale"}
        ],
        "redetected_output": {
            "samples": len(compact),
            "detected": detected,
            "inside": inside,
            "inside_fraction": inside / detected if detected else None,
            "method": "MediaPipe FaceLandmarker on rendered output, every fifth frame; largest face centre",
        },
        "streams": measures,
        "duration_difference_s": abs(float(v["duration"]) - float(a["duration"])),
        "start_difference_s": abs(float(v["start_time"]) - float(a["start_time"])),
        "sync_limit": "Stream timing only, not a perceptual lip-sync certification",
        "frames": paths + [str(target)],
    }
    (directory / "measurements.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
