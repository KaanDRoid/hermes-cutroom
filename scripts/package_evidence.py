"""Real local F7 renders, packages, checksum verification and one-byte tamper check.

This evidence program records approval by calling Studio.approve with the digest
returned by Studio.review, the same internal path the local Studio page uses.
That is a test fixture approval, not a claim that a person watched these exports.
Nothing is uploaded or posted. Existing evidence directories are never reused.
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cutroom.packages import jpeg_size  # noqa: E402
from cutroom.project import file_digest  # noqa: E402
from cutroom.studio import Studio  # noqa: E402


def run(studio, project_id, action, options=None):
    record = studio.submit(project_id, action, options or {})
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        record = studio.job(record["id"])
        if record["status"] in {"completed", "failed", "cancelled"}:
            if record["status"] != "completed":
                raise RuntimeError(f"{action}: {record.get('error')}")
            print(f"{project_id}: {action} completed", flush=True)
            return record
        time.sleep(0.2)
    studio.cancel(record["id"])
    raise TimeoutError(f"{action} exceeded 900 seconds")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", default="C:/Users/Kaan/Videos/cutroom-test/sandra-wikitongues.webm"
    )
    parser.add_argument(
        "--models", default="C:/Users/Kaan/Projects/hermes-cutroom/models"
    )
    parser.add_argument("--output", default="artifacts/f7/evidence")
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    studio = Studio(directory / "workspace")
    base = studio.create(args.source, "Sandra — Wikitongues")
    base = studio.update(
        base["id"],
        {
            "settings": {
                "whisper_model": str(Path(args.models).resolve() / "whisper-tiny")
            }
        },
        base["revision"],
    )
    run(studio, base["id"], "transcribe", {"language": "en"})
    report = {
        "approval": "Evidence fixture calls Studio.review then Studio.approve, the internal Studio page path; no person-watch acceptance is claimed.",
        "posted": False,
        "packages": [],
    }
    for platform in ("instagram_reels", "youtube"):
        project = studio.derive(base["id"], platform, name="Sandra — Wikitongues")
        settings = {"captions": False, "framing": "blur_fill"}
        if platform == "youtube":
            settings.update(
                chapters=[
                    {"start": 0, "title": "Sandra"},
                    {"start": 10, "title": "Speaking English"},
                    {"start": 20, "title": "Wikitongues"},
                ],
                thumbnail={"time": 3, "text": "Sandra"},
            )
        project = studio.update(
            project["id"],
            {"segments": [{"start": 0, "end": 32}], "settings": settings},
            project["revision"],
        )
        preview = run(studio, project["id"], "preview")
        studio.approve(project["id"], studio.review(project["id"])["digest"])
        final = run(studio, project["id"], "final")
        source_final = studio.artifact(project["id"], "final")
        original_hash = file_digest(source_final)
        package = studio.package(
            project["id"],
            post={
                "title": "Sandra speaking English",
                "caption": "Sandra speaking English — Wikitongues.",
                "hashtags": ["Wikitongues"],
            },
            cover_time=3,
        )
        folder = Path(package["directory"])
        verification = studio.verify_package(folder)
        if not verification["ok"]:
            raise AssertionError(verification)
        cover = folder / ("thumbnail.jpg" if platform == "youtube" else "cover.jpg")
        shutil.copyfile(cover, directory / f"{platform}-cover.jpg")
        copied = folder.with_name(folder.name + "-tampered")
        shutil.copytree(folder, copied)
        video = copied / "video.mp4"
        with video.open("r+b") as stream:
            stream.seek(video.stat().st_size // 2)
            offset = stream.tell()
            byte = stream.read(1)
            stream.seek(offset)
            stream.write(bytes([byte[0] ^ 1]))
        tampered = studio.verify_package(copied)
        if tampered["ok"] or not any(
            p["file"] == "video.mp4" for p in tampered["problems"]
        ):
            raise AssertionError("A one-byte video change was not detected")
        if file_digest(source_final) != original_hash:
            raise AssertionError("The source final was changed")
        report["packages"].append(
            {
                "platform": platform,
                "preview_job": preview["id"],
                "final_job": final["id"],
                "package": package,
                "verified": verification,
                "cover_size": jpeg_size(cover),
                "tampered_copy": tampered,
                "original_final_unchanged": True,
            }
        )
    (directory / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (directory / "NOTES.txt").write_text(
        report["approval"]
        + "\nNothing has been posted. Upload these files yourself.\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
