"""Model files placed in a models folder are found without typing a path."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import setup
from cutroom.studio import Studio


def whisper(folder):
    folder.mkdir(parents=True)
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (folder / name).write_bytes(b"x")
    return folder


class FindModelTests(unittest.TestCase):
    def test_the_most_accurate_speech_model_present_is_chosen(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertIsNone(setup.find_model("whisper_model", [root]))
            whisper(root / "whisper-tiny")
            self.assertEqual(
                setup.find_model("whisper_model", [root]), root / "whisper-tiny"
            )
            whisper(root / "faster-whisper-small")
            self.assertEqual(
                setup.find_model("whisper_model", [root]),
                root / "faster-whisper-small",
            )

    def test_incomplete_folders_and_missing_roots_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "whisper-small").mkdir()
            (root / "whisper-small" / "config.json").write_bytes(b"x")
            self.assertIsNone(
                setup.find_model("whisper_model", [root / "missing", root])
            )

    def test_face_and_background_models_are_single_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "face_landmarker.task").write_bytes(b"x")
            (root / "selfie_segmenter.tflite").write_bytes(b"x")
            self.assertEqual(
                setup.find_model("face_model", [root]), root / "face_landmarker.task"
            )
            self.assertEqual(
                setup.find_model("segmentation_model", [root]),
                root / "selfie_segmenter.tflite",
            )


class StudioModelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / "source.mp4"
        source.write_bytes(b"unit source fixture")
        self.studio = Studio(self.root / "workspace")
        with patch(
            "cutroom.studio.probe",
            return_value={"duration": 4.0, "has_audio": True},
        ):
            self.project = self.studio.create(source)

    def test_a_project_without_a_model_path_uses_the_workspace_models_folder(self):
        folder = whisper(self.studio.root / "models" / "whisper-small")
        self.assertEqual(
            self.studio._model(self.project["settings"], "whisper_model"), str(folder)
        )
        assets = self.studio._transcription_assets(self.project)
        self.assertIn(str(folder / "model.bin"), assets)

    def test_a_chosen_path_wins_over_the_models_folder(self):
        whisper(self.studio.root / "models" / "whisper-small")
        chosen = whisper(self.root / "mine")
        settings = {**self.project["settings"], "whisper_model": str(chosen)}
        self.assertEqual(self.studio._model(settings, "whisper_model"), str(chosen))

    def test_vision_is_accepted_with_a_face_model_in_the_models_folder(self):
        (self.studio.root / "models").mkdir()
        (self.studio.root / "models" / "face_landmarker.task").write_bytes(b"x")
        with patch("subprocess.Popen"):
            try:
                self.studio.submit(self.project["id"], "vision")
            except ValueError as error:
                self.fail(f"vision refused: {error}")

    def test_without_any_model_the_error_says_where_to_put_one(self):
        with self.assertRaises(ValueError) as caught:
            self.studio.submit(self.project["id"], "transcribe")
        message = str(caught.exception)
        self.assertIn("speech model", message.lower())
        self.assertIn(str(self.studio.root / "models"), message)


if __name__ == "__main__":
    unittest.main()
