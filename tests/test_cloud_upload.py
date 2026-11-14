"""Sending approved files to a cloud folder through rclone."""

import hashlib
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cutroom import integrations

REMOTE = "cutroom-drive:Cutroom/Kaan'ın videosu 2026-11-14 01.55/video.mp4"


def stats(done, total):
    return json.dumps(
        {"level": "notice", "msg": "...", "stats": {"bytes": done, "totalBytes": total}}
    )


class FakeProcess:
    """A copyto process that prints the given stderr lines, then exits."""

    def __init__(self, lines, returncode=0, hold=None):
        self.lines = lines
        self.returncode = None
        self.final = returncode
        self.hold = hold
        self.terminated = False
        self.argv = None
        self.kwargs = None

        def stream():
            for line in self.lines:
                yield line + "\n"
                if self.hold is not None:
                    self.hold.wait(2)
            if not self.terminated:
                self.returncode = self.final

        self.stderr = stream()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = self.final if not self.terminated else 1
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1
        if self.hold is not None:
            self.hold.set()

    def kill(self):
        self.terminate()


class CloudUploadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.local = Path(temporary.name) / "video.mp4"
        self.local.write_bytes(b"approved final fixture")
        self.which = patch.object(
            integrations.shutil, "which", return_value="rclone.exe"
        )
        self.which.start()
        self.addCleanup(self.which.stop)

    def metadata(self, **extra):
        data = self.local.read_bytes()
        # Real rclone 1.76 output for Google Drive: lowercase hash names and an ID.
        return {
            "Name": "video.mp4",
            "IsDir": False,
            "Size": len(data),
            "Hashes": {
                "md5": hashlib.md5(data).hexdigest(),
                "sha1": hashlib.sha1(data).hexdigest(),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
            "ID": "1RB_ARVXfwdY_qVpyz7bw5Oxbpn9GehWM",
            **extra,
        }

    def upload(self, process, metadata=None, **kwargs):
        def popen(argv, **options):
            process.argv, process.kwargs = argv, options
            return process

        lsjson = MagicMock(stdout=json.dumps(metadata or self.metadata()))
        with (
            patch.object(integrations.subprocess, "Popen", side_effect=popen),
            patch.object(integrations.subprocess, "run", return_value=lsjson) as run,
        ):
            result = integrations.upload_rclone(
                self.local, REMOTE, confirmed=True, **kwargs
            )
        return result, run

    def test_real_lowercase_hash_names_are_verified(self):
        total = self.local.stat().st_size
        result, _ = self.upload(FakeProcess([stats(total, total)]))
        self.assertTrue(result["verified"])
        self.assertEqual(result["hash_verified"], ["MD5", "SHA-1", "SHA-256"])

    def test_progress_is_reported_from_rclone_stats(self):
        seen = []
        result, _ = self.upload(
            FakeProcess([stats(0, 6), "not json", stats(3, 6), stats(6, 6)]),
            progress=seen.append,
        )
        self.assertEqual(seen, [0.0, 0.5, 1.0])
        self.assertTrue(result["verified"])

    def test_copy_runs_without_a_shell_and_never_replaces_a_remote_file(self):
        process = FakeProcess([])
        self.upload(process)
        self.assertEqual(process.argv[0], "rclone.exe")
        self.assertIn("copyto", process.argv)
        self.assertIn("--immutable", process.argv)
        self.assertIn("--ignore-existing", process.argv)
        self.assertEqual(process.argv[-3:], ["--", str(self.local), REMOTE])
        self.assertIs(process.kwargs["shell"], False)
        self.assertNotIn("PYTHONPATH", process.kwargs["env"])

    def test_a_drive_upload_returns_a_private_link_to_the_file(self):
        result, _ = self.upload(FakeProcess([]), remote_type="drive")
        self.assertEqual(
            result["link"],
            "https://drive.google.com/file/d/1RB_ARVXfwdY_qVpyz7bw5Oxbpn9GehWM/view",
        )
        other, _ = self.upload(FakeProcess([]), remote_type="s3")
        self.assertIsNone(other["link"])

    def test_cancelling_stops_rclone_and_skips_verification(self):
        hold = threading.Event()
        process = FakeProcess([stats(0, 6), stats(3, 6)], hold=hold)
        asked = []

        def cancelled():
            asked.append(True)
            return len(asked) > 1

        with self.assertRaises(InterruptedError):
            _, run = self.upload(process, cancelled=cancelled)
        self.assertTrue(process.terminated)

    def test_a_failed_copy_says_no_success_was_verified(self):
        process = FakeProcess(
            [json.dumps({"level": "error", "msg": "Failed to copy: storage is full"})],
            returncode=1,
        )
        with self.assertRaisesRegex(
            RuntimeError, "storage is full. Nothing was verified"
        ):
            self.upload(process)

    def test_names_with_letters_outside_ascii_are_accepted_but_not_escapes(self):
        integrations._remote_target(REMOTE)
        for bad in (
            "cutroom-drive:Cutroom/../x.mp4",
            "cutroom-drive:Cutroom/a\x00b.mp4",
            "cutroom-drive:Cutroom/a\\b.mp4",
            "cutroom-drive:/abs.mp4",
            "x:file.mp4",
            "cutroom-drive:Cutroom/",
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                integrations._remote_target(bad)


class RemoteListTests(unittest.TestCase):
    def test_configured_remotes_are_listed_with_their_type(self):
        output = MagicMock(stdout="cutroom-drive: drive\nwork-bucket: s3\n\n")
        with (
            patch.object(integrations.shutil, "which", return_value="rclone.exe"),
            patch.object(integrations.subprocess, "run", return_value=output) as run,
        ):
            remotes = integrations.list_remotes()
        self.assertEqual(
            remotes,
            [
                {"name": "cutroom-drive", "type": "drive"},
                {"name": "work-bucket", "type": "s3"},
            ],
        )
        self.assertEqual(run.call_args.args[0][1:], ["listremotes", "--long"])

    def test_no_rclone_means_no_remotes(self):
        with (
            patch.object(integrations.shutil, "which", return_value=None),
            patch.object(integrations, "_find_executable", return_value=None),
        ):
            self.assertEqual(integrations.list_remotes(), [])


if __name__ == "__main__":
    unittest.main()


class CloudMessageTests(unittest.TestCase):
    setUp = CloudUploadTests.setUp
    metadata = CloudUploadTests.metadata
    upload = CloudUploadTests.upload

    """Failures read as one plain sentence; Google's JSON details are dropped."""

    def test_a_drive_quota_refusal_says_what_to_do(self):
        detail = (
            "Attempt 1/3 failed with 1 errors and: couldn't list directory: googleapi: "
            "Error 403: Quota exceeded for quota metric 'Queries' and limit 'Previous quota: "
            "Requests per minute' of service 'drive.googleapis.com' for consumer "
            '\'project_number:202264815644\'.\nDetails:\n[\n  {\n    "@type": "x"\n  }\n]'
        )
        process = FakeProcess(
            [json.dumps({"level": "error", "msg": detail})], returncode=1
        )
        with self.assertRaises(RuntimeError) as caught:
            self.upload(process)
        message = str(caught.exception)
        self.assertIn("Google Drive is limiting requests", message)
        self.assertIn("own client ID", message)
        self.assertNotIn("Details", message)
        self.assertNotIn("project_number", message)

    def test_rate_limits_are_retried_by_rclone_before_giving_up(self):
        process = FakeProcess([])
        self.upload(process)
        argv = process.argv
        self.assertEqual(argv[argv.index("--low-level-retries") + 1], "10")
        self.assertEqual(argv[argv.index("--retries") + 1], "3")


class CloudCheckTests(unittest.TestCase):
    setUp = CloudUploadTests.setUp
    metadata = CloudUploadTests.metadata

    def test_a_failed_check_after_copying_says_the_file_was_sent(self):
        def popen(argv, **options):
            return FakeProcess([])

        failed = subprocess.CalledProcessError(1, ["rclone", "lsjson"])
        with (
            patch.object(integrations.subprocess, "Popen", side_effect=popen),
            patch.object(integrations.subprocess, "run", side_effect=failed) as run,
            self.assertRaises(RuntimeError) as caught,
        ):
            integrations.upload_rclone(self.local, REMOTE, confirmed=True)
        self.assertIn("was sent, but checking it", str(caught.exception))
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index("--low-level-retries") + 1], "10")


class FindRcloneTests(unittest.TestCase):
    def test_a_winget_install_is_found_when_the_path_is_older_than_it(self):
        # Hermes started before rclone was installed keeps the old PATH.
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            exe = (
                home
                / "Microsoft/WinGet/Packages/Rclone.Rclone_Microsoft.Winget.Source_x"
                / "rclone-v1.76.0-windows-amd64/rclone.exe"
            )
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"x")
            with (
                patch.object(integrations.shutil, "which", return_value=None),
                patch.object(integrations.os, "name", "nt"),
                patch.dict(integrations.os.environ, {"LOCALAPPDATA": str(home)}),
            ):
                self.assertEqual(integrations._find_executable("rclone"), str(exe))
                self.assertIsNone(integrations._find_executable("obs64"))
