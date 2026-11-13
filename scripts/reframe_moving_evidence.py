"""Local F2 evidence with a moving face: real footage slid across a wide canvas.

The speaker clip is scaled to `--width` pixels and slides between the left and
right edges of a 1920x1080 black canvas (triangle wave, `--half-period`
seconds per sweep). The Studio pipeline then runs Vision, a face_track preview
for Instagram Reels and QA, and MediaPipe redetects the face on every output
frame to compare the planned safe-zone fraction with the delivered picture.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cutroom.childenv import child_env
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
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--half-period", type=float, default=3.0)
    parser.add_argument("--frame-step", type=int, default=5)
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    width, height = args.width, args.width * 9 // 16
    clip = directory / "moving.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-ss",
            "2",
            "-t",
            "12",
            "-i",
            args.source,
            "-filter_complex",
            "color=black:size=1920x1080:rate=30000/1001:duration=12[bg];"
            f"[0:v]scale={width}:{height}[fg];[bg][fg]overlay="
            f"x='{1920 - width}*abs(mod(t/{args.half_period},2)-1)':"
            f"y={(1080 - height) // 2}:shortest=1,format=yuv420p[v]",
            "-map",
            "[v]",
            "-map",
            "0:a",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "16",
            "-c:a",
            "aac",
            str(clip),
        ],
        check=True,
        env=child_env(python=False),
        timeout=300,
    )
    studio = Studio(directory / "workspace")
    project = studio.create(str(clip), "Moving face evidence")
    project = studio.update(
        project["id"],
        {
            "settings": {
                "platform": "instagram_reels",
                "framing": "face_track",
                "face_model": args.face_model,
                "frame_step": args.frame_step,
            },
            "segments": [{"start": 0.0, "end": 11.5}],
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
            raise RuntimeError(record.get("error"))
        timings[action] = round(time.monotonic() - started, 1)
        return record

    job("vision")
    preview = job("preview")
    quality = job("qa")
    framing = preview["result"]["framing"]
    zone = framing["zone"]
    found = analyze_faces(preview["result"]["output"], args.face_model, frame_step=1)
    detected = inside = 0
    outside = []
    for timestamp, faces in face_samples(found["frames"]):
        if not faces:
            continue
        best = max(faces, key=lambda entry: entry[2] * entry[3])
        detected += 1
        ok = (
            zone["left"] <= best[0] <= 1 - zone["right"]
            and zone["top"] <= best[1] <= 1 - zone["bottom"]
        )
        inside += ok
        if not ok:
            outside.append([round(timestamp, 3), round(best[0], 3)])
    analysis = studio.get(project["id"])["analysis"]
    summary = {
        "source": args.source,
        "clip": str(clip),
        "foreground_width_px": width,
        "half_period_s": args.half_period,
        "face_speed_source_px_per_s": (1920 - width) / args.half_period,
        "vision_frame_step": args.frame_step,
        "vision_samples": len(analysis["face_samples"]),
        "vision_samples_with_face": sum(1 for s in analysis["face_samples"] if s[1]),
        "timings_s": timings,
        "framing": {
            "frames": framing["frames"],
            "crop": framing["crop"],
            "face_coverage": framing.get("face_coverage"),
            "expression_pieces": framing.get("expression_pieces"),
            "warnings": framing["warnings"],
        },
        "qa_passed": quality["result"].get("passed"),
        "qa": {
            check["name"]: {"status": check["status"], "detail": check["detail"]}
            for check in quality["result"]["checks"]
            if check["name"].startswith("framing") or check["name"] == "duration"
        },
        "output_redetection_every_frame": {
            "frames": framing["frames"],
            "detected": detected,
            "inside": inside,
            "inside_fraction": inside / detected if detected else None,
            "outside_examples": outside[:10],
        },
        "zone": zone,
    }
    text = json.dumps(summary, indent=1)
    (directory / "summary.json").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
