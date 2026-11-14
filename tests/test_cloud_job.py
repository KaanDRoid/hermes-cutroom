"""Sending an approved final to a cloud folder from the Studio (never by the agent)."""

import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from cutroom import integrations, studio_tools
from cutroom.studio import Studio

REMOTES = [{"name": "cutroom-drive", "type": "drive"}]


def tiny_video(path):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=320x240:rate=10:duration=1", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=1", "-shortest", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    return path


class CloudJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = tempfile.TemporaryDirectory()
        cls.source = tiny_video(Path(cls.media.name) / "talk.mp4")

    @classmethod
    def tearDownClass(cls):
        cls.media.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.studio = Studio(self.root / "workspace")
        self.project = self.studio.create(self.source, name="Kaan'ın videosu")
        remotes = patch.object(integrations, "list_remotes", return_value=REMOTES)
        remotes.start()
        self.addCleanup(remotes.stop)

    def approve_and_export(self):
        project_id = self.project["id"]
        digest = self.studio.review(project_id)["digest"]
        self.studio.approve(project_id, digest)
        project = self.studio.get(project_id)
        job_id = uuid.uuid4().hex
        outputs = self.studio._job_path(job_id).parent / "outputs"
        outputs.mkdir(parents=True)
        (outputs / "final.mp4").write_bytes(b"approved final bytes")
        (outputs / "captions.srt").write_bytes(
            b"1\n00:00:00,000 --> 00:00:01,000\nHi\n"
        )
        artifacts = {
            "final": str(outputs / "final.mp4"),
            "captions_srt": str(outputs / "captions.srt"),
        }
        job = {"id": job_id, "project_id": project_id, "action": "final",
               "revision": project["revision"], "status": "completed",
               "result": {"artifacts": artifacts}}  # fmt: skip
        self.studio._write_job(job)
        with self.studio._lock():
            current = self.studio.get(project_id)
            self.studio._publish(current, job, artifacts, platform="custom")
            self.studio._write(current)
        return self.studio.get(project_id)

    def submit(self, **options):
        options = {"remote": "cutroom-drive", "folder": "Cutroom",
                   "files": ["final"], "confirmed": True, **options}  # fmt: skip
        with patch("subprocess.Popen"):
            return self.studio.submit(self.project["id"], "upload", options)

    def test_sending_needs_explicit_consent(self):
        self.approve_and_export()
        with self.assertRaises(PermissionError):
            self.submit(confirmed=False)

    def test_only_an_exported_final_of_the_approved_version_can_be_sent(self):
        with self.assertRaisesRegex(PermissionError, "Export the approved final"):
            self.submit()
        self.approve_and_export()
        self.studio.update(
            self.project["id"],
            {"name": "Renamed"},
            self.studio.get(self.project["id"])["revision"],
        )
        with self.assertRaisesRegex(PermissionError, "Export the approved final"):
            self.submit()

    def test_the_remote_must_be_configured_and_the_folder_plain(self):
        self.approve_and_export()
        with self.assertRaisesRegex(ValueError, "not set up"):
            self.submit(remote="elsewhere")
        # A leading or trailing slash is tidied away; escapes are refused.
        for folder in ("../up", "a/../b", "a\\b", "a:b", "", "  "):
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                self.submit(folder=folder)
        with self.assertRaisesRegex(ValueError, "final"):
            self.submit(files=["captions_srt"])
        with self.assertRaisesRegex(ValueError, "not available"):
            self.submit(files=["final", "thumbnail"])

    def test_files_go_to_a_new_dated_folder_with_progress_and_drive_links(self):
        self.approve_and_export()
        job = self.submit(files=["final", "captions_srt"])
        self.assertEqual(job["status"], "queued")
        calls, progress = [], []

        def fake_upload(local, remote, confirmed, *, progress, cancelled, remote_type):
            calls.append((Path(local).read_bytes(), remote, confirmed, remote_type))
            progress(0.5)
            progress(1.0)
            return {"remote": remote, "size": Path(local).stat().st_size,
                    "verified": True, "verification": "hash",
                    "hash_verified": ["MD5"], "link": "https://drive.google.com/file/d/x/view",
                    "external_write": True}  # fmt: skip

        real_progress = self.studio._job_progress
        with (
            patch.object(integrations, "upload_rclone", side_effect=fake_upload),
            patch.object(
                self.studio,
                "_job_progress",
                side_effect=lambda i, v: (progress.append(v), real_progress(i, v)),
            ),
        ):
            result = self.studio._perform_job(self.studio.job(job["id"]))
        self.studio._complete_job(self.studio.job(job["id"]), result)
        self.assertEqual(
            [c[0] for c in calls],
            [b"approved final bytes", b"1\n00:00:00,000 --> 00:00:01,000\nHi\n"],
        )
        folder = calls[0][1].rsplit("/", 1)[0]
        self.assertRegex(
            folder,
            r"^cutroom-drive:Cutroom/Kaan'ın videosu \d{4}-\d{2}-\d{2} \d{2}\.\d{2}$",
        )
        self.assertEqual(calls[0][1], folder + "/Kaan'ın videosu.mp4")
        self.assertEqual(calls[1][1], folder + "/Kaan'ın videosu.srt")
        self.assertEqual({c[2] for c in calls} | {c[3] for c in calls}, {True, "drive"})
        self.assertEqual(progress[-1], 1.0)
        self.assertTrue(all(a <= b for a, b in zip(progress, progress[1:])))
        done = self.studio.job(job["id"])
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["result"]["destination"], folder)
        self.assertEqual(
            [f["kind"] for f in done["result"]["files"]], ["final", "captions_srt"]
        )
        self.assertTrue(done["result"]["external_write"])
        # Sending changes nothing in the project.
        project = self.studio.get(self.project["id"])
        self.assertEqual(
            project["revision"], self.studio.get(self.project["id"])["revision"]
        )
        self.assertIn("approval", project)

    def test_an_edit_during_sending_still_records_what_was_sent(self):
        self.approve_and_export()
        job = self.submit()
        result = {
            "destination": "cutroom-drive:Cutroom/x",
            "files": [],
            "external_write": True,
        }
        project = self.studio.get(self.project["id"])
        self.studio.update(self.project["id"], {"name": "Edited"}, project["revision"])
        self.studio._complete_job(self.studio.job(job["id"]), result)
        self.assertEqual(self.studio.job(job["id"])["status"], "completed")

    def test_the_agent_cannot_send_files(self):
        self.assertNotIn("upload", studio_tools.JOB_OPERATIONS)
        definitions = json.dumps(studio_tools.definitions())
        self.assertNotIn('"upload"', definitions)

    def test_remotes_are_listed_for_the_studio(self):
        self.assertEqual(self.studio.cloud_remotes(), REMOTES)


if __name__ == "__main__":
    unittest.main()
