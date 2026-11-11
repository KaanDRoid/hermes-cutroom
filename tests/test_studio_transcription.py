"""Focused transcription-routing checks; contract model files are NOT real models."""

import copy
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.job_worker import main as supervise
from cutroom.studio import Studio
from cutroom.worker import execute


def transcript(words=None):
    words = (
        words
        if words is not None
        else [
            dict(id=0, start=0.5, end=1.5, text="First", probability=0.9),
            dict(id=1, start=1.5, end=1.7, text="um", probability=0.9),
            dict(id=2, start=1.7, end=3.5, text="last", probability=0.9),
        ]
    )
    return dict(
        language="en",
        words=words,
        text=" ".join(w["text"] for w in words),
        engine="contract-fixture",
        status="ok",
    )


class TranscriptionJobsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "contract-source.mp4"
        self.source.write_bytes(b"Contract fixture, NOT media")
        self.model = self.root / "contract-model"
        self.model.mkdir()
        for name in ("config.json", "model.bin", "tokenizer.json"):
            (self.model / name).write_bytes(b"Contract fixture, NOT a model")
        self.studio = Studio(self.root / "workspace")
        with patch(
            "cutroom.studio.probe",
            return_value={
                "duration": 4.0,
                "width": 64,
                "height": 64,
                "has_audio": True,
            },
        ):
            self.project = self.studio.create(self.source)
        self.project = self.studio.update(
            self.project["id"],
            {"settings": {"whisper_model": str(self.model)}},
            1,
        )

    def run_result(self, result, mutate=None):
        # Use the real supervisor/application boundary, with inference and launch mocked.
        with (
            patch("subprocess.Popen"),
            patch.dict("cutroom.studio._CHILD_PROCESSES", clear=True),
        ):
            job = self.studio.submit(
                self.project["id"], "transcribe", {"language": "en"}
            )

        def perform(instance, record):
            if mutate:
                mutate(record)
            return copy.deepcopy(result)

        with patch.object(Studio, "_perform_job", perform):
            supervise([str(self.studio.root), job["id"]])
        return self.studio.job(job["id"])

    def test_worker_dispatches_transcription(self):
        arguments = {
            "source": str(self.source),
            "model_path": str(self.model),
            "language": "en",
        }
        with patch("cutroom.speech.transcribe", return_value=transcript()) as run:
            self.assertEqual(execute("transcribe", arguments), transcript())
        run.assert_called_once_with(**arguments)

    def test_options_and_missing_model_fail_before_launch(self):
        for options in (
            {"source": "other.mp4"},
            {"model_path": str(self.model)},
            {"language": True},
            {"language": ""},
            {"language": "en us"},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.studio.submit(self.project["id"], "transcribe", options)
        (self.model / "model.bin").unlink()
        with self.assertRaises(FileNotFoundError):
            self.studio.submit(self.project["id"], "transcribe")
        self.assertEqual(self.studio.jobs(), [])

    def test_success_persists_validated_transcript_fillers_and_new_revision(self):
        self.project = self.studio.update(
            self.project["id"],
            {
                "segments": [{"start": 0.75, "end": 3.0}],
                "gaze_exclusions": [{"start": 2.8, "end": 3.0}],
            },
            self.project["revision"],
        )
        reviewed = self.studio.review(self.project["id"])
        self.studio.approve(self.project["id"], reviewed["digest"])
        job = self.run_result(transcript())
        self.assertEqual(job["status"], "completed", job)
        project = Studio(self.studio.root).get(self.project["id"])
        self.assertEqual(project["revision"], self.project["revision"] + 1)
        self.assertEqual(job["applied_revision"], project["revision"])
        self.assertEqual(project["segments"], self.project["segments"])
        self.assertNotIn("approval", project)
        self.assertEqual(project["status"], "draft")
        self.assertEqual(project["transcript"]["words"], transcript()["words"])
        self.assertEqual(project["transcript"]["fillers"][0]["word_ids"], [1])
        edited = self.studio.update(
            project["id"], {"excluded_word_ids": [1]}, project["revision"]
        )
        self.assertEqual(
            edited["segments"],
            [
                {"start": 0.75, "end": 1.5},
                {"start": 1.7, "end": 2.8},
            ],
        )
        request = self.studio._job_path(job["id"]).parent / "snapshot.json"
        self.assertEqual(
            json.loads(request.read_text())["revision"], self.project["revision"]
        )

    def test_replacement_preserves_word_cuts_without_reusing_old_ids(self):
        for via_job in (True, False):
            with self.subTest(via_job=via_job):
                self.project = self.studio.update(
                    self.project["id"],
                    {
                        "transcript": transcript(),
                        "segments": [{"start": 0.5, "end": 3.5}],
                        "excluded_word_ids": [1],
                        "gaze_exclusions": [{"start": 3.2, "end": 3.5}],
                    },
                    self.studio.get(self.project["id"])["revision"],
                )
                seeded = copy.deepcopy(self.project)
                seeded["story"] = {"hooks": [{"text": "old quote"}]}
                seeded["selected_hook"] = 0
                seeded["artifacts"]["captions_srt"] = "old-captions.srt"
                self.studio._write(seeded)
                replacement = transcript(
                    [
                        dict(id=0, start=0.5, end=1.4, text="New", probability=0.9),
                        dict(id=1, start=2.0, end=3.1, text="words", probability=0.9),
                    ]
                )
                if via_job:
                    job = self.run_result(replacement)
                    self.assertEqual(job["status"], "completed", job)
                    self.assertTrue(job["transcript_update"]["preserved_word_cuts"])
                else:
                    self.studio.update(
                        self.project["id"],
                        {"transcript": replacement},
                        self.project["revision"],
                    )
                current = self.studio.get(self.project["id"])
                self.assertEqual(current["excluded_word_ids"], [])
                self.assertEqual(
                    current["base_segments"],
                    [
                        {"start": 0.5, "end": 1.5},
                        {"start": 1.7, "end": 3.5},
                    ],
                )
                self.assertEqual(current["segments"][-1]["end"], 3.2)
                self.assertIsNone(current["story"])
                self.assertNotIn("selected_hook", current)
                self.assertNotIn("captions_srt", current["artifacts"])
                current = self.studio.update(
                    current["id"], {"gaze_exclusions": []}, current["revision"]
                )
                self.assertEqual(current["segments"][-1]["end"], 3.5)

    def test_invalid_results_changed_models_and_cancellation_do_not_publish(self):
        for case in ("invalid", "model", "cancel", "revision"):
            with self.subTest(case=case):
                before = self.studio.get(self.project["id"])
                result = transcript()
                if case == "invalid":
                    result["words"][0]["end"] = 99

                def mutate(job):
                    if case == "model":
                        (self.model / "model.bin").write_bytes(
                            b"Changed contract model"
                        )
                    elif case == "cancel":
                        self.studio.cancel(job["id"])
                    elif case == "revision":
                        self.studio.update(
                            self.project["id"],
                            {"brief": "New edit"},
                            before["revision"],
                        )

                job = self.run_result(result, mutate)
                self.assertEqual(
                    job["status"], "cancelled" if case == "cancel" else "failed", job
                )
                self.assertIsNone(job["result"])
                current = self.studio.get(self.project["id"])
                self.assertEqual(current["transcript"], before["transcript"])
                self.assertEqual(current["segments"], before["segments"])

    def test_real_no_audio_background_job_does_not_require_a_model(self):
        source = self.root / "synthetic-no-audio.mp4"
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
                "testsrc2=size=64x64:rate=10:duration=0.4",
                "-c:v",
                "libx264",
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=15,
        )
        project = self.studio.create(source)
        job = self.studio.submit(project["id"], "transcribe")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = self.studio.job(job["id"])
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.05)
        self.assertEqual(job["status"], "completed", job)
        current = self.studio.get(project["id"])
        self.assertEqual(current["transcript"]["status"], "no_audio")
        self.assertEqual(current["transcript"]["words"], [])
        self.assertEqual(current["transcript"]["fillers"], [])
        self.assertEqual(current["segments"], project["segments"])


if __name__ == "__main__":
    unittest.main()
