"""Durable local studio projects and reviewed editing workflows."""

import copy
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .media import _local_path, probe
from .project import file_digest

_CHILD_PROCESSES = {}


def _load_json(path):
    deadline = time.monotonic() + 1.0
    while True:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


def _replace_file(temporary, target):
    deadline = time.monotonic() + 1.0
    while True:
        try:
            temporary.replace(target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.02)


class Studio:
    def __init__(self, root, runner=None):
        self.root = _local_path(Path(root).expanduser(), must_exist=False)
        self.root.mkdir(parents=True, exist_ok=True)
        self.runner = runner

    def _directory(self, project_id):
        if not isinstance(project_id, str) or not re.fullmatch(
            r"[a-f0-9]{32}", project_id
        ):
            raise ValueError("Invalid project id")
        return self.root / "projects" / project_id

    def _write(self, project):
        path = self._directory(project["id"]) / "studio.json"
        temporary = path.with_name("." + uuid.uuid4().hex + ".json")
        try:
            temporary.write_text(
                json.dumps(project, indent=2, allow_nan=False), encoding="utf-8"
            )
            _replace_file(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def create(self, source, name=None):
        source = _local_path(source)
        digest = file_digest(source)
        info = probe(source)
        if digest != file_digest(source):
            raise PermissionError("Source changed during import")
        project = {
            "version": 2,
            "id": uuid.uuid4().hex,
            "name": name or source.stem,
            "source": str(source),
            "source_sha256": digest,
            "source_info": info,
            "revision": 1,
            "status": "draft",
            "settings": {"aspect": "source", "title": "", "brand": {}},
            "segments": [{"start": 0.0, "end": info["duration"]}],
            "base_segments": [{"start": 0.0, "end": info["duration"]}],
            "excluded_word_ids": [],
            "gaze_exclusions": [],
            "brief": "",
            "voice": "neutral",
            "transcript": None,
            "analysis": None,
            "story": None,
            "artifacts": {},
        }
        self._directory(project["id"]).mkdir(parents=True, exist_ok=False)
        self._write(project)
        return project

    def get(self, project_id):
        path = self._directory(project_id) / "studio.json"
        if path.stat().st_size > 32_000_000:
            raise ValueError("Project exceeds 32 MB")
        return _load_json(path)

    @contextmanager
    def _lock(self, name="state", timeout=15, cancelled=None):
        path = self.root / (name + ".lock")
        with path.open("a+b") as stream:
            if path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            started = time.monotonic()
            while True:
                if cancelled and cancelled():
                    raise InterruptedError("Job cancelled")
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() - started >= timeout:
                        raise TimeoutError("Workspace is busy; retry later")
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _check_source(self, project):
        if file_digest(project["source"]) != project["source_sha256"]:
            raise PermissionError("Source changed; import a new project")

    def _digest(self, project):
        payload = {
            key: value
            for key, value in project.items()
            if key not in {"artifacts", "approval", "status"}
        }
        assets = {}
        settings = project["settings"]
        candidates = [
            settings.get("graphic"),
            settings.get("background"),
            settings.get("brand", {}).get("font_path"),
            project["artifacts"].get("segmented")
            if settings.get("use_segmented")
            else None,
        ]
        for candidate in candidates:
            if (
                candidate
                and isinstance(candidate, str)
                and not candidate.startswith("#")
            ):
                asset = _local_path(candidate)
                assets[str(asset)] = file_digest(asset)
        payload["asset_digests"] = assets
        return hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()

    def review(self, project_id):
        with self._lock():
            project = self.get(project_id)
            self._check_source(project)
            return {
                "digest": self._digest(project),
                "project": project,
                "notice": "Review source, cuts, text, brand and optional assets before confirming. Receipts are consistency guards, not authentication.",
            }

    def approve(self, project_id, digest):
        with self._lock():
            project = self.get(project_id)
            self._check_source(project)
            actual = self._digest(project)
            if digest != actual:
                raise PermissionError("Reviewed revision no longer matches")
            project["approval"] = {"digest": actual, "revision": project["revision"]}
            project["status"] = "approved"
            self._write(project)
            return project

    def update(self, project_id, changes, revision):
        allowed = {
            "settings",
            "brief",
            "voice",
            "excluded_word_ids",
            "gaze_exclusions",
            "selected_hook",
            "segments",
            "transcript",
            "name",
        }
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise ValueError("Unsupported or empty project changes")
        with self._lock():
            project = self.get(project_id)
            if isinstance(revision, bool) or project["revision"] != revision:
                raise ValueError("Stale project revision; reload before editing")
            self._check_source(project)
            updated = copy.deepcopy(project)
            for key in ("brief", "voice", "name"):
                if key in changes:
                    if not isinstance(changes[key], str) or len(changes[key]) > 10000:
                        raise ValueError("Text must be a string under 10000 characters")
                    updated[key] = changes[key]
            if "settings" in changes:
                settings = changes["settings"]
                keys = {
                    "aspect",
                    "title",
                    "brand",
                    "captions",
                    "normalize_audio",
                    "graphic",
                    "background",
                    "whisper_model",
                    "face_model",
                    "segmentation_model",
                    "runtime_python",
                    "frame_step",
                    "max_width",
                    "use_segmented",
                }
                if not isinstance(settings, dict) or set(settings) - keys:
                    raise ValueError("Unsupported settings")
                merged = updated["settings"] | settings
                if merged.get("aspect") not in {
                    "source",
                    "portrait",
                    "landscape",
                    "square",
                }:
                    raise ValueError("Unsupported aspect ratio")
                if (
                    not isinstance(merged.get("title", ""), str)
                    or len(merged.get("title", "")) > 500
                ):
                    raise ValueError("Title must be under 500 characters")
                if not isinstance(merged.get("brand", {}), dict):
                    raise ValueError("Brand must be an object")
                for key in ("captions", "normalize_audio", "use_segmented"):
                    if key in merged and not isinstance(merged[key], bool):
                        raise ValueError(key + " must be boolean")
                for key in ("frame_step", "max_width"):
                    if key in merged and (
                        isinstance(merged[key], bool)
                        or not isinstance(merged[key], int)
                        or merged[key] < 1
                    ):
                        raise ValueError(key + " must be a positive integer")
                updated["settings"] = merged
            if "transcript" in changes:
                from .speech import validate_transcript

                validate_transcript(
                    changes["transcript"], project["source_info"]["duration"]
                )
                updated["transcript"] = changes["transcript"]
            for key in ("excluded_word_ids", "gaze_exclusions"):
                if key in changes:
                    if not isinstance(changes[key], list) or len(changes[key]) > 100000:
                        raise ValueError(key + " must be a bounded list")
                    updated[key] = changes[key]
            if "selected_hook" in changes:
                hook = changes["selected_hook"]
                if (
                    isinstance(hook, bool)
                    or not isinstance(hook, int)
                    or not 0 <= hook < 3
                ):
                    raise ValueError("Hook must be an index between zero and two")
                updated["selected_hook"] = hook
            if "segments" in changes:
                from .plan import validate_plan

                validate_plan(
                    {
                        "version": 1,
                        "source": project["source"],
                        "source_duration": project["source_info"]["duration"],
                        "segments": changes["segments"],
                    }
                )
                updated["base_segments"] = copy.deepcopy(changes["segments"])
            if any(
                key in changes
                for key in (
                    "segments",
                    "excluded_word_ids",
                    "gaze_exclusions",
                    "transcript",
                )
            ):
                self._rebuild_segments(updated)
            updated["revision"] += 1
            updated["status"] = "draft"
            updated.pop("approval", None)
            self._write(updated)
            return updated

    def _rebuild_segments(self, project):
        segments = project["base_segments"]
        transcript = project.get("transcript")
        if transcript and transcript.get("words") and project["excluded_word_ids"]:
            from .speech import word_segments

            word_ranges = word_segments(
                transcript["words"],
                project["excluded_word_ids"],
                duration=project["source_info"]["duration"],
            )
            segments = [
                {
                    "start": max(base["start"], word["start"]),
                    "end": min(base["end"], word["end"]),
                }
                for base in segments
                for word in word_ranges
                if max(base["start"], word["start"]) < min(base["end"], word["end"])
            ]
        for interval in project["gaze_exclusions"]:
            from .plan import _number

            start, end = _number(interval.get("start")), _number(interval.get("end"))
            if not 0 <= start < end <= project["source_info"]["duration"]:
                raise ValueError("Excluded interval lies outside the source")
            remainder = []
            for segment in segments:
                if end <= segment["start"] or start >= segment["end"]:
                    remainder.append(segment)
                else:
                    if start > segment["start"]:
                        remainder.append({"start": segment["start"], "end": start})
                    if end < segment["end"]:
                        remainder.append({"start": end, "end": segment["end"]})
            segments = remainder
        if not segments:
            raise ValueError("An edit must keep at least one source interval")
        project["segments"] = segments

    def _job_path(self, job_id):
        self._directory(job_id)
        return self.root / "jobs" / job_id / "job.json"

    def _write_job(self, job):
        path = self._job_path(job["id"])
        temporary = path.with_name("." + uuid.uuid4().hex + ".json")
        try:
            temporary.write_text(
                json.dumps(job, indent=2, allow_nan=False), encoding="utf-8"
            )
            _replace_file(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def job(self, job_id):
        record = _load_json(self._job_path(job_id))
        child = _CHILD_PROCESSES.get(job_id)
        if child is not None and record["status"] in {
            "completed",
            "failed",
            "cancelled",
        }:
            import subprocess

            try:
                child.wait(timeout=2)
                _CHILD_PROCESSES.pop(job_id, None)
            except subprocess.TimeoutExpired:
                pass
        return record

    def jobs(self, project_id=None):
        if project_id is not None:
            self._directory(project_id)
        directory = self.root / "jobs"
        if not directory.exists():
            return []
        records = [
            self.job(path.name)
            for path in sorted(directory.iterdir())
            if path.is_dir() and re.fullmatch(r"[a-f0-9]{32}", path.name)
        ]
        return [
            job
            for job in records
            if project_id is None or job["project_id"] == project_id
        ]

    def submit(self, project_id, action, options=None):
        import subprocess
        import sys

        actions = {
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
        if action not in actions:
            raise ValueError("Unsupported studio action")
        if options is None:
            options = {}
        if (
            not isinstance(options, dict)
            or len(json.dumps(options, allow_nan=False)) > 100000
        ):
            raise ValueError("Invalid or oversized job options")
        if (
            action in {"download", "publish", "obs"}
            and options.get("confirmed") is not True
        ):
            raise PermissionError("Explicit consent required for external operations")
        with self._lock():
            project = self.get(project_id)
            self._check_source(project)
            if action == "final" and project.get("approval", {}).get(
                "digest"
            ) != self._digest(project):
                raise PermissionError(
                    "Review and approve this exact revision before final export"
                )
            job = {
                "id": uuid.uuid4().hex,
                "project_id": project_id,
                "action": action,
                "revision": project["revision"],
                "status": "queued",
                "progress": 0.0,
                "error": None,
                "result": None,
                "cancel_requested": False,
                "created_at": time.time(),
                "options": options,
                "review_digest": self._digest(project),
            }
            directory = self._job_path(job["id"]).parent
            directory.mkdir(parents=True, exist_ok=False)
            (directory / "snapshot.json").write_text(
                json.dumps(project, allow_nan=False), encoding="utf-8"
            )
            self._write_job(job)
        package_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(package_root) + os.pathsep + env.get("PYTHONPATH", "")
        with (directory / "worker.log").open("ab") as log:
            try:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "cutroom.job_worker",
                        str(self.root),
                        job["id"],
                    ],
                    cwd=package_root,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    close_fds=True,
                    **(
                        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                        if os.name == "nt"
                        else {"start_new_session": True}
                    ),
                )
                _CHILD_PROCESSES[job["id"]] = process
            except Exception as error:
                job.update(status="failed", error=str(error))
                self._write_job(job)
        return self.job(job["id"])

    def _perform_job(self, job):
        project = json.loads(
            (self._job_path(job["id"]).parent / "snapshot.json").read_text(
                encoding="utf-8"
            )
        )
        self._check_source(project)
        if job["action"] == "inspect":
            return probe(project["source"])
        raise ValueError("Operation is not installed: " + job["action"])

    def cancel(self, job_id):
        with self._lock():
            job = self.job(job_id)
            if job["status"] not in {"completed", "failed", "cancelled"}:
                job["cancel_requested"] = True
                self._write_job(job)
            return job

    def artifact(self, project_id, kind):
        project = self.get(project_id)
        if kind == "source":
            self._check_source(project)
            return _local_path(project["source"])
        allowed = {
            "preview",
            "final",
            "cover",
            "captions_srt",
            "captions_vtt",
            "captions_ass",
            "quality",
            "segmented",
            "storyboard",
            "caption",
            "package",
            "calendar",
        }
        if kind not in allowed or kind not in project["artifacts"]:
            raise FileNotFoundError("Artifact is not available")
        path = _local_path(project["artifacts"][kind])
        if not path.is_relative_to(self.root):
            raise PermissionError("Artifact must remain inside this workspace")
        return path

    def list(self):
        directory = self.root / "projects"
        if not directory.is_dir():
            return []
        return [
            self.get(path.name)
            for path in sorted(directory.iterdir())
            if path.is_dir() and re.fullmatch(r"[a-f0-9]{32}", path.name)
        ]


_STUDIOS = {}


def get_studio(root=None):
    if root is None:
        root = os.environ.get("CUTROOM_WORKSPACE")
    if root is None:
        try:
            from plugins.plugin_storage import plugin_data_dir

            root = plugin_data_dir("cutroom") / "studio"
        except ImportError:
            root = Path(__file__).resolve().parents[1] / "artifacts" / "studio"
    key = str(Path(root).expanduser().resolve())
    if key not in _STUDIOS:
        _STUDIOS[key] = Studio(key)
    return _STUDIOS[key]
