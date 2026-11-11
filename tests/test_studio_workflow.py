"""End-to-end Studio actions on synthetic FFmpeg media.

Synthetic tones and test patterns prove mechanics (routing, timing, lineage and
publication rules). They are not evidence of editorial quality on real speech.
"""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.job_worker import main as supervise
from cutroom.media import probe
from cutroom.runtime import runtime_python
from cutroom.studio import _CHILD_PROCESSES, Studio

ROOT = Path(__file__).resolve().parents[1]
FACE_MODEL = ROOT / "models" / "face_landmarker.task"
PERSON_MODEL = ROOT / "models" / "selfie_segmenter.tflite"


def words():
    return [
        dict(id=0, start=0.2, end=0.8, text="Hello", probability=0.9),
        dict(id=1, start=1.0, end=1.6, text="um", probability=0.9),
        dict(id=2, start=2.0, end=2.8, text="world", probability=0.9),
        dict(id=3, start=3.0, end=3.6, text="again", probability=0.9),
    ]


def transcript():
    items = words()
    return dict(
        language="en",
        words=items,
        text=" ".join(word["text"] for word in items),
        engine="synthetic-fixture",
        status="ok",
    )


def native_vision_available():
    if not (FACE_MODEL.is_file() and PERSON_MODEL.is_file()):
        return False
    completed = subprocess.run(
        [runtime_python(), "-c", "import cv2, mediapipe, numpy"],
        capture_output=True,
        timeout=60,
    )
    return completed.returncode == 0


class WorkflowJobsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "synthetic-speech-like.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=160x90:rate=10:duration=4",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=330:sample_rate=48000:duration=4",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(self.source),
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )
        self.studio = Studio(self.root / "workspace")
        self.addCleanup(self.reap)
        project = self.studio.create(self.source)
        self.project = self.studio.update(
            project["id"], {"transcript": transcript()}, project["revision"]
        )

    def reap(self):
        for job_id, process in list(_CHILD_PROCESSES.items()):
            try:
                process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                process.kill()
            _CHILD_PROCESSES.pop(job_id, None)

    def wait(self, job, timeout=240):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = self.studio.job(job["id"])
            if current["status"] in {"completed", "failed", "cancelled"}:
                process = _CHILD_PROCESSES.pop(job["id"], None)
                if process is not None:
                    process.wait(timeout=60)
                return current
            time.sleep(0.05)
        self.fail("Background job did not terminate")

    def run_job(self, action, options=None):
        job = self.wait(self.studio.submit(self.project["id"], action, options or {}))
        self.assertEqual(job["status"], "completed", job)
        self.project = self.studio.get(self.project["id"])
        return job

    def edit(self, changes):
        self.project = self.studio.update(
            self.project["id"], changes, self.project["revision"]
        )
        return self.project

    def approve(self):
        digest = self.studio.review(self.project["id"])["digest"]
        self.project = self.studio.approve(self.project["id"], digest)

    def test_storyboard_offers_three_hooks_then_builds_the_selected_storyboard(self):
        before = self.project["revision"]
        job = self.run_job("storyboard")
        story = self.project["story"]
        self.assertEqual(len(story["hooks"]), 3)
        self.assertTrue(all(hook["text"] for hook in story["hooks"]))
        self.assertEqual(story["storyboard"], [])
        self.assertEqual(story["status"], "awaiting_hook_selection")
        self.assertEqual(self.project["revision"], before + 1)
        self.assertEqual(job["applied_revision"], self.project["revision"])

        self.edit({"selected_hook": 1})
        self.approve()
        with self.assertRaisesRegex(PermissionError, "storyboard"):
            self.studio.submit(self.project["id"], "final")

        self.run_job("storyboard")
        story = self.project["story"]
        self.assertEqual(story["selected_hook"], 1)
        self.assertEqual(story["opening_hook"]["text"], story["hooks"][1]["text"])
        self.assertTrue(story["storyboard"])
        self.assertNotIn("approval", self.project)
        self.assertIn("storyboard", self.project["artifacts"])
        saved = json.loads(
            self.studio.artifact(self.project["id"], "storyboard").read_text("utf-8")
        )
        self.assertEqual(saved["selected_hook"], 1)

    def test_long_titles_are_wrapped_for_legible_overlays(self):
        settings = self.studio._render_settings(
            {
                **self.project,
                "settings": {**self.project["settings"], "aspect": "portrait"},
                "story": {
                    "opening_hook": {
                        "text": "And so my fellow Americans, ask not what your country can do"
                    }
                },
            },
            "preview",
        )
        lines = settings["title"].split("\n")
        self.assertGreater(len(lines), 1)
        self.assertLessEqual(max(map(len, lines)), 24)
        self.assertLessEqual(len(lines), 3)
        self.assertEqual(
            " ".join(lines),
            "And so my fellow Americans, ask not what your country can do",
        )

    def test_storyboard_and_unknown_options_fail_before_a_job_is_created(self):
        bare = self.studio.create(self.source)
        with self.assertRaisesRegex(ValueError, "transcript"):
            self.studio.submit(bare["id"], "storyboard")
        for action, options in (
            ("storyboard", {"anything": 1}),
            ("preview", {"source": "other.mp4"}),
            ("vision", {"frame_step": 0}),
            ("vision", {"frame_step": True}),
            ("segment", {"output": "x.mp4"}),
            ("cover", {"time": -1}),
            ("qa", {"video": "x.mp4"}),
        ):
            with self.subTest(action=action, options=options):
                with self.assertRaises(ValueError):
                    self.studio.submit(self.project["id"], action, options)
        self.assertEqual(self.studio.jobs(self.project["id"]), [])

    def test_preview_exports_current_cut_with_remapped_sidecar_captions(self):
        self.edit({"excluded_word_ids": [1], "settings": {"title": "Demo"}})
        self.approve()
        job = self.run_job("preview")
        self.assertEqual(self.project["status"], "approved")
        expected = sum(item["end"] - item["start"] for item in self.project["segments"])
        preview = self.studio.artifact(self.project["id"], "preview")
        owned = (self.studio.root / "jobs" / job["id"] / "outputs").resolve()
        self.assertTrue(preview.is_relative_to(owned))
        self.assertAlmostEqual(probe(preview)["duration"], expected, delta=0.25)
        srt = self.studio.artifact(self.project["id"], "captions_srt").read_text(
            "utf-8"
        )
        vtt = self.studio.artifact(self.project["id"], "captions_vtt").read_text(
            "utf-8"
        )
        self.assertIn("Hello", srt)
        self.assertIn("world", srt)
        self.assertNotIn("um", srt.split())
        self.assertTrue(vtt.startswith("WEBVTT"))
        lineage = self.project["artifact_lineage"]["preview"]
        self.assertEqual(lineage["job_id"], job["id"])
        self.assertEqual(lineage["digest"], job["review_digest"])

        self.edit({"settings": {"title": "Changed"}})
        self.assertNotIn("preview", self.project["artifacts"])
        self.assertNotIn("captions_srt", self.project["artifacts"])
        with self.assertRaises(FileNotFoundError):
            self.studio.artifact(self.project["id"], "preview")

    def test_published_artifact_tampering_is_detected(self):
        self.run_job("preview")
        path = self.studio.artifact(self.project["id"], "captions_srt")
        path.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(PermissionError, "changed"):
            self.studio.artifact(self.project["id"], "captions_srt")

    def test_final_cover_and_quality_follow_the_approved_current_render(self):
        self.edit({"settings": {"aspect": "square", "title": "Final cut"}})
        with self.assertRaises(PermissionError):
            self.studio.submit(self.project["id"], "final")
        for action in ("cover", "qa"):
            with self.assertRaisesRegex(ValueError, "(?i)render"):
                self.studio.submit(self.project["id"], action)
        self.approve()
        self.run_job("final")
        final = probe(self.studio.artifact(self.project["id"], "final"))
        self.assertEqual((final["width"], final["height"]), (2160, 2160))
        self.run_job("cover", {"time": 0.5})
        cover = self.studio.artifact(self.project["id"], "cover")
        self.assertEqual(cover.suffix, ".png")
        self.assertGreater(cover.stat().st_size, 1000)
        self.assertEqual(self.project["artifact_lineage"]["cover"]["from"], "final")
        job = self.run_job("qa")
        report = json.loads(
            self.studio.artifact(self.project["id"], "quality").read_text("utf-8")
        )
        self.assertIn("checks", report)
        self.assertEqual(report["video"], "final")
        self.assertEqual(job["result"]["passed"], report["passed"])

    def test_stale_render_is_not_published_and_its_outputs_are_removed(self):
        with patch("subprocess.Popen"):
            job = self.studio.submit(self.project["id"], "preview")
        _CHILD_PROCESSES.pop(job["id"], None)
        real = Studio._perform_job

        def perform(instance, record):
            result = real(instance, record)
            instance.update(
                self.project["id"], {"brief": "late edit"}, self.project["revision"]
            )
            return result

        with patch.object(Studio, "_perform_job", perform):
            self.assertEqual(supervise([str(self.studio.root), job["id"]]), 1)
        current = self.studio.job(job["id"])
        self.assertEqual(current["status"], "failed", current)
        self.assertNotIn("preview", self.studio.get(self.project["id"])["artifacts"])
        self.assertFalse((self.studio.root / "jobs" / job["id"] / "outputs").exists())

    @unittest.skipUnless(
        native_vision_available(), "Local MediaPipe runtime and models are required"
    )
    def test_vision_and_segmentation_run_real_local_models(self):
        self.edit(
            {
                "settings": {
                    "face_model": str(FACE_MODEL),
                    "segmentation_model": str(PERSON_MODEL),
                    "background": "#204060",
                    "max_width": 160,
                }
            }
        )
        self.approve()
        before = self.project["revision"]
        self.run_job("vision", {"frame_step": 1})
        analysis = self.project["analysis"]
        self.assertEqual(analysis["status"], "no_face_detected")
        self.assertTrue(analysis["coverage"]["complete"])
        self.assertEqual(analysis["sampled_frames"], 40)
        self.assertFalse(analysis["automatic_removal"])
        self.assertEqual(self.project["revision"], before + 1)
        self.assertNotIn("approval", self.project)

        self.run_job("segment")
        segmented = self.studio.artifact(self.project["id"], "segmented")
        self.assertEqual(probe(segmented)["width"], 160)
        # A synthetic pattern carries no ground truth about people; assert coverage.
        segmentation = self.project["segmentation"]
        self.assertIn(segmentation["status"], {"ok", "no_person_detected"})
        self.assertEqual(segmentation["segmentation"]["processed_frames"], 40)
        self.edit({"settings": {"use_segmented": True}})
        self.assertEqual(
            self.studio.artifact(self.project["id"], "segmented"), segmented
        )
        job = self.run_job("preview")
        self.assertEqual(job["result"]["render_source"], str(segmented))

        self.edit({"settings": {"background": "#000000"}})
        self.assertNotIn("segmented", self.project["artifacts"])
        with self.assertRaisesRegex(ValueError, "segment"):
            self.studio.submit(self.project["id"], "preview")


@unittest.skipUnless(
    os.environ.get("CUTROOM_TEST_USER_MEDIA") == "1"
    and native_vision_available()
    and (ROOT / "raw_vids" / "4439224-uhd_2160_3840_25fps.mp4").is_file(),
    "Consented portrait clip and native models are local-only",
)
class ConsentedPortraitAcceptance(unittest.TestCase):
    def test_full_frame_face_review_and_person_layer_on_consented_clip(self):
        with tempfile.TemporaryDirectory() as temporary:
            studio = Studio(Path(temporary) / "workspace")
            project = studio.create(
                ROOT / "raw_vids" / "4439224-uhd_2160_3840_25fps.mp4"
            )
            project = studio.update(
                project["id"],
                {
                    "settings": {
                        "face_model": str(FACE_MODEL),
                        "segmentation_model": str(PERSON_MODEL),
                        "background": "#16324F",
                        "max_width": 540,
                    }
                },
                project["revision"],
            )
            for action in ("vision", "segment"):
                job = studio.submit(project["id"], action, {})
                deadline = time.monotonic() + 900
                while studio.job(job["id"])["status"] not in {
                    "completed",
                    "failed",
                    "cancelled",
                }:
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.2)
                job = studio.job(job["id"])
                _CHILD_PROCESSES.pop(job["id"], None)
                self.assertEqual(job["status"], "completed", job)
                project = studio.get(project["id"])
            self.assertEqual(project["analysis"]["status"], "ok")
            self.assertEqual(project["analysis"]["frame_count"], 264)
            self.assertEqual(project["segmentation"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
