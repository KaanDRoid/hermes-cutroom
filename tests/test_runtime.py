"""The native dependency runtime stays outside the Hermes interpreter."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from process_helpers import process_is_running

from cutroom.runtime import _terminate, invoke_worker


class RuntimeTests(unittest.TestCase):
    def test_real_running_cancellation_terminates_only_owned_subtree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ready = root / "ready.json"
            original_popen = subprocess.Popen
            process_options = (
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt"
                else {"start_new_session": True}
            )
            sentinel = original_popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **process_options,
            )
            self.addCleanup(_terminate, sentinel)
            workers = []

            def launch(arguments, **kwargs):
                if "cutroom.worker" not in arguments:
                    return original_popen(arguments, **kwargs)
                fixture = Path(__file__).parent / "fixtures" / "runtime_tree.py"
                worker = original_popen(
                    [sys.executable, str(fixture), str(ready)], **kwargs
                )
                workers.append(worker)
                self.addCleanup(_terminate, worker)
                return worker

            observed = {}

            def cancelled():
                if not ready.is_file():
                    return False
                observed.update(json.loads(ready.read_text(encoding="utf-8")))
                self.assertTrue(process_is_running(observed["child_pid"]))
                return True

            with patch("cutroom.runtime.subprocess.Popen", side_effect=launch):
                with self.assertRaises(InterruptedError):
                    invoke_worker(
                        "silence", {}, root / "engine", cancelled=cancelled, timeout=15
                    )
            self.assertEqual(len(workers), 1)
            self.assertIsNotNone(workers[0].poll())
            deadline = time.monotonic() + 5
            while (
                process_is_running(observed["child_pid"])
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            self.assertFalse(process_is_running(observed["child_pid"]))
            self.assertIsNone(
                sentinel.poll(), "Cancellation killed an unrelated process"
            )
            self.assertFalse((root / "engine" / "result.json").exists())

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
