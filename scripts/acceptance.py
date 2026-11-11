"""Run the complete Studio workflow on local reference media.

This is an acceptance harness, not a unit test. It needs FFmpeg, the local
model runtime and models (see `cutroom doctor` / `cutroom setup-models`) and a
speech recording. By default it uses the attributed whisper.cpp JFK sample at
artifacts/reference/jfk.wav, placed over a synthetic test pattern so that the
result is clearly not anyone's own recording.

Every step goes through the public Studio facade and its detached jobs. This
harness stops at preview for separate human review in Desktop or the local
REST API. It never grants approval.
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


def prepare(args, output):
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
    return studio, project


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--audio", default=ROOT / "artifacts/reference/jfk.wav", type=Path
    )
    parser.add_argument("--models", default=ROOT / "models", type=Path)
    parser.add_argument("--output", default=None, type=Path)
    parser.add_argument("--aspect", default="portrait")
    parser.add_argument("--language", default="en")
    parser.add_argument("--workspace", type=Path, help="Existing workspace to resume")
    parser.add_argument(
        "--project-id", help="Existing project to resume without editing"
    )
    args = parser.parse_args(argv)
    if (args.workspace is None) != (args.project_id is None):
        parser.error("--workspace and --project-id must be supplied together")
    output = args.output or ROOT / "artifacts" / (
        "acceptance-" + time.strftime("%Y%m%d-%H%M%S")
    )
    output.mkdir(parents=True, exist_ok=False)
    if args.workspace:
        studio = Studio(args.workspace)
        review = studio.review(args.project_id)
        project = review["project"]
        approval = project.get("approval") or {}
        if (
            approval.get("digest") != review["digest"]
            or approval.get("revision") != project["revision"]
        ):
            raise PermissionError(
                "Current human approval is absent or stale. Review and approve "
                "this exact digest in Cutroom Studio Desktop or the local REST "
                "human review surface before resuming."
            )
    else:
        studio, project = prepare(args, output)
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

    if not args.workspace:
        run("transcribe", {"language": args.language})
        run("silence", {"min_duration": 0.4})
        run("storyboard")
        project = studio.get(project["id"])
        project = studio.update(
            project["id"], {"selected_hook": 0}, project["revision"]
        )
        run("storyboard")
        run("vision", {"frame_step": 5})
        run("preview")
        review = studio.review(project["id"])
        summary = {
            "status": "awaiting_human_review",
            "workspace": str(studio.root),
            "project_id": project["id"],
            "digest": review["digest"],
            "instructions": (
                "Review the preview, source, cuts, text, brand and assets in Cutroom "
                "Studio Desktop or the local REST human review surface, then approve "
                "this exact digest there. This harness never grants approval. "
                "Resume with --workspace and --project-id from this summary."
            ),
            "steps": log,
        }
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, indent=2))
        return 0

    run("final", timeout=3600)
    run("cover", {"time": 1.0})
    qa = run("qa")
    project = studio.get(project["id"])
    summary = {
        "project_id": project["id"],
        "source": project["source"],
        "transcript_words": len(project["transcript"]["words"]),
        "transcript_text": project["transcript"]["text"],
        "filler_candidates": len(project["transcript"]["fillers"]),
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
