"""Run local quality checks with all generated evidence/temp files inside this repo."""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.successes = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.successes.append(test.id())


def main():
    root = Path(__file__).resolve().parents[1]
    temporary = root / "artifacts" / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    for key in ("TMPDIR", "TEMP", "TMP"):
        os.environ[key] = str(temporary)
    tempfile.tempdir = str(temporary)
    evidence = root / "artifacts" / "checks" / uuid.uuid4().hex[:12]
    evidence.mkdir(parents=True)
    os.chdir(root)
    sys.path.insert(0, str(root))
    with (evidence / "python-tests.log").open("w", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            suite = unittest.defaultTestLoader.discover(str(root / "tests"))
            result = unittest.TextTestRunner(
                stream=log,
                verbosity=2,
                resultclass=RecordedResult,
            ).run(suite)
    report = {
        "python": {
            "interpreter": sys.executable,
            "total": result.testsRun,
            "passed": len(result.successes),
            "skipped": [
                {"test": test.id(), "reason": reason} for test, reason in result.skipped
            ],
            "errors": [test.id() for test, _ in result.errors],
            "failures": [test.id() for test, _ in result.failures],
            "expected_failures": [test.id() for test, _ in result.expectedFailures],
            "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
            "ok": result.wasSuccessful(),
        },
    }
    checks = {
        "ruff": [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "cutroom",
            "dashboard",
            "tests",
            "scripts",
        ],
        "desktop": ["node", "--test", "tests/desktop-check.mjs"],
        "whitespace": ["git", "diff", "--check"],
    }
    for name, command in checks.items():
        if not shutil.which(command[0]):
            report[name] = {
                "ok": False,
                "error": "Required executable not found: " + command[0],
            }
            continue
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            (evidence / (name + ".log")).write_text(
                completed.stdout + completed.stderr,
                encoding="utf-8",
            )
            report[name] = {
                "ok": completed.returncode == 0,
                "exit_code": completed.returncode,
            }
        except (OSError, subprocess.TimeoutExpired) as error:
            report[name] = {"ok": False, "error": str(error)}
    (evidence / "summary.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    print("Evidence: " + str(evidence))
    return 0 if all(check["ok"] for check in report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
