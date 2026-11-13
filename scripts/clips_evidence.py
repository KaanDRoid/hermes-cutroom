"""Local F5 evidence on a long talk; no source or output is overwritten.

Transcribes with a local Whisper directory, finds eight candidates, checks
sentence/word edges and quiet cut points, creates Shorts and Reels projects,
renders previews and runs QA. Measures sound and picture against the original
source range rather than against another edit. An interrupted run can resume
from its own workspace with --resume.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from cutroom.childenv import child_env  # noqa: E402
from cutroom.clips import energy_profile, sentences  # noqa: E402
from cutroom.media import poster_frame  # noqa: E402
from cutroom.studio import Studio  # noqa: E402


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def binary(args):
    return subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=600,
        shell=False,
        env=child_env(python=False),
    ).stdout


def audio(path, start, length, rate=8000):
    raw = binary(
        [
            "-ss",
            str(start),
            "-i",
            str(path),
            "-t",
            str(length),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-f",
            "f32le",
            "-",
        ]
    )
    return np.frombuffer(raw, dtype="<f4")


def correlation(a, b, limit):
    n = min(len(a), len(b)) - 2 * limit
    scores = []
    x = a[limit : limit + n].astype(float)
    x -= x.mean()
    for lag in range(-limit, limit + 1):
        y = b[limit + lag : limit + lag + n].astype(float)
        y -= y.mean()
        value = float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-12))
        scores.append((value, lag))
    value, lag = max(scores)
    return {"lag": lag, "correlation": round(value, 6)}


def picture_signal(path, start, length):
    # The source is fit into the middle of the vertical frame. Crop only the
    # picture, avoiding caption bands, then compare its motion and brightness.
    raw = binary(
        [
            "-ss",
            str(start),
            "-i",
            str(path),
            "-t",
            str(length),
            "-an",
            "-vf",
            "crop=iw:iw*9/16,scale=64:36,format=gray",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    n = len(raw) // (64 * 36)
    frames = (
        np.frombuffer(raw[: n * 64 * 36], dtype=np.uint8)
        .reshape(n, 36, 64)
        .astype(float)
    )
    return frames


def sync(source, rendered, start, duration, fps):
    measurements = []
    # Interior samples avoid the codec's first/last padded frames.
    for fraction in (0.2, 0.65):
        offset = duration * fraction
        length = min(5.0, duration - offset - 0.4)
        a = audio(source, start + offset, length)
        b = audio(rendered, offset, length)
        sound = correlation(a, b, 400)
        a_frames = picture_signal(source, start + offset, length)
        b_frames = picture_signal(rendered, offset, length)
        # Compare every pixel, not just means (which a static slide can share).
        best = (-2.0, 0)
        for lag in range(-3, 4):
            aa = a_frames[3 : len(a_frames) - 3]
            bb = b_frames[3 + lag : len(a_frames) - 3 + lag]
            n = min(len(aa), len(bb))
            if n < 3:
                continue
            aa, bb = aa[:n].reshape(-1), bb[:n].reshape(-1)
            aa, bb = aa - aa.mean(), bb - bb.mean()
            score = float(
                np.dot(aa, bb) / (np.linalg.norm(aa) * np.linalg.norm(bb) + 1e-12)
            )
            if score > best[0]:
                best = (score, lag)
        measurements.append(
            {
                "program_at": round(offset, 3),
                "audio_lag_samples_8000": sound["lag"],
                "audio_correlation": sound["correlation"],
                "video_lag_frames": best[1],
                "video_correlation": round(best[0], 6),
                "relative_av_offset_s": round(sound["lag"] / 8000 - best[1] / fps, 6),
            }
        )
    return measurements


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("models")
    parser.add_argument("output")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=args.resume)
    studio = Studio(directory / "workspace")
    state_path = directory / "run.json"
    state = (
        json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {}
    )
    timings = state.setdefault("timings", {})

    def job(pid, action):
        matches = [
            j
            for j in studio.jobs(pid)
            if j["action"] == action and j["status"] == "completed"
        ]
        if matches:
            return matches[-1]
        started = time.monotonic()
        record = studio.submit(pid, action)
        deadline = started + (3600 if action == "transcribe" else 1800)
        while record["status"] not in {"completed", "failed", "cancelled"}:
            if time.monotonic() > deadline:
                studio.cancel(record["id"])
                raise TimeoutError(f"{action} exceeded the evidence deadline")
            time.sleep(0.5)
            record = studio.job(record["id"])
        if record["status"] != "completed":
            raise RuntimeError(f"{action}: {record['error']}")
        timings[f"{pid}:{action}"] = round(time.monotonic() - started, 2)
        write(state_path, state)
        print(action, record["id"], "completed", flush=True)
        return record

    if "parent" not in state:
        project = studio.create(source, "Climate change is simple")
        project = studio.update(
            project["id"],
            {
                "settings": {
                    "whisper_model": str(Path(args.models).resolve() / "whisper-tiny"),
                    "captions": True,
                    "caption_style": "highlight",
                    "framing": "fit",
                }
            },
            project["revision"],
        )
        state["parent"] = project["id"]
        write(state_path, state)
    pid = state["parent"]
    job(pid, "transcribe")
    project = studio.get(pid)
    words = project["transcript"]["words"]
    write(directory / "transcript.json", project["transcript"])
    started = time.monotonic()
    found = studio.find_clips(pid, platform="youtube_shorts")
    timings["find_clips"] = round(time.monotonic() - started, 2)
    write(directory / "candidates.json", found)
    print("found", len(found["candidates"]), "candidates", flush=True)
    bounds = sentences(words)
    firsts = {s["first_id"]: s for s in bounds}
    lasts = {s["last_id"]: s for s in bounds}
    energy = energy_profile(source, project["source_info"]["duration"])
    levels = energy["db"]
    boundary_checks = []
    frames = directory / "frames"
    frames.mkdir(exist_ok=True)
    for candidate in found["candidates"]:
        first = firsts[candidate["first_word_id"]]
        last = lasts[candidate["last_word_id"]]
        previous = bounds[first["index"] - 1] if first["index"] else None
        nxt = bounds[last["index"] + 1] if last["index"] + 1 < len(bounds) else None
        cuts_words = [
            w["id"]
            for w in words
            if any(
                w["start"] + 0.001 < edge < w["end"] - 0.001
                for edge in (candidate["start"], candidate["end"])
            )
        ]
        dbs = [
            levels[min(len(levels) - 1, round(edge / energy["step"]))]
            for edge in (candidate["start"], candidate["end"])
        ]
        check = {
            "id": candidate["id"],
            "first_word": first["text"].split()[0],
            "last_word": last["text"].split()[-1],
            "previous_sentence_end": previous["end_kind"]
            if previous
            else "source start",
            "sentence_end": last["end_kind"],
            "cut_word_ids": cuts_words,
            "cut_level_db": dbs,
            "before_gap_s": round(
                first["start"] - (previous["end"] if previous else 0), 3
            ),
            "after_gap_s": round(
                (nxt["start"] if nxt else project["source_info"]["duration"])
                - last["end"],
                3,
            ),
        }
        boundary_checks.append(check)
        poster = frames / f"{candidate['id']}.jpg"
        if not poster.exists():
            poster_frame(source, candidate["start"], poster)
    write(directory / "boundaries.json", boundary_checks)
    # Save all diagnostics before checking, so a failure is inspectable.
    assert len(found["candidates"]) >= 5
    assert all(not c["cut_word_ids"] for c in boundary_checks), boundary_checks
    assert all(max(c["cut_level_db"]) <= -40 for c in boundary_checks), boundary_checks
    assert all(
        c["previous_sentence_end"] in {"stop", "question", "source start"}
        and c["sentence_end"] in {"stop", "question"}
        for c in boundary_checks
    ), boundary_checks
    children = state.setdefault("children", {})
    outputs = []
    fps = 30000 / 1001
    for index, platform in enumerate(("youtube_shorts", "instagram_reels")):
        pick = found["candidates"][index]
        if platform not in children:
            child = studio.create_clip(pid, platform, candidate_id=pick["id"])
            children[platform] = child["id"]
            write(state_path, state)
        child = studio.get(children[platform])
        preview = job(child["id"], "preview")
        qa = job(child["id"], "qa")
        report = qa["result"]
        assert not [c for c in report["checks"] if c["status"] == "fail"], report
        span = child["derived_from"]["range"]
        # The engine aligns the first kept picture frame; audio starts there too.
        actual_start = round(span["start"] * fps) / fps
        measurements = sync(
            source,
            preview["result"]["output"],
            actual_start,
            span["end"] - span["start"],
            fps,
        )
        outputs.append(
            {
                "platform": platform,
                "project_id": child["id"],
                "candidate_id": pick["id"],
                "range": span,
                "preview": preview["result"]["output"],
                "duration": preview["result"]["duration"],
                "checks": [
                    {"name": c["name"], "status": c["status"]} for c in report["checks"]
                ],
                "sync": measurements,
            }
        )
        target = frames / f"{platform}.jpg"
        if not target.exists():
            poster_frame(preview["result"]["output"], 3.0, target)
        write(
            directory / "measurements.json",
            {
                "candidates": len(found["candidates"]),
                "sentence_boundaries": boundary_checks,
                "renders": outputs,
                "timings": timings,
            },
        )
    sha1 = hashlib.sha1()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha1.update(block)
    write(
        directory / "source.json",
        {"path": str(source), "sha1": sha1.hexdigest(), "info": project["source_info"]},
    )
    assert all(
        abs(m["relative_av_offset_s"]) <= 0.06
        and m["audio_correlation"] > 0.9
        and m["video_correlation"] > 0.9
        for r in outputs
        for m in r["sync"]
    ), outputs
    print(
        json.dumps(
            {"candidates": len(found["candidates"]), "renders": outputs}, indent=2
        )
    )


if __name__ == "__main__":
    main()
