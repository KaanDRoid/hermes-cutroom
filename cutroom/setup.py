"""Explicit model acquisition and read-only, dependency-light health checks.

Pinned assets were verified against known-good local copies: the MediaPipe
files match Google's published size and MD5, and the speech files match the
Hugging Face revision recorded below.
"""

import hashlib
import os
import tempfile
from pathlib import Path

SPEECH_REVISION = "d90ca5fe260221311c53c58e660288d3deb8d356"
GOOGLE = "https://storage.googleapis.com/mediapipe-models/"
HF = f"https://huggingface.co/Systran/faster-whisper-tiny/resolve/{SPEECH_REVISION}/"
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
SIZE_ERROR = "Download exceeds the 200 MB limit"
TIMEOUT_SECONDS = 60
CHUNK = 1024 * 1024
PACKAGES = ("faster_whisper", "ctranslate2", "mediapipe", "cv2", "numpy")
MODEL_ASSETS = {
    "face": [
        {
            "path": "face_landmarker.task",
            "url": GOOGLE
            + "face_landmarker/face_landmarker/float16/1/face_landmarker.task",
            "sha256": "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
        }
    ],
    "person": [
        {
            "path": "selfie_segmenter.tflite",
            "url": GOOGLE
            + "image_segmenter/selfie_segmenter/float16/1/selfie_segmenter.tflite",
            "sha256": "191ac9529ae506ee0beefa6b2c945a172dab9d07d1e802a290a4e4038226658b",
        }
    ],
    "speech": [
        {"path": "whisper-tiny/" + name, "url": HF + name, "sha256": digest}
        for name, digest in (
            (
                "config.json",
                "a73a28cdfe1c43ccc7202fa333d1f89c202477271407ae9a7f19afa52039cac8",
            ),
            (
                "model.bin",
                "dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1",
            ),
            (
                "tokenizer.json",
                "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab",
            ),
            (
                "vocabulary.txt",
                "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913",
            ),
        )
    ],
}


def _reject_network(value):
    text = str(value).replace("\\", "/")
    if not text.strip() or text.startswith("//") or "://" in text:
        raise ValueError(
            "Use an explicit local directory, not a URL or UNC/network path"
        )
    if os.name == "nt":
        import ctypes

        anchor = Path(text).anchor
        if anchor and ctypes.windll.kernel32.GetDriveTypeW(anchor) == 4:
            raise ValueError("Mapped network drives are not supported")


def _directory(directory):
    if not isinstance(directory, (str, os.PathLike)):
        raise TypeError("directory must be a local path")
    _reject_network(directory)
    result = Path(directory).expanduser().resolve()
    _reject_network(result)
    if result.exists() and not result.is_dir():
        raise ValueError("directory must be a directory")
    return result


def _selected(models):
    if not isinstance(models, str):
        raise TypeError("models must be comma-separated keys: face,person,speech")
    keys = models.split(",")
    if len(set(keys)) != len(keys) or any(key not in MODEL_ASSETS for key in keys):
        raise ValueError("models must contain unique keys from face,person,speech")
    return keys


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def _destination(root, asset):
    destination = (root / asset["path"]).resolve()
    if not destination.is_relative_to(root):
        raise ValueError("Asset path escapes the destination directory")
    return destination


def _fetch(asset, destination):
    """Stream one asset to a sibling temp file, verify it, then install it."""
    import urllib.request
    from urllib.parse import urlsplit

    class HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urlsplit(newurl).scheme.lower() != "https":
                raise ValueError("Model source redirected away from HTTPS")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    url = asset["url"]
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS model sources are allowed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=destination.parent, prefix="." + destination.name + ".", suffix=".part"
    )
    try:
        digest, received = hashlib.sha256(), 0
        with os.fdopen(handle, "wb") as stream:
            opener = urllib.request.build_opener(HTTPSOnlyRedirectHandler())
            with opener.open(url, timeout=TIMEOUT_SECONDS) as response:
                if not str(response.geturl()).startswith("https://"):
                    raise ValueError("Model source redirected away from HTTPS")
                declared = int(response.headers.get("Content-Length") or 0)
                if declared > MAX_DOWNLOAD_BYTES:
                    raise ValueError(SIZE_ERROR)
                while block := response.read(CHUNK):
                    received += len(block)
                    if received > MAX_DOWNLOAD_BYTES:
                        raise ValueError(SIZE_ERROR)
                    digest.update(block)
                    stream.write(block)
            if declared and received != declared:
                raise ValueError("Incomplete download")
        if digest.hexdigest() != asset["sha256"]:
            raise ValueError("Downloaded file sha256 does not match the pinned value")
        if os.name == "nt":
            os.rename(temporary, destination)
        else:
            os.link(temporary, destination)
            os.unlink(temporary)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _acquire(root, asset):
    entry = dict(asset)
    try:
        destination = _destination(root, asset)
        entry["destination"] = str(destination)
        if destination.exists():
            if destination.is_file() and _sha256(destination) == asset["sha256"]:
                entry["status"] = "present"
            else:
                entry["status"] = "error"
                entry["error"] = "Existing file sha256 does not match; left untouched"
            return entry
        _fetch(asset, destination)
        entry["status"] = "downloaded"
    except Exception as error:
        entry["status"] = "error"
        entry["error"] = f"{type(error).__name__}: {error}"
    return entry


def setup_models(directory, models="face,person,speech", confirm_downloads=False):
    """Return a side-effect-free plan unless downloads are explicitly confirmed."""
    if type(confirm_downloads) is not bool:
        raise TypeError("confirm_downloads must be a boolean")
    keys = _selected(models)
    root = _directory(directory)
    if not confirm_downloads:
        return {
            "status": "planned",
            "directory": str(root),
            "confirmed": False,
            "models": {
                key: {
                    "files": [
                        dict(asset, destination=str(root / asset["path"]))
                        for asset in MODEL_ASSETS[key]
                    ]
                }
                for key in keys
            },
            "instructions": "Review URLs and hashes; rerun setup-models with "
            "--confirm-downloads to acquire these files. No packages are installed.",
        }
    results = {
        key: {"files": [_acquire(root, asset) for asset in MODEL_ASSETS[key]]}
        for key in keys
    }
    failed = any(
        entry["status"] == "error"
        for model in results.values()
        for entry in model["files"]
    )
    return {
        "status": "failed" if failed else "complete",
        "directory": str(root),
        "confirmed": True,
        "models": results,
    }


def _tool(name):
    import shutil
    import subprocess

    path = shutil.which(name)
    if not path:
        return {"path": None, "version": None}
    try:
        completed = subprocess.run(
            [path, "-version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        lines = (completed.stdout or "").splitlines()
        version = lines[0].strip() if lines else None
    except Exception as error:
        return {"path": path, "version": None, "error": str(error)}
    return {"path": path, "version": version}


def _package(name):
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _runtime():
    from . import runtime

    try:
        return {"path": runtime.runtime_python()}
    except Exception as error:
        return {"path": None, "error": f"{type(error).__name__}: {error}"}


def _model_status(root, asset):
    path = root / asset["path"]
    exists = path.is_file()
    return {
        "path": asset["path"],
        "destination": str(path),
        "exists": exists,
        "size": path.stat().st_size if exists else None,
        "sha256_match": _sha256(path) == asset["sha256"] if exists else None,
    }


def doctor(models_dir=None):
    """Report local prerequisites without installing, importing or fetching."""
    if models_dir is None:
        models_dir = Path(__file__).resolve().parents[1] / "models"
    root = _directory(models_dir)
    models = {}
    for key, assets in MODEL_ASSETS.items():
        files = [_model_status(root, asset) for asset in assets]
        models[key] = {
            "files": files,
            "ready": all(entry["sha256_match"] for entry in files),
        }
    return {
        "ffmpeg": _tool("ffmpeg"),
        "ffprobe": _tool("ffprobe"),
        "runtime_python": _runtime(),
        "packages": {name: _package(name) for name in PACKAGES},
        "models_dir": str(root),
        "models": models,
    }
