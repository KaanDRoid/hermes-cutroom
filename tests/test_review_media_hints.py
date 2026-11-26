"""Chat hints must agree with Studio's publication and approval guards."""

import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from cutroom.studio import Studio
from cutroom.studio_tools import _with_media


class CurrentMediaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.studio = Studio(self.root / "workspace")
        source = self.root / "source.mp4"
        source.write_bytes(b"source fixture, not playable media")
        self.music = self.root / "music.wav"
        with wave.open(str(self.music), "wb") as stream:
            stream.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            stream.writeframes(b"\0\0" * 8000)
        with patch("cutroom.studio.probe", return_value={"duration": 4.0}):
            project = self.studio.create(source)
        project = self.studio.update(
            project["id"],
            {"settings": {"music": {"path": str(self.music)}}},
            project["revision"],
        )
        self.pid = project["id"]
        project = self.studio.approve(self.pid, self.studio.review(self.pid)["digest"])
        job_id = "a" * 32
        outputs = self.studio._job_path(job_id).parent / "outputs"
        outputs.mkdir(parents=True)
        self.path = outputs / "final.mp4"
        self.path.write_bytes(b"published fixture, not playable media")
        self.job = {
            "id": job_id,
            "project_id": self.pid,
            "action": "final",
            "status": "completed",
            "result": {"artifacts": {"final": str(self.path)}},
        }
        self.studio._publish(project, self.job, {"final": str(self.path)})
        self.studio._write(project)
        self.studio._write_job(dict(self.job, created_at=0))

    def test_reviewed_music_change_cannot_advertise_current_approved_media(self):
        before = _with_media(self.studio, self.job)
        self.assertTrue(before["media"]["current"])
        self.assertTrue(before["media"]["approved"])
        self.assertIn("MEDIA:", before["display_hint"])
        self.music.write_bytes(b"replacement music")
        with self.assertRaises(FileNotFoundError):
            self.studio.artifact(self.pid, "final")
        after = _with_media(self.studio, self.job)
        self.assertFalse(after["media"]["current"])
        self.assertFalse(after["media"]["approved"])
        self.assertNotIn("display_hint", after)

    def test_missing_file_clears_previously_enriched_media_and_hint(self):
        before = _with_media(self.studio, self.job)
        self.assertIn("display_hint", before)
        self.path.unlink()
        after = _with_media(self.studio, before)
        self.assertNotIn("media", after)
        self.assertNotIn("display_hint", after)
        self.assertEqual(after["status"], "completed")

    def test_tampered_publication_cannot_get_a_display_hint(self):
        self.path.write_bytes(b"tampered publication")
        with self.assertRaises(PermissionError):
            self.studio.artifact(self.pid, "final")
        result = _with_media(self.studio, self.job)
        self.assertFalse(result["media"]["current"])
        self.assertFalse(result["media"]["approved"])
        self.assertNotIn("display_hint", result)

    def test_playing_in_chunks_reads_each_file_once_until_it_changes(self):
        # Every 1 MiB chunk of the player asks for the artifact again; hashing the whole file each
        # time made a 20 MB preview take most of a minute to load.
        import cutroom.studio as studio_module

        real, seen = studio_module.file_digest, []
        self.studio = Studio(self.root / "workspace")  # A fresh server with nothing read yet.

        def counted(path):
            seen.append(Path(path).name)
            return real(path)

        with patch("cutroom.studio.file_digest", side_effect=counted):
            for _ in range(5):
                self.studio.artifact(self.pid, "final", playing=True)
                self.studio.artifact(self.pid, "source", playing=True)
            self.assertEqual(seen.count("final.mp4"), 1)
            self.assertEqual(seen.count("source.mp4"), 1)
            # Same size, new bytes and a new modification time: read and refused again.
            source = self.root / "source.mp4"
            before = source.stat()
            source.write_bytes(source.read_bytes()[::-1])
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
            with self.assertRaises(PermissionError):
                self.studio.artifact(self.pid, "source", playing=True)
            self.assertEqual(seen.count("source.mp4"), 2)
            # Everything but playback reads the whole file every time.
            self.studio.artifact(self.pid, "final")
            self.studio.artifact(self.pid, "final")
            self.assertEqual(seen.count("final.mp4"), 3)
