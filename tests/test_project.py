import html
import json
import shlex
import tempfile
import unittest
from pathlib import Path

from cutroom.project import approve_plan, load_approved, plan_digest, save_draft


class ApprovalTests(unittest.TestCase):
    def test_review_commands_quote_shell_metacharacters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"unit fixture, not media")
            path = save_draft(
                {
                    "version": 1,
                    "source": str(source),
                    "source_duration": 2,
                    "segments": [{"start": 0, "end": 1}],
                },
                root / "project-$(printf x)-'quoted'",
            )
            document = html.unescape(
                (path.parent / "review.html").read_text(encoding="utf-8")
            )
            self.assertIn("approve " + shlex.quote(str(path)) + " --digest", document)
            self.assertIn("PowerShell", document)

    def test_exact_source_and_plan_must_be_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"local unit fixture, not a video")
            plan = {
                "version": 1,
                "source": str(source),
                "source_duration": 4,
                "segments": [{"start": 0, "end": 2}],
                "status": "draft",
            }
            path = save_draft(plan, root / "project")
            self.assertTrue((path.parent / "review.html").is_file())
            with self.assertRaises(PermissionError):
                load_approved(path)
            digest = plan_digest(json.loads(path.read_text()))
            with self.assertRaises(ValueError):
                approve_plan(path, "incorrect")
            approve_plan(path, digest)
            self.assertEqual(load_approved(path)["segments"], plan["segments"])
            changed = json.loads(path.read_text())
            changed["segments"][0]["end"] = 3
            path.write_text(json.dumps(changed))
            with self.assertRaises(PermissionError):
                load_approved(path)
            path.write_text(
                json.dumps(plan | {"source_sha256": changed["source_sha256"]})
            )
            approve_plan(path, plan_digest(json.loads(path.read_text())))
            source.write_bytes(b"changed unit fixture")
            with self.assertRaises(PermissionError):
                load_approved(path)


if __name__ == "__main__":
    unittest.main()
