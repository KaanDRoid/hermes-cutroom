"""Local F6 evidence: long-form YouTube delivery on a real 17-minute talk.

Runs the real Studio jobs (transcribe, vision, preview, QA) on a local talk for
the YouTube profile, saves the suggested chapters with a thumbnail title and an
end screen, then checks the delivered files independently of Cutroom's QA:
ffprobe chapters against chapters.txt and the rules, every SRT cue against the
kept words, the thumbnail's size, aspect and bytes, and the frames at each
chapter start. Nothing is uploaded.
"""

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cutroom import longform  # noqa: E402
from cutroom.studio import Studio  # noqa: E402

THUMBNAIL_TEXT = "Climate change is simple"


def ffprobe(path, *flags):
    return json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", *flags, "-of", "json", str(path)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
            shell=False,
        ).stdout
    )


def frame(video, at, output):
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=480:-2",
            str(output),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=120,
        shell=False,
    )


def kept_text(project):
    """Every kept word of the transcript, straight from the project."""
    excluded = set(project["excluded_word_ids"])
    return [
        " ".join(w["text"].split())
        for w in sorted(project["transcript"]["words"], key=lambda w: w["start"])
        if w["id"] not in excluded
        and w["text"].strip()
        and any(s["start"] <= w["start"] < s["end"] for s in project["segments"])
    ]


def check_srt(path, words, frame_s, expected_words):
    """Independent SRT check: numbering, order, layout, timing against words."""
    text = Path(path).read_text(encoding="utf-8")
    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    stamp = re.compile(r"(\d+):(\d\d):(\d\d),(\d\d\d)")
    starts = sorted(w["start"] for w in words)
    ends = sorted(w["end"] for w in words)
    problems, previous_end, worst = [], 0.0, 0.0
    longest_line, most_lines, durations = 0, 0, []
    for number, block in enumerate(blocks, 1):
        lines = block.split("\n")
        if lines[0] != str(number):
            problems.append(f"cue {number}: numbered {lines[0]}")
        times = stamp.findall(lines[1])
        start, end = (
            int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
            for h, m, s, ms in times
        )
        body = lines[2:]
        longest_line = max(longest_line, *(len(line) for line in body))
        most_lines = max(most_lines, len(body))
        durations.append(end - start)
        if start < previous_end - 0.0005:
            problems.append(f"cue {number}: overlaps the previous cue")
        nearest = min(starts, key=lambda value: abs(value - start))
        worst = max(worst, abs(nearest - start))
        if abs(nearest - start) > frame_s:
            problems.append(
                f"cue {number}: starts {abs(nearest - start):.3f} s from a word"
            )
        if not any(value <= end + frame_s for value in ends if value >= start):
            problems.append(f"cue {number}: no word ends inside it")
        previous_end = end
    written = " ".join(
        html.unescape(line) for block in blocks for line in block.split("\n")[2:]
    ).split()
    if written != " ".join(expected_words).split():
        problems.append(
            f"{len(written)} words in the file, {len(' '.join(expected_words).split())} "
            "kept words in the transcript"
        )
    return {
        "words_in_file": len(written),
        "kept_words": len(" ".join(expected_words).split()),
        "cues": len(blocks),
        "longest_line_chars": longest_line,
        "most_lines": most_lines,
        "shortest_s": round(min(durations), 3),
        "longest_s": round(max(durations), 3),
        "largest_start_offset_s": round(worst, 4),
        "frame_s": round(frame_s, 4),
        "problems": problems[:20],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument(
        "models", help="Directory with whisper-tiny and face_landmarker.task"
    )
    parser.add_argument(
        "output", help="New local evidence directory (never overwritten)"
    )
    parser.add_argument(
        "--end", type=float, default=None, help="Use only the source up to this second"
    )
    args = parser.parse_args()
    models = Path(args.models)
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    studio = Studio(directory / "workspace")
    project = studio.create(args.source, "Long-form evidence")
    changes = {
        "settings": {
            "platform": "youtube",
            "face_model": str(models / "face_landmarker.task"),
            "whisper_model": str(models / "whisper-tiny"),
            "frame_step": 30,
        }
    }
    if args.end:
        changes["segments"] = [{"start": 0.0, "end": args.end}]
    project = studio.update(project["id"], changes, project["revision"])
    timings = {}

    def job(action, options=None):
        started = time.monotonic()
        record = studio.submit(project["id"], action, options or {})
        while record["status"] not in {"completed", "failed", "cancelled"}:
            time.sleep(0.5)
            record = studio.job(record["id"])
        if record["status"] != "completed":
            raise RuntimeError(f"{action}: {record['error']}")
        timings[action] = round(time.monotonic() - started, 2)
        print(f"{action}: {timings[action]} s", flush=True)
        return record

    job("transcribe", {"language": "en"})
    job("vision")
    started = time.monotonic()
    suggestion = studio.suggest_chapters(project["id"])
    timings["suggest_chapters"] = round(time.monotonic() - started, 3)
    current = studio.get(project["id"])
    project = studio.update(
        project["id"],
        {
            "settings": {
                "chapters": [
                    {"start": c["start"], "title": c["title"]}
                    for c in suggestion["chapters"]
                ],
                "thumbnail": {"text": THUMBNAIL_TEXT},
                "end_screen_s": 20,
            }
        },
        current["revision"],
    )
    preview = job("preview")
    qa = job("qa")
    result = preview["result"]
    video = Path(result["output"])
    words = studio._program_words(project)
    duration = float(ffprobe(video, "-show_format")["format"]["duration"])
    streams = ffprobe(video, "-show_streams")["streams"]
    video_stream = next(s for s in streams if s["codec_type"] == "video")
    numerator, denominator = video_stream["avg_frame_rate"].split("/")
    frame_s = float(denominator) / float(numerator)

    chapters = project["settings"]["chapters"]
    listed = longform.probe_chapters(video)
    chapters_txt = Path(studio.artifact(project["id"], "chapters")).read_text(
        encoding="utf-8"
    )
    srt_path = studio.artifact(project["id"], "captions_srt")
    thumbnail_path = studio.artifact(project["id"], "thumbnail")
    thumbnail = ffprobe(thumbnail_path, "-show_streams")["streams"][0]
    evidence = directory / "evidence"
    evidence.mkdir()
    shutil.copyfile(thumbnail_path, evidence / "thumbnail.jpg")
    shutil.copyfile(srt_path, evidence / "captions.srt")
    (evidence / "chapters.txt").write_text(chapters_txt, encoding="utf-8")
    for index, chapter in enumerate(listed):
        frame(video, chapter["start"] + 0.5, evidence / f"chapter-{index + 1:02}.png")
    frame(video, max(0.0, duration - 10), evidence / "end-screen-area.png")
    lines = chapters_txt.splitlines()
    measurements = {
        "source": args.source,
        "program_duration_s": round(duration, 3),
        "timings_s": timings,
        "suggested_chapters": suggestion["chapters"],
        "chapters_txt": lines,
        "chapters_embedded": listed,
        "chapter_checks": {
            "first_at_zero": bool(listed) and listed[0]["start"] == 0,
            "count": len(listed),
            "shortest_s": round(min(c["end"] - c["start"] for c in listed), 3)
            if listed
            else None,
            "matches_txt": [
                f"{longform.clock(c['start'], duration >= 3600)} {c['title']}"
                for c in listed
            ]
            == lines,
            "matches_settings": [round(c["start"]) for c in listed]
            == [longform.whole(c["start"]) for c in chapters],
            "problems": longform.chapter_problems(chapters, duration),
        },
        "srt": check_srt(srt_path, words, frame_s, kept_text(project)),
        "thumbnail": {
            "width": int(thumbnail["width"]),
            "height": int(thumbnail["height"]),
            "aspect_16_9": int(thumbnail["width"]) * 9 == int(thumbnail["height"]) * 16,
            "bytes": Path(thumbnail_path).stat().st_size,
            "under_2_mb": Path(thumbnail_path).stat().st_size <= 2_000_000,
            "codec": thumbnail["codec_name"],
            "render": result["longform"]["thumbnail"],
        },
        "qa": {
            check["name"]: {"status": check["status"]}
            | (
                {"detail": check["detail"]}
                if check["name"]
                in {"chapters", "subtitles_file", "thumbnail", "end_screen"}
                else {}
            )
            for check in qa["result"]["checks"]
        },
    }
    (evidence / "measurements.json").write_text(
        json.dumps(measurements, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: measurements[k] for k in ("chapter_checks", "srt")}, indent=2))
    print("chapters:\n" + chapters_txt)
    print(
        "thumbnail:",
        measurements["thumbnail"]["width"],
        measurements["thumbnail"]["height"],
        measurements["thumbnail"]["bytes"],
    )
    print("qa:", {k: v["status"] for k, v in measurements["qa"].items()})


if __name__ == "__main__":
    main()
