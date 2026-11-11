"""Offline acceptance-harness safety contracts, not human consent evidence."""

import contextlib
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import acceptance


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.studio = Mock(root=self.root / "workspace")
        self.project = {
            "id": "project-one",
            "revision": 3,
            "source": str(self.root / "source.mp4"),
            "transcript": {
                "words": [{"text": "hello"}],
                "fillers": [],
                "text": "hello",
            },
            "segments": [],
            "story": {"hooks": [{"text": "hello"}]},
            "artifacts": {"preview": {}},
        }
        self.studio.create.return_value = self.project
        self.studio.update.return_value = self.project
        self.studio.get.return_value = self.project
        self.studio.review.return_value = {
            "digest": "current-digest",
            "project": self.project,
        }
        self.studio.submit.side_effect = lambda pid, action, options: {
            "id": action,
            "action": action,
        }
        self.studio.job.side_effect = lambda job_id: {
            "status": "completed",
            "error": None,
            "result": {"passed": True, "checks": []},
        }
        self.studio.artifact.side_effect = lambda pid, kind: self.root / (kind + ".mp4")

    def test_custom_audio_stops_at_preview_without_approval_or_final(self):
        audio = self.root / "private-recording.wav"
        with wave.open(str(audio), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(8000)
            stream.writeframes(b"\0\0" * 800)
        output = self.root / "run"
        printed = io.StringIO()
        with (
            patch.object(acceptance, "Studio", return_value=self.studio),
            patch.object(acceptance.subprocess, "run"),
            patch.object(
                acceptance,
                "probe",
                return_value={
                    "duration": 1,
                    "width": 100,
                    "height": 100,
                    "has_audio": True,
                },
            ),
            contextlib.redirect_stdout(printed),
        ):
            result = acceptance.main(["--audio", str(audio), "--output", str(output)])
        self.studio.approve.assert_not_called()
        actions = [call.args[1] for call in self.studio.submit.call_args_list]
        self.assertEqual(actions[-1], "preview")
        self.assertNotIn("final", actions)
        self.assertEqual(result, 0)
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "awaiting_human_review")
        self.assertEqual(summary["workspace"], str(self.studio.root))
        self.assertEqual(summary["project_id"], self.project["id"])
        self.assertEqual(summary["digest"], "current-digest")
        self.assertIn("Desktop", summary["instructions"])
        self.assertIn("REST", summary["instructions"])
        self.assertIn("current-digest", printed.getvalue())

    def test_resume_consumes_existing_current_approval_without_granting_it(self):
        self.project["approval"] = {"digest": "current-digest", "revision": 3}
        output = self.root / "resumed"
        with (
            patch.object(acceptance, "Studio", return_value=self.studio),
            patch.object(acceptance.subprocess, "run") as media_run,
            patch.object(
                acceptance,
                "probe",
                return_value={
                    "duration": 1,
                    "width": 100,
                    "height": 100,
                    "has_audio": True,
                },
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = acceptance.main(
                [
                    "--workspace",
                    str(self.studio.root),
                    "--project-id",
                    self.project["id"],
                    "--output",
                    str(output),
                ]
            )
        self.assertEqual(result, 0)
        self.studio.approve.assert_not_called()
        self.studio.create.assert_not_called()
        self.studio.update.assert_not_called()
        media_run.assert_not_called()
        self.assertEqual(
            [call.args[1] for call in self.studio.submit.call_args_list],
            ["final", "cover", "qa"],
        )
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertTrue(summary["quality_passed"])
        self.assertEqual(summary["project_id"], self.project["id"])

    def test_resume_rejects_absent_or_stale_approval_before_submitting(self):
        for index, approval in enumerate(
            (
                None,
                {},
                {"digest": "old", "revision": 3},
                {"digest": "current-digest", "revision": 2},
            )
        ):
            with self.subTest(approval=approval):
                self.studio.reset_mock()
                self.project["approval"] = approval
                with (
                    patch.object(acceptance, "Studio", return_value=self.studio),
                    patch.object(acceptance.subprocess, "run") as media_run,
                    patch.object(
                        acceptance,
                        "probe",
                        return_value={
                            "duration": 1,
                            "width": 100,
                            "height": 100,
                            "has_audio": True,
                        },
                    ),
                    contextlib.redirect_stdout(io.StringIO()),
                    self.assertRaisesRegex(PermissionError, "human approval"),
                ):
                    acceptance.main(
                        [
                            "--workspace",
                            str(self.studio.root),
                            "--project-id",
                            self.project["id"],
                            "--output",
                            str(self.root / f"rejected-{index}"),
                        ]
                    )
                self.studio.approve.assert_not_called()
                self.studio.submit.assert_not_called()
                self.studio.update.assert_not_called()
                media_run.assert_not_called()

    def test_resume_requires_both_identifiers_before_any_side_effect(self):
        for index, flags in enumerate(
            (
                ["--workspace", str(self.studio.root)],
                ["--project-id", self.project["id"]],
            )
        ):
            output = self.root / f"invalid-{index}"
            with (
                self.subTest(flags=flags),
                patch.object(acceptance, "Studio") as factory,
                patch.object(acceptance, "prepare") as prepare,
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                acceptance.main(flags + ["--output", str(output)])
            self.assertEqual(raised.exception.code, 2)
            factory.assert_not_called()
            prepare.assert_not_called()
            self.assertFalse(output.exists())

    def test_tool_descriptions_put_approval_before_submission_and_at_completion(self):
        from cutroom.studio_tools import definitions

        for definition in definitions():
            description = definition["description"]
            self.assertIn("before final job submission", description)
            self.assertIn("checked again on completion", description)
            self.assertIn("local REST", description)
            self.assertNotIn("stays pending until", description)


if __name__ == "__main__":
    unittest.main()
