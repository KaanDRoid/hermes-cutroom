"""Music without speech gives an empty transcript, not invented words."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom import speech

MAIN_RAW = Path("C:/Users/Kaan/Projects/hermes-cutroom/raw_vids")


def fake_model(folder):
    folder.mkdir()
    for name in ("config.json", "model.bin", "tokenizer.json"):
        (folder / name).write_bytes(b"x")
    return folder


@unittest.skipUnless(
    importlib.util.find_spec("faster_whisper"),
    "Optional faster-whisper is not installed",
)
class NoSpeechTests(unittest.TestCase):
    def test_music_without_speech_never_reaches_the_speech_model(self):
        # Whisper invents words on music ("tense music", "bear" in Russian on a
        # real phone clip). When the voice detector hears no speech at all, the
        # transcript is empty and the model is not even loaded.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            music = root / "music.m4a"
            chord = "+".join(
                f"0.12*sin(2*PI*{f}*t)" for f in (220, 277.18, 329.63, 440)
            )
            beat = "0.2*random(0)*lt(mod(t\\,0.5)\\,0.05)"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"aevalsrc={chord}+{beat}:s=48000:d=8",
                    "-c:a",
                    "aac",
                    str(music),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            model = fake_model(root / "whisper-tiny")
            with patch(
                "faster_whisper.WhisperModel",
                side_effect=AssertionError("No speech: the model must not load"),
            ):
                result = speech.transcribe(music, model)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["words"], [])
        self.assertEqual(result["text"], "")

    def test_words_far_from_any_detected_speech_are_dropped(self):
        # Speech followed by music: a word the model puts in the music, far
        # from any detected speech, is invented and must not reach the edit.
        jfk = MAIN_RAW.parent / "artifacts" / "reference" / "jfk.wav"
        if not jfk.is_file():
            self.skipTest("The official JFK reference audio is not present")
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mixed = root / "speech-then-music.m4a"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-i",
                    str(jfk),
                    "-f",
                    "lavfi",
                    "-i",
                    "aevalsrc=0.2*sin(2*PI*220*t)+0.2*sin(2*PI*330*t):s=16000:d=8",
                    "-filter_complex",
                    "[0:a]aresample=16000,aformat=channel_layouts=mono[a];"
                    "[1:a]aformat=channel_layouts=mono[b];[a][b]concat=n=2:v=0:a=1",
                    "-c:a",
                    "aac",
                    str(mixed),
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            model = fake_model(root / "whisper-tiny")

            def word(text, start, end):
                return SimpleNamespace(
                    word=f" {text}", start=start, end=end, probability=0.9
                )

            segments = [
                SimpleNamespace(
                    text=" ask not",
                    words=[word("ask", 3.0, 3.3), word("not", 3.3, 3.6)],
                ),
                SimpleNamespace(text=" bear", words=[word("bear", 15.0, 15.4)]),
            ]
            fake = SimpleNamespace(
                transcribe=lambda *a, **k: (
                    iter(segments),
                    SimpleNamespace(language="en"),
                )
            )
            with patch("faster_whisper.WhisperModel", return_value=fake):
                result = speech.transcribe(mixed, model)
        self.assertEqual([w["text"] for w in result["words"]], ["ask", "not"])
        self.assertEqual([w["id"] for w in result["words"]], [0, 1])
        self.assertNotIn("bear", result["text"])

    def test_the_real_phone_clip_with_only_music_has_no_words(self):
        source = MAIN_RAW / "WhatsApp Video 2026-11-12 at 11.14.38.mp4"
        model = MAIN_RAW.parent / "models" / "whisper-tiny"
        if not source.is_file() or not (model / "model.bin").is_file():
            self.skipTest("The consented phone clip or local model is not present")
        result = speech.transcribe(source, model)
        self.assertEqual(result["words"], [])


if __name__ == "__main__":
    unittest.main()
