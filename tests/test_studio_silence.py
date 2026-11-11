"""Silence routing through the public Studio and isolated engine boundaries."""

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from process_helpers import wait_for_process_exit

from cutroom.job_worker import main as supervise
from cutroom.runtime import invoke_worker
from cutroom.studio import Studio


class SilenceJobsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "synthetic-tone-silence-tone.mp4"
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
                "testsrc2=size=64x64:rate=10:duration=4",
                "-f",
                "lavfi",
                "-i",
                r"aevalsrc=if(between(t\,1\,3)\,0\,0.25*sin(2*PI*440*t)):s=48000:d=4",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                "-shortest",
                str(self.source),
            ],
            capture_output=True,
            check=True,
            timeout=20,
        )
        self.studio = Studio(self.root / "workspace")
        self.project = self.studio.create(self.source)

    def wait(self, job):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            current = self.studio.job(job["id"])
            if current["status"] in {"completed", "failed", "cancelled"}:
                return current
            time.sleep(0.05)
        self.fail("Background job did not terminate")

    def test_real_isolated_silence_returns_source_time_plan(self):
        result = invoke_worker(
            "silence",
            {"source": str(self.source), "padding": 0.0},
            self.root / "engine",
        )
        self.assertEqual(len(result["segments"]), 2)
        self.assertAlmostEqual(result["segments"][0]["end"], 1.0, delta=0.1)
        self.assertAlmostEqual(result["segments"][1]["start"], 3.0, delta=0.1)

    def test_public_job_applies_cuts_preserves_manual_ranges_and_revokes_approval(self):
        project = self.studio.update(
            self.project["id"],
            {"segments": [{"start": 0.5, "end": 3.5}]},
            1,
        )
        self.studio.approve(project["id"], self.studio.review(project["id"])["digest"])
        job = self.wait(self.studio.submit(project["id"], "silence", {"padding": 0.0}))
        self.assertEqual(job["status"], "completed", job)
        reopened = Studio(self.studio.root).get(project["id"])
        self.assertEqual(reopened["revision"], 3)
        self.assertEqual(reopened["status"], "draft")
        self.assertNotIn("approval", reopened)
        self.assertEqual(len(reopened["segments"]), 2)
        self.assertEqual(reopened["segments"][0]["start"], 0.5)
        self.assertEqual(reopened["segments"][1]["end"], 3.5)
        self.assertAlmostEqual(reopened["segments"][0]["end"], 1.0, delta=0.1)
        self.assertAlmostEqual(reopened["segments"][1]["start"], 3.0, delta=0.1)
        self.assertEqual(reopened["base_segments"], reopened["segments"])
        self.assertEqual(self.studio.review(project["id"])["project"], reopened)
        with self.assertRaises(PermissionError):
            self.studio.submit(project["id"], "final")

    def test_bad_options_are_rejected_before_job_creation(self):
        for options in (
            {"source": "another.mp4"},
            {"padding": -1},
            {"padding": True},
            {"min_duration": 0},
            {"noise_db": "-35"},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.studio.submit(self.project["id"], "silence", options)
        self.assertEqual(self.studio.jobs(), [])

    def test_queued_revision_change_fails_without_applying_cuts(self):
        with self.studio._lock("queue"):
            job = self.studio.submit(self.project["id"], "silence")
            edited = self.studio.update(self.project["id"], {"brief": "Keep this"}, 1)
        result = self.wait(job)
        self.assertEqual(result["status"], "failed", result)
        self.assertIsNone(result["result"])
        self.assertEqual(self.studio.get(self.project["id"]), edited)
        self.assertFalse((self.studio._job_path(job["id"]).parent / "engine").exists())

    def test_silence_keeps_existing_word_and_gaze_exclusions(self):
        project = self.studio.update(
            self.project["id"],
            {
                "transcript": {
                    "language": "en",
                    "engine": "manual",
                    "status": "ok",
                    "text": "First um last",
                    "words": [
                        dict(id=0, start=0.0, end=0.5, text="First", probability=0.9),
                        dict(id=1, start=0.5, end=0.7, text="um", probability=0.9),
                        dict(id=2, start=0.7, end=4.0, text="last", probability=0.9),
                    ],
                },
                "excluded_word_ids": [1],
                "gaze_exclusions": [{"start": 3.5, "end": 4.0}],
            },
            1,
        )
        result = self.wait(self.studio.submit(project["id"], "silence", {"padding": 0}))
        self.assertEqual(result["status"], "completed", result)
        updated = self.studio.get(project["id"])
        self.assertEqual(updated["excluded_word_ids"], [1])
        self.assertEqual(updated["gaze_exclusions"], project["gaze_exclusions"])
        segments = updated["segments"]
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0], {"start": 0.0, "end": 0.5})
        self.assertEqual(segments[1]["start"], 0.7)
        self.assertEqual(segments[2]["end"], 3.5)

    def test_silence_cannot_remove_the_entire_manual_selection(self):
        project = self.studio.update(
            self.project["id"],
            {"segments": [{"start": 1.5, "end": 2.5}]},
            1,
        )
        job = self.wait(self.studio.submit(project["id"], "silence", {"padding": 0}))
        self.assertEqual(job["status"], "failed", job)
        self.assertIn("at least one", job["error"])
        self.assertEqual(self.studio.get(project["id"]), project)

    def test_queued_job_survives_real_submitter_process_exit(self):
        code = (
            "import json,sys; from cutroom.studio import Studio,_CHILD_PROCESSES; "
            "studio=Studio(sys.argv[1]); "
            "job=studio.submit(sys.argv[2], 'silence'); "
            "print(json.dumps({'job':job,'worker_pid':_CHILD_PROCESSES[job['id']].pid}))"
        )
        with self.studio._lock("queue"):
            caller = subprocess.run(
                [sys.executable, "-c", code, str(self.studio.root), self.project["id"]],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
            submitted = json.loads(caller.stdout)
            job = submitted["job"]
            # The caller owns the Popen, so this process cannot reap it via Studio.job.
            # LIFO cleanup waits on the actual worker before deleting its workspace.
            self.addCleanup(wait_for_process_exit, submitted["worker_pid"], 10)
            self.assertEqual(self.studio.job(job["id"])["status"], "queued")
        result = self.wait(job)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["applied_revision"], 2)
        updated = Studio(self.studio.root).get(self.project["id"])
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(len(updated["segments"]), 2)

    def test_no_audio_keeps_full_source(self):
        video = self.root / "silent-video.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(self.source),
                "-an",
                "-c:v",
                "copy",
                str(video),
            ],
            capture_output=True,
            check=True,
            timeout=20,
        )
        project = self.studio.create(video)
        job = self.wait(self.studio.submit(project["id"], "silence"))
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(
            self.studio.get(project["id"])["segments"], project["segments"]
        )

    def test_completion_rechecks_assets_cancellation_source_and_revision(self):
        # Deterministic supervisor races; inference is mocked, not media acceptance.
        for change in ("asset", "cancel", "source", "revision", "empty"):
            with self.subTest(change=change):
                studio = Studio(self.root / change)
                project = studio.create(self.source)
                graphic = self.root / (change + ".txt")
                graphic.write_text("original")
                project = studio.update(
                    project["id"],
                    {"settings": {"graphic": str(graphic)}},
                    1,
                )
                # Persist a queued public request, but execute its supervisor here.
                with patch("subprocess.Popen") as launch:
                    job = studio.submit(project["id"], "silence")
                from cutroom.studio import _CHILD_PROCESSES

                _CHILD_PROCESSES.pop(job["id"], None)
                launch.assert_called_once()

                def perform(instance, record):
                    if change == "asset":
                        graphic.write_text("changed")
                    elif change == "cancel":
                        instance.cancel(record["id"])
                    elif change == "source":
                        self.source.write_bytes(self.source.read_bytes() + b"changed")
                    elif change == "revision":
                        instance.update(project["id"], {"brief": "new edit"}, 2)
                    return {
                        "version": 1,
                        "source": str(self.source.resolve()),
                        "source_duration": project["source_info"]["duration"],
                        "segments": []
                        if change == "empty"
                        else [{"start": 0.0, "end": 0.5}],
                    }

                with patch.object(Studio, "_perform_job", perform):
                    self.assertEqual(supervise([str(studio.root), job["id"]]), 1)
                current = studio.job(job["id"])
                expected = "cancelled" if change == "cancel" else "failed"
                self.assertEqual(current["status"], expected, current)
                self.assertIsNone(current["result"])
                after = studio.get(project["id"])
                self.assertEqual(after["segments"], project["segments"])
                self.assertEqual(after["revision"], 3 if change == "revision" else 2)


if __name__ == "__main__":
    unittest.main()
