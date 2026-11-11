"""Run the complete Studio workflow on local reference media.

This is an acceptance harness, not a unit test. It needs FFmpeg, the local
model runtime and models (see `cutroom doctor` / `cutroom setup-models`) and a
speech recording. By default it uses the attributed whisper.cpp JFK sample at
artifacts/reference/jfk.wav, placed over a synthetic test pattern so that the
result is clearly not anyone's own recording.

Every step goes through the public Studio facade and its detached jobs. The
approval step is performed here only because this harness stands in for the
human reviewer; agent tools never expose approval.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cutroom.media import probe  # noqa: E402
from cutroom.studio import Studio  # noqa: E402


def wait(studio, job, timeout):
    deadline = time.monotonic() + timeout
    while True:
        current = studio.job(job["id"])
        if current["status"] in {"completed", "failed", "cancelled"}:
            return current
        if time.monotonic() > deadline:
            raise TimeoutError(f"{job['action']} did not finish in {timeout} s")
        time.sleep(0.25)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--audio", default=ROOT / "artifacts/reference/jfk.wav", type=Path
    )
    parser.add_argument("--models", default=ROOT / "models", type=Path)
    parser.add_argument("--output", default=None, type=Path)
    parser.add_argument("--aspect", default="portrait")
    parser.add_argument("--language", default="en")
    args = parser.parse_args(argv)

    output = args.output or ROOT / "artifacts" / (
        "acceptance-" + time.strftime("%Y%m%d-%H%M%S")
    )
    output.mkdir(parents=True, exist_ok=False)
    source = output / "reference-over-test-pattern.mp4"
    import wave

    with wave.open(str(args.audio), "rb") as stream:
        duration = stream.getnframes() / stream.getframerate()
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-n",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=1280x720:rate=25:duration={duration}",
            "-i",
            str(args.audio),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        timeout=300,
    )
    studio = Studio(output / "workspace")
    project = studio.create(source, name="Reference acceptance")
    project = studio.update(
        project["id"],
        {
            "settings": {
                "whisper_model": str(args.models / "whisper-tiny"),
                "face_model": str(args.models / "face_landmarker.task"),
                "segmentation_model": str(args.models / "selfie_segmenter.tflite"),
                "aspect": args.aspect,
                "captions": True,
                "brand": {"title_color": "#FFFFFF", "subtitle_color": "#FFE066"},
            },
            "brief": "Reference acceptance run",
        },
        project["revision"],
    )
    log = []

    def run(action, options=None, timeout=1800):
        started = time.monotonic()
        job = wait(studio, studio.submit(project["id"], action, options or {}), timeout)
        log.append(
            {
                "action": action,
                "status": job["status"],
                "seconds": round(time.monotonic() - started, 2),
                "error": job["error"],
            }
        )
        print(json.dumps(log[-1]), flush=True)
        if job["status"] != "completed":
            raise RuntimeError(f"{action} failed: {job['error']}")
        return job

    run("transcribe", {"language": args.language})
    project = studio.get(project["id"])
    words = project["transcript"]["words"]
    fillers = project["transcript"]["fillers"]
    run("silence", {"min_duration": 0.4})
    run("storyboard")
    project = studio.get(project["id"])
    project = studio.update(project["id"], {"selected_hook": 0}, project["revision"])
    run("storyboard")
    run("vision", {"frame_step": 5})
    run("preview")
    project = studio.get(project["id"])
    # Stand-in for the human reviewer in Cutroom Studio.
    review = studio.review(project["id"])
    studio.approve(project["id"], review["digest"])
    run("final", timeout=3600)
    run("cover", {"time": 1.0})
    qa = run("qa")
    project = studio.get(project["id"])
    summary = {
        "source": str(source),
        "transcript_words": len(words),
        "transcript_text": project["transcript"]["text"],
        "filler_candidates": len(fillers),
        "segments": project["segments"],
        "hooks": [hook["text"] for hook in project["story"]["hooks"]],
        "artifacts": {
            kind: studio.artifact(project["id"], kind).name
            for kind in project["artifacts"]
        },
        "final": {
            key: probe(studio.artifact(project["id"], "final"))[key]
            for key in ("duration", "width", "height", "has_audio")
        },
        "quality_passed": qa["result"]["passed"],
        "quality_checks": {c["name"]: c["status"] for c in qa["result"]["checks"]},
        "steps": log,
        "workspace": str(studio.root),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
