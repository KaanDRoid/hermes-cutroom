"""Regression checks for waiting on process exit before deleting worker logs."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from process_helpers import process_is_running, wait_for_process_exit


class ProcessLifetimeTests(unittest.TestCase):
    def test_live_worker_times_out_then_releases_its_log_before_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "worker.log"
            # A stdin barrier keeps the log open independently of machine speed.
            code = (
                "import pathlib,sys; "
                "log=pathlib.Path(sys.argv[1]).open('w'); "
                "print('ready',flush=True); "
                "sys.stdin.readline(); "
                "log.close()"
            )
            worker = subprocess.Popen(
                [sys.executable, "-c", code, str(log)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            try:
                self.assertEqual(worker.stdout.readline().strip(), "ready")
                self.assertTrue(process_is_running(worker.pid))
                with self.assertRaises(TimeoutError):
                    wait_for_process_exit(worker.pid, timeout=0.05)
                self.assertIsNone(worker.poll(), "A timeout must not kill the worker")
                worker.stdin.close()
                wait_for_process_exit(worker.pid, timeout=5)
                self.assertEqual(worker.wait(timeout=5), 0)
                self.assertFalse(process_is_running(worker.pid))
                log.unlink()  # Windows rejects this if the child still owns the log.
                self.assertFalse(log.exists())
            finally:
                if not worker.stdin.closed:
                    worker.stdin.close()
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
                worker.stdout.close()

    def test_wait_does_not_return_at_the_first_live_observation(self):
        with (
            patch(
                "process_helpers.process_is_running", side_effect=[True, True, False]
            ) as running,
            patch("process_helpers.time.sleep") as sleep,
        ):
            wait_for_process_exit(123, timeout=5)
        self.assertEqual(running.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_query_errors_are_not_mistaken_for_worker_exit(self):
        with patch(
            "process_helpers.process_is_running", side_effect=PermissionError("denied")
        ):
            with self.assertRaises(PermissionError):
                wait_for_process_exit(123, timeout=5)


if __name__ == "__main__":
    unittest.main()
