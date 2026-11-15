"""Workspace locks report a busy workspace instead of failing on a new lock file."""

import os
import tempfile
import unittest
from pathlib import Path

from cutroom.studio import Studio


@unittest.skipUnless(os.name == "nt", "byte-range locks block writes only on Windows")
class NewLockFileTests(unittest.TestCase):
    def test_a_lock_held_on_a_new_empty_file_means_busy(self):
        # Two callers can open a brand-new lock file together. The first one
        # may lock byte 0 before anything is written; the second one must then
        # wait and report a busy workspace, not crash writing to that byte.
        import msvcrt

        with tempfile.TemporaryDirectory() as temporary:
            studio = Studio(Path(temporary) / "workspace")
            path = studio.root / "race.lock"
            with path.open("a+b") as holder:
                msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
                try:
                    with self.assertRaises(TimeoutError):
                        with studio._lock("race", timeout=1):
                            pass
                finally:
                    holder.seek(0)
                    msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, 1)
            with studio._lock("race", timeout=1):
                pass


if __name__ == "__main__":
    unittest.main()
