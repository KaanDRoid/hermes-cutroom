"""Bounded, cancellable native-model worker processes."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .childenv import child_env

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
    "longform",
    "download",
    "publish",
    "calendar",
    "obs",
}


def runtime_python():
    """Interpreter for native-model workers.

    Only user-owned sources are honoured: the ``CUTROOM_PYTHON`` environment
    variable, then the plugin's bundled ``.venv``, then the Hermes interpreter.
    Project settings and agent tools cannot choose an executable.
    """
    root = Path(__file__).resolve().parents[1]
    candidate = os.environ.get("CUTROOM_PYTHON")
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
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        taskkill = Path(system_root) / "System32" / "taskkill.exe"
        subprocess.run(
            [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            env=child_env(python=False),
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


def invoke_worker(operation, arguments, directory, cancelled=None, timeout=1800):
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
    env = child_env(
        OMP_NUM_THREADS=4,
        MKL_NUM_THREADS=4,
        HF_HUB_OFFLINE=1,
        HF_HUB_DISABLE_IMPLICIT_TOKEN=1,
        HF_HUB_DISABLE_TELEMETRY=1,
    )
    started = time.monotonic()
    log_path = directory / "engine.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [runtime_python(), "-m", "cutroom.worker", str(request), str(result)],
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
