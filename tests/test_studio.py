"""Studio project persistence and concurrency behavior."""

import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.studio import Studio


class StudioTests(unittest.TestCase):
    def test_manual_ranges_remain_authoritative_across_other_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "unit.mp4"
            source.write_bytes(b"unit source, not media")
            with patch(
                "cutroom.studio.probe",
                return_value={
                    "duration": 4.0,
                    "width": 320,
                    "height": 180,
                    "has_audio": False,
                },
            ):
                studio = Studio(root / "workspace")
                project = studio.create(source)
            selected = [{"start": 1.0, "end": 2.0}]
            project = studio.update(
                project["id"], {"segments": selected}, project["revision"]
            )
            project = studio.update(
                project["id"], {"gaze_exclusions": []}, project["revision"]
            )
            self.assertEqual(project["segments"], selected)
            self.assertEqual(project["base_segments"], selected)
            words = [
                dict(id=0, start=0.5, end=1.5, text="First", probability=0.9),
                dict(id=1, start=1.5, end=1.6, text="um", probability=0.9),
                dict(id=2, start=1.6, end=3.0, text="last", probability=0.9),
            ]
            transcript = dict(
                language="en",
                words=words,
                text="First um last",
                engine="manual",
                status="ok",
            )
            project = studio.update(
                project["id"],
                {"transcript": transcript, "excluded_word_ids": [1]},
                project["revision"],
            )
            self.assertEqual(
                project["segments"],
                [{"start": 1.0, "end": 1.5}, {"start": 1.6, "end": 2.0}],
            )
            project = studio.update(
                project["id"],
                {"segments": [{"start": 1.2, "end": 1.8}], "gaze_exclusions": []},
                project["revision"],
            )
            self.assertEqual(
                project["segments"],
                [{"start": 1.2, "end": 1.5}, {"start": 1.6, "end": 1.8}],
            )

    def test_create_list_reopen_preserves_source_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "unit-source.mp4"
            source.write_bytes(b"unit fixture, not video")
            with patch(
                "cutroom.studio.probe",
                return_value={
                    "duration": 4.0,
                    "width": 320,
                    "height": 180,
                    "has_audio": False,
                },
            ):
                studio = Studio(root / "workspace")
                project = studio.create(source, name="First project")
            reopened = Studio(root / "workspace").get(project["id"])
            self.assertEqual(reopened["source"], str(source.resolve()))
            self.assertEqual(reopened["revision"], 1)
            self.assertEqual(reopened["segments"], [{"start": 0.0, "end": 4.0}])
            self.assertEqual(studio.list()[0]["id"], project["id"])
            # The list carries the save time for display; it is not project data.
            listed = studio.list()[0]
            self.assertIsInstance(listed["modified_at"], float)
            self.assertNotIn("modified_at", reopened)
            self.assertEqual(
                studio.review(project["id"])["digest"],
                studio.review(project["id"])["digest"],
            )
            self.assertEqual(reopened["source_sha256"], project["source_sha256"])
            with self.assertRaises(ValueError):
                studio.get("../escape")

    def test_revision_edits_and_exact_approval_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            source.write_bytes(b"unit source fixture")
            with patch(
                "cutroom.studio.probe",
                return_value={
                    "duration": 4.0,
                    "width": 320,
                    "height": 180,
                    "has_audio": False,
                },
            ):
                studio = Studio(root / "workspace")
                project = studio.create(source)
            edited = studio.update(
                project["id"],
                {"settings": {"title": "My title", "aspect": "portrait"}},
                1,
            )
            self.assertEqual(edited["revision"], 2)
            with self.assertRaises(ValueError):
                studio.update(project["id"], {"brief": "stale"}, 1)
            reviewed = studio.review(project["id"])
            with self.assertRaises(PermissionError):
                studio.approve(project["id"], "wrong")
            approved = studio.approve(project["id"], reviewed["digest"])
            self.assertEqual(approved["status"], "approved")
            edited = studio.update(project["id"], {"brief": "New brief"}, 2)
            self.assertNotIn("approval", edited)
            with self.assertRaises(PermissionError):
                studio.approve(project["id"], reviewed["digest"])
            source.write_bytes(b"changed source")
            with self.assertRaises(PermissionError):
                studio.review(project["id"])

    def test_background_job_survives_facade_reopen(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic-fixture.mp4"
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
                    "testsrc2=size=160x90:rate=10:duration=1",
                    "-c:v",
                    "libx264",
                    str(source),
                ],
                capture_output=True,
                check=True,
                timeout=20,
            )
            studio = Studio(root / "workspace")
            project = studio.create(source)
            job = studio.submit(project["id"], "inspect")
            reopened = Studio(root / "workspace")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                current = reopened.job(job["id"])
                if current["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.05)
            self.assertEqual(current["status"], "completed", current)
            self.assertEqual(current["result"]["width"], 160)
            self.assertEqual(reopened.jobs(project["id"])[0]["id"], job["id"])

    def test_unreviewed_final_and_external_jobs_never_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            source.write_bytes(b"unit fixture, not media")
            with patch(
                "cutroom.studio.probe",
                return_value={
                    "duration": 4.0,
                    "width": 320,
                    "height": 180,
                    "has_audio": False,
                },
            ):
                studio = Studio(root / "workspace")
                project = studio.create(source)
            for action in ("final", "download", "publish", "obs"):
                with self.subTest(action=action), self.assertRaises(PermissionError):
                    studio.submit(project["id"], action)
            self.assertEqual(studio.jobs(), [])
            with self.assertRaises(ValueError):
                studio.update(project["id"], {"source": "replacement.mp4"}, 1)

    def test_cancelled_queued_job_has_no_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            source.write_bytes(b"unit fixture, not media")
            with patch(
                "cutroom.studio.probe",
                return_value={
                    "duration": 4.0,
                    "width": 320,
                    "height": 180,
                    "has_audio": False,
                },
            ):
                studio = Studio(root / "workspace")
                project = studio.create(source)
            with studio._lock("queue"):
                job = studio.submit(project["id"], "inspect")
                studio.cancel(job["id"])
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                current = studio.job(job["id"])
                if current["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.05)
            self.assertEqual(current["status"], "cancelled", current)
            self.assertIsNone(current["result"])

    def test_transient_windows_read_sharing_error_is_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            studio = Studio(Path(temporary) / "workspace")
            job_id = "a" * 32
            path = studio._job_path(job_id)
            path.parent.mkdir(parents=True)
            path.write_text('{"id":"' + job_id + '","status":"completed"}')
            original = Path.read_text
            calls = []

            def transient(path, *args, **kwargs):
                if not calls:
                    calls.append(True)
                    raise PermissionError(
                        "Simulated transient Windows sharing violation"
                    )
                return original(path, *args, **kwargs)

            with patch.object(Path, "read_text", autospec=True, side_effect=transient):
                self.assertEqual(studio.job(job_id)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
