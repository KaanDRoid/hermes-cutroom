"""The native dependency runtime stays outside the Hermes interpreter."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cutroom.runtime import invoke_worker


class RuntimeTests(unittest.TestCase):
    def test_real_isolated_inspection_and_unknown_action_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "synthetic.mp4"
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
                capture_output=True,
                check=True,
                timeout=15,
            )
            result = invoke_worker("inspect", {"source": str(source)}, root / "work")
            self.assertEqual(result["width"], 64)
            with patch(
                "cutroom.runtime.subprocess.Popen",
                side_effect=AssertionError("must reject before launch"),
            ):
                with self.assertRaises(ValueError):
                    invoke_worker("__import__", {}, root / "unknown")
                with self.assertRaises(InterruptedError):
                    invoke_worker(
                        "inspect",
                        {"source": str(source)},
                        root / "cancelled",
                        cancelled=lambda: True,
                    )


if __name__ == "__main__":
    unittest.main()
