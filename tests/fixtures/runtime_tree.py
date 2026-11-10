"""A bounded real worker subtree for runtime cancellation tests, not an engine action."""

import json
import subprocess
import sys
from pathlib import Path


def main():
    ready = Path(sys.argv[1])
    child = subprocess.Popen(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=32x32:rate=5:duration=60",
            "-f",
            "null",
            "-",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        temporary = ready.with_suffix(".tmp")
        temporary.write_text(json.dumps({"child_pid": child.pid}), encoding="utf-8")
        temporary.replace(ready)
        return child.wait(timeout=70)
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
