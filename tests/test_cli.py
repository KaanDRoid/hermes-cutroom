import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cutroom.project import save_draft


class CliTests(unittest.TestCase):
    def test_review_and_explicit_approval_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"unit fixture, not video")
            path = save_draft(
                {
                    "version": 1,
                    "source": str(source),
                    "source_duration": 2,
                    "segments": [{"start": 0, "end": 1}],
                },
                root / "project",
            )

            def run(*args):
                return subprocess.run(
                    [sys.executable, "-m", "cutroom", *map(str, args)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )

            result = run("review", path)
            self.assertEqual(result.returncode, 0, result.stderr)
            review = json.loads(result.stdout)
            bad = run("approve", path, "--digest", "wrong")
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse((path.parent / "approval.json").exists())
            good = run("approve", path, "--digest", review["digest"])
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertTrue((path.parent / "approval.json").is_file())


if __name__ == "__main__":
    unittest.main()
