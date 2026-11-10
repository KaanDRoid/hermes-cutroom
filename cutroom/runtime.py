"""Bounded, cancellable native-model worker processes."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

OPERATIONS = {
    "inspect",
    "transcribe",
    "silence",
    "vision",
    "segment",
    "storyboard",
    "preview",
    "final",
    "cover",
    "qa",
    "download",
    "publish",
    "calendar",
    "obs",
}


def runtime_python(configured=None):
    root = Path(__file__).resolve().parents[1]
    candidate = configured or os.environ.get("CUTROOM_PYTHON")
    if candidate:
        path = Path(candidate).expanduser().resolve(strict=True)
        if not path.is_file() or not path.name.lower().startswith("python"):
            raise ValueError("Runtime must be a local Python executable")
        return str(path)
    local = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(local if local.is_file() else Path(sys.executable))


def _terminate(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def invoke_worker(
    operation, arguments, directory, python=None, cancelled=None, timeout=1800
):
    if operation not in OPERATIONS:
        raise ValueError("Unsupported worker operation")
    if cancelled and cancelled():
        raise InterruptedError("Job cancelled")
    directory = Path(directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=False)
    request, result = directory / "request.json", directory / "result.json"
    request.write_text(
        json.dumps({"operation": operation, "arguments": arguments}, allow_nan=False),
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[1]
    env = dict(
        os.environ,
        OMP_NUM_THREADS="4",
        MKL_NUM_THREADS="4",
        HF_HUB_OFFLINE="1",
        HF_HUB_DISABLE_IMPLICIT_TOKEN="1",
    )
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    started = time.monotonic()
    log_path = directory / "engine.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [runtime_python(python), "-m", "cutroom.worker", str(request), str(result)],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            **(
                {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                if os.name == "nt"
                else {"start_new_session": True}
            ),
        )
        try:
            while process.poll() is None:
                if cancelled and cancelled():
                    raise InterruptedError("Job cancelled")
                if time.monotonic() - started > timeout:
                    raise TimeoutError("Worker exceeded its execution budget")
                if log_path.stat().st_size > 20_000_000:
                    raise RuntimeError("Worker log exceeded 20 MB")
                time.sleep(0.1)
            if not result.is_file():
                raise RuntimeError("Worker ended without a result; inspect engine.log")
            if result.stat().st_size > 32_000_000:
                raise ValueError("Worker result exceeds 32 MB")
            envelope = json.loads(result.read_text(encoding="utf-8"))
            if not envelope.get("ok"):
                raise RuntimeError(
                    envelope.get("type", "WorkerError")
                    + ": "
                    + envelope.get("error", "Unknown failure")
                )
            if process.returncode != 0:
                raise RuntimeError("Worker process failed despite returning a result")
            return envelope["result"]
        finally:
            _terminate(process)
