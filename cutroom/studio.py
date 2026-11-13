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


class MissingAssetError(FileNotFoundError):
    """A project's source or reviewed asset file is no longer on disk."""


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
        project = _load_json(path)
        settings = project.get("settings")
        if isinstance(settings, dict):
            # Legacy interpreter paths are ignored and never surfaced or re-saved.
            settings.pop("runtime_python", None)
        return project

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
        try:
            digest = file_digest(project["source"])
        except FileNotFoundError as error:
            raise MissingAssetError(
                f"Source file is missing: {project['source']}; restore it or "
                "import a new project"
            ) from error
        if digest != project["source_sha256"]:
            raise PermissionError("Source changed; import a new project")

    def _digest(self, project):
        payload = {
            key: value
            for key, value in project.items()
            if key not in {"artifacts", "artifact_lineage", "approval", "status"}
        }
        assets = {}
        settings = project["settings"]
        candidates = [
            settings.get("graphic"),
            settings.get("background"),
            (settings.get("music") or {}).get("path"),
            (settings.get("cut_sfx") or {}).get("path"),
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
                try:
                    asset = _local_path(candidate)
                    assets[str(asset)] = file_digest(asset)
                except FileNotFoundError as error:
                    raise MissingAssetError(
                        f"Project asset is missing: {candidate}; restore the file "
                        "or change the project settings"
                    ) from error
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
                    "caption_style",
                    "caption_highlight_color",
                    "caption_word_y",
                    "normalize_audio",
                    "graphic",
                    "background",
                    "whisper_model",
                    "face_model",
                    "segmentation_model",
                    "frame_step",
                    "max_width",
                    "use_segmented",
                    "platform",
                    "final_resolution",
                    "music",
                    "cut_sfx",
                    "voice_cleanup",
                    "framing",
                    "framing_keyframes",
                    "pacing",
                }
                if not isinstance(settings, dict) or set(settings) - keys:
                    raise ValueError("Unsupported settings")
                merged = updated["settings"] | settings
                from .captions import RESETTABLE, validate_settings

                # null resets an optional caption field to its default.
                for key in RESETTABLE:
                    if key in settings and settings[key] is None:
                        merged.pop(key)
                validate_settings(merged)
                if (
                    settings.get("platform") == "youtube"
                    and updated["settings"].get("platform") != "youtube"
                    and "captions" not in settings
                ):
                    # Long-form YouTube gets sidecar SRT/VTT; burn-in is opt-in.
                    merged["captions"] = False
                # Interpreter paths are no longer project data; drop legacy values.
                merged.pop("runtime_python", None)
                from .platforms import FINAL_RESOLUTIONS, profile

                if "platform" in merged:
                    entry = profile(merged["platform"])
                    if entry["orientation"]:
                        # A platform fixes the frame shape; other settings still apply.
                        merged["aspect"] = entry["orientation"]
                if (
                    "final_resolution" in merged
                    and merged["final_resolution"] not in FINAL_RESOLUTIONS
                ):
                    raise ValueError("final_resolution must be '1080' or '2160'")
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
                from .postproduction import validate_brand

                validate_brand(merged.get("brand", {}))
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
                from .audio import (
                    normalize_cut_sfx,
                    normalize_music,
                    validate_voice_cleanup,
                )

                for key, normalize in (
                    ("music", normalize_music),
                    ("cut_sfx", normalize_cut_sfx),
                ):
                    if key in settings:
                        value = normalize(settings[key])
                        if value is None:
                            merged.pop(key, None)
                        else:
                            merged[key] = value
                if "voice_cleanup" in settings:
                    value = validate_voice_cleanup(settings["voice_cleanup"])
                    if value == "off":
                        merged.pop("voice_cleanup", None)
                    else:
                        merged["voice_cleanup"] = value
                from .reframe import validate_framing, validate_keyframes

                validate_framing(merged.get("framing", "fit"))
                if "pacing" in settings:
                    from .pacing import validate_settings as validate_pacing

                    value = validate_pacing(settings["pacing"])
                    if value is None:
                        merged.pop("pacing", None)
                    else:
                        merged["pacing"] = value
                if "framing_keyframes" in merged:
                    # Shape only here; program length is checked after the edit.
                    merged["framing_keyframes"] = validate_keyframes(
                        merged["framing_keyframes"]
                    )
                updated["settings"] = merged
            if "transcript" in changes:
                self._set_transcript(updated, changes["transcript"])
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
            ) or "pacing" in (changes.get("settings") or {}):
                # Shortened pauses are derived from the words, so they follow
                # every edit and every change of the pause limit.
                self._rebuild_segments(updated)
            notes = []
            if updated["settings"].get("framing_keyframes"):
                from .reframe import validate_keyframes

                program = sum(s["end"] - s["start"] for s in updated["segments"])
                pins = updated["settings"]["framing_keyframes"]
                if "framing_keyframes" in (changes.get("settings") or {}):
                    # Pins supplied now must fit the edit; the error names the pin.
                    validate_keyframes(pins, duration=program)
                else:
                    # An edit that got shorter drops the pins it no longer reaches.
                    late = [pin for pin in pins if pin["time"] > program]
                    if late:
                        updated["settings"]["framing_keyframes"] = [
                            pin for pin in pins if pin["time"] <= program
                        ]
                        notes.append(
                            "Dropped framing keyframes past the new "
                            f"{program:g} s program end at "
                            + ", ".join(f"{pin['time']:g} s" for pin in late)
                        )
            updated["revision"] += 1
            updated["status"] = "draft"
            updated.pop("approval", None)
            self._prune_artifacts(updated)
            self._write(updated)
            return {**updated, "notes": notes} if notes else updated

    @staticmethod
    def platform(project):
        """Platform name of a project; projects without the setting are custom."""
        return (project.get("settings") or {}).get("platform") or "custom"

    def derive(self, project_id, platform, name=None, final_resolution=None):
        """Create a sibling project for another platform from the same source.

        The sibling copies the reviewed edit (transcript, cuts, story, brief,
        voice, brand and model settings) but starts at revision 1 with no
        artifacts, approval or jobs; a person reviews and approves it
        separately. `derived_from` records the parent's revision and digest.
        The final resolution starts at the target profile's default unless
        `final_resolution` asks for another one.
        """
        from .platforms import FINAL_RESOLUTIONS, profile

        entry = profile(platform)
        if name is not None:
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
                raise ValueError("Name must contain 1 to 200 characters")
            name = name.strip()
        if final_resolution is not None:
            if final_resolution not in FINAL_RESOLUTIONS:
                raise ValueError("final_resolution must be '1080' or '2160'")
            if entry["frame"] is None:
                raise ValueError("final_resolution applies only to platform profiles")
        with self._lock():
            parent = self.get(project_id)
            self._check_source(parent)
            child = self._derived_project(
                parent, platform, entry, name, final_resolution
            )
            self._directory(child["id"]).mkdir(parents=True, exist_ok=False)
            self._write(child)
            return child

    def _derived_project(self, parent, platform, entry, name, final_resolution=None):
        """Build a sibling record; a later source range would narrow its cuts here."""
        settings = copy.deepcopy(parent["settings"])
        settings.pop("runtime_python", None)
        # The person layer is an artifact of the parent; the sibling must rebuild it.
        settings.pop("use_segmented", None)
        # Framing pins are target geometry; retain only for the same orientation.
        if parent["settings"].get("aspect", "source") != entry["orientation"]:
            settings.pop("framing_keyframes", None)
        settings["platform"] = platform
        if platform == "youtube":
            settings["captions"] = False
        if entry["orientation"]:
            settings["aspect"] = entry["orientation"]
        # A 4K choice belongs to the parent's target; never carry it silently.
        settings.pop("final_resolution", None)
        if entry["frame"] is not None:
            settings["final_resolution"] = (
                final_resolution or entry["frame"]["default_final"]
            )
        child = {
            "version": 2,
            "id": uuid.uuid4().hex,
            "name": name or f"{parent['name']} ({entry['short_label']})",
            "source": parent["source"],
            "source_sha256": parent["source_sha256"],
            "source_info": copy.deepcopy(parent["source_info"]),
            "revision": 1,
            "status": "draft",
            "settings": settings,
            "derived_from": {
                "project_id": parent["id"],
                "revision": parent["revision"],
                "digest": self._digest(parent),
            },
            "analysis": None,
            "artifacts": {},
        }
        for key in (
            "segments",
            "base_segments",
            "excluded_word_ids",
            "gaze_exclusions",
            "brief",
            "voice",
            "transcript",
            "story",
            "selected_hook",
        ):
            if key in parent:
                child[key] = copy.deepcopy(parent[key])
        return child

    def _platform_problem(self, project):
        """Why the current edit cannot be exported for its platform, if at all."""
        from .platforms import profile

        name = self.platform(project)
        limit = (profile(name)["max_duration_s"] or {}).get("value")
        length = sum(s["end"] - s["start"] for s in project["segments"])
        if limit is not None and length > limit:
            return (
                f"This edit runs {length:.1f} s; {profile(name)['label']} allows at "
                f"most {limit} s. Shorten the cut before final export"
            )
        return None

    def _segment_inputs(self, project):
        """Fingerprint of everything a person-layer render depends on."""
        settings = project["settings"]
        files = {}
        for key in ("segmentation_model", "background", "graphic"):
            value = settings.get(key)
            if isinstance(value, str) and value and not value.startswith("#"):
                path = _local_path(value, must_exist=False)
                files[key] = file_digest(path) if path.is_file() else None
        payload = {
            "source": project["source_sha256"],
            "settings": {
                key: settings.get(key)
                for key in ("segmentation_model", "background", "graphic", "max_width")
            },
            "files": files,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()

    def _artifact_current(self, project, kind):
        lineage = project.get("artifact_lineage", {}).get(kind)
        if lineage is None:
            return kind not in {"cover", "quality"}  # Legacy derivatives lack identity.
        if kind == "segmented":
            return lineage.get("inputs") == self._segment_inputs(project)
        if lineage.get("digest") != self._digest(project):
            return False
        if kind in {"cover", "quality"}:
            upstream = self._current_render(project)
            return bool(upstream) and lineage.get("upstream") == self._render_identity(
                project, upstream
            )
        return True

    def _prune_artifacts(self, project):
        """Drop links whose inputs no longer match; files are never deleted."""
        lineage = project.setdefault("artifact_lineage", {})
        # Segmented first: render digests can depend on the segmented asset.
        for kind in sorted(project["artifacts"], key=lambda name: name != "segmented"):
            if not self._artifact_current(project, kind):
                project["artifacts"].pop(kind, None)
                lineage.pop(kind, None)
        for kind in list(lineage):
            if kind not in project["artifacts"]:
                lineage.pop(kind)

    def _story_ready(self, project):
        story = project.get("story")
        if not story:
            return None
        if project.get("selected_hook") is None:
            return "Choose one of the three hooks before final export"
        if (
            story.get("selected_hook") != project.get("selected_hook")
            or not story.get("storyboard")
            or story.get("segments") != project["segments"]
            or story.get("brief") != project["brief"]
            or story.get("voice") != project["voice"]
        ):
            return "Build the storyboard for the selected hook and current cut before final export"
        return None

    def _render_identity(self, project, kind):
        path = self._validate_publication(project, kind)
        lineage = project.get("artifact_lineage", {}).get(kind, {})
        return {
            "kind": kind,
            "job_id": lineage.get("job_id"),
            "path": str(path),
            "sha256": file_digest(path),
        }

    def _current_render(self, project):
        for kind in ("final", "preview"):
            if kind in project["artifacts"] and self._artifact_current(project, kind):
                self._validate_publication(project, kind)
                return kind
        return None

    def _set_transcript(self, project, transcript):
        """Keep old word cuts as source ranges; never reuse another transcript's IDs."""
        from .speech import filler_suggestions, validate_transcript

        validate_transcript(transcript, project["source_info"]["duration"])
        cleared_ids = list(project["excluded_word_ids"])
        if cleared_ids:
            project["base_segments"] = self._word_selected_segments(project)
        project["excluded_word_ids"] = []
        project["transcript"] = copy.deepcopy(transcript)
        project["transcript"]["fillers"] = filler_suggestions(
            transcript["words"], transcript["language"] or ""
        )
        project["story"] = None
        project.pop("selected_hook", None)
        for kind in (
            "preview",
            "final",
            "cover",
            "captions_srt",
            "captions_vtt",
            "captions_ass",
            "quality",
            "storyboard",
            "caption",
            "package",
        ):
            project["artifacts"].pop(kind, None)
        return {
            "preserved_word_cuts": bool(cleared_ids),
            "cleared_word_ids": cleared_ids,
        }

    def _word_selected_segments(self, project):
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
        return segments

    def _rebuild_segments(self, project):
        segments = self._word_selected_segments(project)
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
        limit = (project["settings"].get("pacing") or {}).get("max_pause")
        words = (project.get("transcript") or {}).get("words") or []
        if limit is not None and words:
            from .pacing import shorten_pauses

            excluded = set(project["excluded_word_ids"])
            segments = shorten_pauses(
                segments, [w for w in words if w["id"] not in excluded], limit
            )
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
        if action == "silence":
            from .plan import _number

            if set(options) - {"noise_db", "min_duration", "padding"}:
                raise ValueError("Unsupported silence options")
            for key, value in options.items():
                number = _number(value)
                if (key == "min_duration" and number <= 0) or (
                    key == "padding" and number < 0
                ):
                    raise ValueError(
                        "Silence duration must be positive and padding non-negative"
                    )
        if action == "transcribe":
            if set(options) - {"language"}:
                raise ValueError("Unsupported transcription options")
            language = options.get("language")
            if language is not None and (
                not isinstance(language, str)
                or not re.fullmatch(r"[a-z]{2,3}", language)
            ):
                raise ValueError(
                    "Language must be a lowercase two/three-letter code or null"
                )
        if action in {"segment", "storyboard", "preview", "final", "qa"} and options:
            raise ValueError("This action takes no options; use project settings")
        if action == "vision":
            if set(options) - {"frame_step"}:
                raise ValueError("Unsupported vision options")
            step = options.get("frame_step", 1)
            if isinstance(step, bool) or not isinstance(step, int) or step < 1:
                raise ValueError("frame_step must be a positive integer")
        if action == "cover":
            from .plan import _number

            if set(options) - {"time"}:
                raise ValueError("Unsupported cover options")
            if "time" in options and _number(options["time"]) < 0:
                raise ValueError("Cover time must be non-negative")
        if (
            action in {"download", "publish", "obs"}
            and options.get("confirmed") is not True
        ):
            raise PermissionError("Explicit consent required for external operations")
        with self._lock():
            project = self.get(project_id)
            self._check_source(project)
            upstream = self._preflight(project, action)
            input_digests = self._job_inputs(project, action, upstream)
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
                "input_digests": input_digests,
            }
            if upstream:
                job["upstream"] = upstream
                job["upstream_identity"] = self._render_identity(project, upstream)
            directory = self._job_path(job["id"]).parent
            directory.mkdir(parents=True, exist_ok=False)
            (directory / "snapshot.json").write_text(
                json.dumps(project, allow_nan=False), encoding="utf-8"
            )
            self._write_job(job)
        package_root = Path(__file__).resolve().parents[1]
        from .childenv import child_env

        env = child_env()
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

    def _preflight(self, project, action):
        """Reject actions whose prerequisites are missing before a job exists."""
        settings = project["settings"]
        if action in {"preview", "final"}:
            from .audio import validate_settings

            validate_settings(
                {
                    key: settings[key]
                    for key in ("music", "cut_sfx", "voice_cleanup")
                    if key in settings
                }
            )
        if action == "storyboard":
            transcript = project.get("transcript") or {}
            if not transcript.get("words"):
                raise ValueError(
                    "Storyboard needs a timed transcript with words; transcribe first"
                )
        if action in {"vision", "segment"}:
            key = "face_model" if action == "vision" else "segmentation_model"
            model = settings.get(key)
            if not model or not _local_path(model, must_exist=False).is_file():
                raise ValueError(
                    f"Set settings.{key} to an existing local model file; "
                    "run `cutroom setup-models` to acquire it. Nothing is downloaded automatically"
                )
        if action in {"preview", "final"} and settings.get("use_segmented"):
            if not (
                "segmented" in project["artifacts"]
                and self._artifact_current(project, "segmented")
            ):
                raise ValueError(
                    "Run segment for the current settings before rendering the person layer"
                )
        if action in {"preview", "final"} and settings.get("framing") == "face_track":
            analysis = project.get("analysis")
            if analysis is None:
                raise ValueError("Run Vision before rendering face_track framing")
            if "face_samples" not in analysis:
                raise ValueError(
                    "Run Vision again to record face boxes for face_track framing"
                )
            from .reframe import validate_analysis

            validate_analysis(
                {
                    "faces": analysis["face_samples"],
                    "scene_cuts": analysis.get("scene_cuts"),
                }
            )
        if action == "final":
            problem = self._platform_problem(project)
            if problem:
                raise ValueError(problem)
            problem = self._story_ready(project)
            if problem:
                raise PermissionError(problem)
        if action in {"cover", "qa"}:
            upstream = self._current_render(project)
            if upstream is None:
                raise ValueError("Render a current preview or final first")
            return upstream
        return None

    def _job_inputs(self, project, action, upstream=None):
        """Digests of files a job reads beyond the source and reviewed assets."""
        if action == "transcribe":
            return self._transcription_assets(project)
        paths = []
        if action in {"vision", "segment"}:
            key = "face_model" if action == "vision" else "segmentation_model"
            paths.append(project["settings"].get(key))
        if upstream:
            paths.append(self._validate_publication(project, upstream))
        if action in {"preview", "final"} and project["settings"].get("use_segmented"):
            paths.append(self._validate_publication(project, "segmented"))
        return {
            str(_local_path(path)): file_digest(_local_path(path))
            for path in paths
            if path
        }

    def _cues(self, project):
        """Output-time caption cues for kept, non-excluded words."""
        from .speech import caption_cues, remap_words

        transcript = project.get("transcript") or {}
        excluded = set(project["excluded_word_ids"])
        words = [w for w in transcript.get("words") or [] if w["id"] not in excluded]
        if not words:
            return []
        total = sum(s["end"] - s["start"] for s in project["segments"])
        cues, previous = [], 0.0
        for cue in caption_cues(remap_words(words, project["segments"])):
            start, end = max(cue["start"], previous), min(cue["end"], total)
            if end - start >= 0.05 and cue["text"].strip():
                cues.append({"start": start, "end": end, "text": cue["text"]})
                previous = end
        return cues

    def _caption_words(self, project):
        """Map kept word fragments once, merging fragments of the same word."""
        from .speech import remap_words

        excluded = set(project.get("excluded_word_ids", []))
        words = [
            w
            for w in (project.get("transcript") or {}).get("words", [])
            if w["id"] not in excluded
        ]
        result, sources = [], []
        for word in remap_words(words, project["segments"]):
            if sources and sources[-1] == word["source_id"]:
                result[-1]["end"] = word["end"]
            else:
                result.append({key: word[key] for key in ("start", "end", "text")})
                sources.append(word["source_id"])
        return result

    def _render_settings(self, project, preset):
        settings = project["settings"]
        brand = {
            key: value
            for key, value in settings.get("brand", {}).items()
            if key not in {"aspect", "preset"}
        }
        title = settings.get("title") or ""
        story = project.get("story") or {}
        platform = self.platform(project)
        entry = None
        if platform != "custom":
            from .platforms import profile

            entry = profile(platform)
        if not title and story.get("opening_hook"):
            title = story["opening_hook"]["text"]
        if title and "\n" not in title:
            import textwrap

            aspect = settings.get("aspect", "source")
            if entry is not None:
                aspect = entry["orientation"]
            if aspect == "source":
                info = project["source_info"]
                aspect = "portrait" if info["height"] > info["width"] else "landscape"
            width = {"portrait": 24, "square": 28}.get(aspect, 36)
            lines = textwrap.wrap(title, width) or [title]
            if len(lines) > 3:
                lines = lines[:3]
                lines[-1] = lines[-1][: width - 1].rstrip() + "…"
            title = "\n".join(lines)
        result = {
            "preset": preset,
            "aspect": settings.get("aspect", "source"),
            "brand": brand,
            "title": title,
            "normalize_audio": settings.get("normalize_audio", True),
            "timeout": 3600 if preset == "final" else 900,
        }
        if entry is not None:
            # Platform renders use the profile's frame, shape and delivery loudness.
            result["aspect"] = entry["orientation"]
            result["platform"] = platform
            result["final_resolution"] = (
                settings.get("final_resolution") or entry["frame"]["default_final"]
            )
            result["loudness_lufs"] = entry["loudness"]["integrated_lufs"]
            result["true_peak_db"] = entry["loudness"]["true_peak_db"]
        if settings.get("caption_style", "classic") != "classic":
            for key in ("caption_style", "caption_highlight_color", "caption_word_y"):
                if key in settings:
                    result[key] = settings[key]
        audio = {
            key: copy.deepcopy(settings[key])
            for key in ("music", "cut_sfx", "voice_cleanup")
            if key in settings
        }
        if audio and (
            audio.get("music")
            or audio.get("cut_sfx")
            or audio.get("voice_cleanup", "off") != "off"
        ):
            result["audio"] = audio
        mode = settings.get("framing", "fit")
        if mode != "fit":
            result["framing"] = mode
        if mode in {"center_crop", "face_track"} and settings.get("framing_keyframes"):
            result["framing_keyframes"] = settings["framing_keyframes"]
        if mode == "face_track":
            analysis = project.get("analysis") or {}
            result["framing_analysis"] = {
                "faces": analysis.get("face_samples", []),
                "scene_cuts": analysis.get("scene_cuts"),
            }
        if settings.get("pacing"):
            from .pacing import zooming

            result["pacing"] = copy.deepcopy(settings["pacing"])
            faces = (project.get("analysis") or {}).get("face_samples")
            if zooming(settings["pacing"]) and faces:
                # Punch-ins centre on the face in every framing mode.
                result["pacing_analysis"] = {"faces": faces}
        return result

    def _quality_settings(self, project, preset):
        """QA settings; platform checks need the title to rebuild text geometry."""
        render = self._render_settings(project, preset)
        render.pop("framing_analysis", None)
        render.pop("framing_keyframes", None)
        render.pop("pacing_analysis", None)
        if (render.get("pacing") or {}).get("max_pause") is not None:
            excluded = set(project.get("excluded_word_ids", []))
            render["pacing_words"] = [
                [w["start"], w["end"]]
                for w in (project.get("transcript") or {}).get("words", [])
                if w["id"] not in excluded and w["end"] > w["start"]
            ]
        if "platform" not in render:
            render.pop("title")
        render["expected_duration"] = sum(
            s["end"] - s["start"] for s in project["segments"]
        )
        return render

    def _perform_job(self, job):
        project = json.loads(
            (self._job_path(job["id"]).parent / "snapshot.json").read_text(
                encoding="utf-8"
            )
        )
        self._check_source(project)
        action = job["action"]
        self._job_inputs(project, action, job.get("upstream"))
        if action == "inspect":
            return probe(project["source"])
        directory = self._job_path(job["id"]).parent
        outputs = directory / "outputs"
        if action == "storyboard":
            return self._storyboard(project, outputs)
        from .runtime import invoke_worker

        settings = project["settings"]

        def run(operation, arguments, timeout=1800):
            return invoke_worker(
                operation,
                arguments,
                directory / ("engine-" + operation),
                cancelled=lambda: self.job(job["id"]).get("cancel_requested", False),
                timeout=timeout,
            )

        if action in {"silence", "transcribe"}:
            arguments = {"source": project["source"], **job["options"]}
            if action == "transcribe":
                arguments["model_path"] = settings.get("whisper_model")
            return invoke_worker(
                action,
                arguments,
                directory / "engine",
                cancelled=lambda: self.job(job["id"]).get("cancel_requested", False),
            )
        if action == "vision":
            return run(
                "vision",
                {
                    "source": project["source"],
                    "face_model": settings["face_model"],
                    "frame_step": job["options"].get(
                        "frame_step", settings.get("frame_step", 1)
                    ),
                },
                timeout=3600,
            )
        outputs.mkdir(exist_ok=False)
        if action == "segment":
            return run(
                "segment",
                {
                    "source": project["source"],
                    "segmentation_model": settings["segmentation_model"],
                    "output": str(outputs / "segmented.mp4"),
                    "background": settings.get("background") or None,
                    "graphic": settings.get("graphic") or None,
                    "max_width": settings.get("max_width", 1280),
                },
                timeout=7200,
            )
        cues = self._cues(project)
        animated = settings.get("caption_style", "classic") != "classic"
        burn = settings.get("captions") is True
        caption_extra = (
            {"caption_words": self._caption_words(project)} if animated and burn else {}
        )
        if action in {"preview", "final"}:
            from .speech import write_subtitles

            source = project["source"]
            if settings.get("use_segmented"):
                source = project["artifacts"]["segmented"]
            result = run(
                action,
                {
                    "source": source,
                    "segments": project["segments"],
                    "output": str(outputs / (action + ".mp4")),
                    "settings": self._render_settings(project, action),
                    "captions": cues if burn else None,
                    **caption_extra,
                    **(
                        {"caption_script": str(outputs / "captions.ass")}
                        if animated and burn and cues
                        else {}
                    ),
                },
                timeout=7200 if action == "final" else 3600,
            )
            artifacts = {action: result["output"]}
            if animated and burn and cues:
                artifacts["captions_ass"] = str(outputs / "captions.ass")
                # QA of this render checks this exact script, by hash.
                result["caption_script_sha256"] = file_digest(outputs / "captions.ass")
            if cues:
                for format in ("srt", "vtt"):
                    written = write_subtitles(
                        cues, outputs / ("captions." + format), format=format
                    )
                    artifacts["captions_" + format] = written["path"]
            return {**result, "render_source": source, "artifacts": artifacts}
        video = project["artifacts"][job["upstream"]]
        if action == "cover":
            preset = "final" if job["upstream"] == "final" else "preview"
            render = self._render_settings(project, preset)
            result = run(
                "cover",
                {
                    "video": video,
                    "output": str(outputs / "cover.png"),
                    "title": render.pop("title"),
                    "settings": render,
                    "time": job["options"].get("time", 0),
                },
            )
            return {**result, "artifacts": {"cover": result["output"]}}
        if action == "qa":
            preset = "final" if job["upstream"] == "final" else "preview"
            render = self._quality_settings(project, preset)
            lineage = project.get("artifact_lineage", {}).get(job["upstream"], {})
            render_job = self.job(lineage["job_id"]) if lineage.get("job_id") else {}
            mix_report = (render_job.get("result") or {}).get("audio_mix")
            if mix_report is not None:
                render["audio_mix"] = mix_report
            pacing_report = (render_job.get("result") or {}).get("pacing")
            if pacing_report is not None and render.get("pacing"):
                render["pacing_report"] = pacing_report
            framing = self._render_framing(project, job["upstream"])
            if framing and framing.get("mode") in {"center_crop", "face_track"}:
                render["framing_report"] = framing
            source_video = self._render_source_video(project, job["upstream"])
            if source_video is not None and "platform" in render:
                render["source_video"] = source_video
            script_job, script = (
                self._render_caption_script(project, job["upstream"])
                if animated and burn
                else (None, None)
            )
            report = run(
                "qa",
                {
                    "video": video,
                    "settings": render,
                    "captions": cues if burn else None,
                    **caption_extra,
                    **({"caption_script": str(script)} if script else {}),
                },
                timeout=3600,
            )
            report = {**report, "video": job["upstream"]}
            for check in report.get("checks", []):
                if check.get("name") == "caption_timing" and script_job:
                    check.setdefault("detail", {})["script_job"] = script_job
            path = outputs / "quality.json"
            with path.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, allow_nan=False)
            return {**report, "artifacts": {"quality": str(path)}}
        raise ValueError("Operation is not installed: " + action)

    def _render_caption_script(self, project, kind):
        """The caption script burned into the current ``kind`` render, if intact.

        Read from the render's own job, not the latest published ``captions_ass``
        (a later preview replaces that one), and only when its hash still matches
        what the render recorded. Otherwise QA rebuilds the script for the video's
        size and says so.
        """
        lineage = project.get("artifact_lineage", {}).get(kind) or {}
        job_id = lineage.get("job_id")
        try:
            record = self.job(job_id)
            result = record.get("result") or {}
            value = (result.get("artifacts") or {}).get("captions_ass")
            expected = result.get("caption_script_sha256")
            if not value or not expected:
                return None, None
            path = self._owned(record, value)
            if file_digest(path) != expected:
                return None, None
            return job_id, path
        except (OSError, ValueError, TypeError, KeyError, PermissionError):
            return None, None

    def _render_framing(self, project, kind):
        lineage = project.get("artifact_lineage", {}).get(kind) or {}
        try:
            return (self.job(lineage.get("job_id")).get("result") or {}).get("framing")
        except (OSError, ValueError, TypeError):
            return None

    def _render_source_video(self, project, kind):
        """Source size the published render was made from, from its job result."""
        lineage = project.get("artifact_lineage", {}).get(kind) or {}
        job_id = lineage.get("job_id")
        try:
            result = self.job(job_id).get("result") or {}
        except (OSError, ValueError, TypeError):
            return None
        source = result.get("source_video")
        return source if isinstance(source, dict) else None

    def _storyboard(self, project, outputs):
        """Deterministic, source-quoted hooks and storyboard; no invented text."""
        from .narrative import publication_caption, story_options

        transcript = {**project["transcript"], "segments": project["segments"]}
        story = story_options(
            transcript, brief=project["brief"], voice=project["voice"]
        )
        selected = project.get("selected_hook")
        story["selected_hook"] = selected
        if selected is None:
            story["storyboard"] = []
            story["status"] = "awaiting_hook_selection"
        else:
            story["opening_hook"] = story["hooks"][selected]
        caption = publication_caption(
            transcript, brief=project["brief"], voice=project["voice"]
        )
        outputs.mkdir(exist_ok=False)
        artifacts = {}
        for key, data in (("storyboard", story), ("caption", caption)):
            path = outputs / (key + ".json")
            with path.open("x", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2, allow_nan=False)
            artifacts[key] = str(path)
        return {"story": story, "caption": caption, "artifacts": artifacts}

    def _transcription_assets(self, project):
        if not project["source_info"]["has_audio"]:
            return {}
        from .speech import local_model_files

        return {
            str(asset): file_digest(asset)
            for asset in local_model_files(project["settings"].get("whisper_model"))
        }

    def _check_job_project(self, job):
        """Call under the state lock, both before execution and publication."""
        if self.job(job["id"]).get("cancel_requested"):
            raise InterruptedError("Job cancelled")
        current = self.get(job["project_id"])
        if current["revision"] != job["revision"]:
            raise ValueError(
                "Project changed while this job was queued or running; retry on the current revision"
            )
        self._check_source(current)
        if self._digest(current) != job["review_digest"]:
            raise PermissionError("Project assets changed; review and retry")
        if job.get("upstream"):
            upstream = self._current_render(current)
            if upstream != job["upstream"] or self._render_identity(
                current, upstream
            ) != job.get("upstream_identity"):
                raise PermissionError("Job upstream changed; submit a new job")
        expected = job.get("input_digests") or {}
        if self._job_inputs(current, job["action"], job.get("upstream")) != expected:
            if job["action"] == "transcribe":
                raise PermissionError(
                    "Transcription model changed; retry with the current model"
                )
            raise PermissionError("Job inputs changed; submit a new job")
        if job["action"] == "final" and (
            current.get("approval", {}).get("digest") != self._digest(current)
        ):
            raise PermissionError("Final export lost its current human approval")
        return current

    def _owned(self, job, value):
        outputs = (self._job_path(job["id"]).parent / "outputs").resolve()
        path = _local_path(value)
        if not path.is_relative_to(outputs) or not path.is_file():
            raise PermissionError(
                "Job artifact must be a file in its own output directory"
            )
        return path

    def _publish(self, project, job, artifacts, **extra):
        lineage = project.setdefault("artifact_lineage", {})
        for kind, value in artifacts.items():
            path = self._owned(job, value)
            stat = path.stat()
            project["artifacts"][kind] = str(path)
            lineage[kind] = {
                "job_id": job["id"],
                "sha256": file_digest(path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                **extra,
            }
        digest = self._digest(project)
        for kind in artifacts:
            if kind == "segmented":
                lineage[kind]["inputs"] = self._segment_inputs(project)
            else:
                lineage[kind]["digest"] = digest

    def _complete_job(self, job, result):
        with self._lock():
            current = self._check_job_project(job)
            job = self.job(job["id"])
            action = job["action"]
            if action in {"vision", "segment", "storyboard"}:
                updated = copy.deepcopy(current)
                if action == "vision":
                    frames = result.get("frames", [])
                    result = {
                        **result,
                        "frames": frames[:2000],
                        "frames_truncated": len(frames) > 2000,
                    }
                    updated["analysis"] = result
                elif action == "segment":
                    summary = {
                        k: v
                        for k, v in result.items()
                        if k not in {"artifacts", "output"}
                    }
                    updated["segmentation"] = summary
                    result = summary | {"artifacts": {"segmented": result["output"]}}
                else:
                    updated["story"] = result["story"]
                updated["revision"] += 1
                updated["status"] = "draft"
                updated.pop("approval", None)
                self._publish(updated, job, result.get("artifacts", {}))
                self._prune_artifacts(updated)
                self._write(updated)
                job["applied_revision"] = updated["revision"]
            elif action in {"preview", "final", "cover", "qa"}:
                updated = copy.deepcopy(current)
                extra = (
                    {"from": job["upstream"], "upstream": job["upstream_identity"]}
                    if job.get("upstream")
                    else {}
                )
                if action in {"preview", "final"}:
                    # Players draw the safe zone of the profile the render used.
                    extra["platform"] = result.get("platform") or "custom"
                self._publish(updated, job, result["artifacts"], **extra)
                self._prune_artifacts(updated)
                self._write(updated)
            if action in {"silence", "transcribe"}:
                from .plan import validate_plan

                updated = copy.deepcopy(current)
                if job["action"] == "silence":
                    validate_plan(result)
                    if (
                        result["source"] != current["source"]
                        or result["source_duration"]
                        != current["source_info"]["duration"]
                    ):
                        raise ValueError(
                            "Silence result does not match the project source"
                        )
                    updated["base_segments"] = [
                        {
                            "start": max(base["start"], keep["start"]),
                            "end": min(base["end"], keep["end"]),
                        }
                        for base in current["base_segments"]
                        for keep in result["segments"]
                        if max(base["start"], keep["start"])
                        < min(base["end"], keep["end"])
                    ]
                else:
                    job["transcript_update"] = self._set_transcript(updated, result)
                    if (updated["transcript"]["status"] == "no_audio") != (
                        not current["source_info"]["has_audio"]
                    ):
                        raise ValueError(
                            "Transcript audio status does not match the source"
                        )
                self._rebuild_segments(updated)
                validate_plan(
                    {
                        "version": 1,
                        "source": updated["source"],
                        "source_duration": updated["source_info"]["duration"],
                        "segments": updated["segments"],
                    }
                )
                updated["revision"] += 1
                updated["status"] = "draft"
                updated.pop("approval", None)
                self._write(updated)
                job["applied_revision"] = updated["revision"]
            job.update(
                status="completed",
                progress=1.0,
                result=result,
                completed_at=time.time(),
            )
            self._write_job(job)

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
        if not self._artifact_current(project, kind):
            raise FileNotFoundError("Artifact is stale for the current revision")
        return self._validate_publication(project, kind)

    def _validate_publication(self, project, kind):
        """Validate stored publication bytes, not a newly adopted input hash."""
        path = _local_path(project["artifacts"][kind])
        if not path.is_relative_to(self.root):
            raise PermissionError("Artifact must remain inside this workspace")
        lineage = project.get("artifact_lineage", {}).get(kind)
        if lineage:
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns, file_digest(path)) != (
                lineage["size"],
                lineage["mtime_ns"],
                lineage["sha256"],
            ):
                raise PermissionError("Artifact changed after publication")
        return path

    def list(self):
        """Projects plus ``modified_at``, the last save time for display only."""
        directory = self.root / "projects"
        if not directory.is_dir():
            return []
        projects = []
        for path in sorted(directory.iterdir()):
            if not (path.is_dir() and re.fullmatch(r"[a-f0-9]{32}", path.name)):
                continue
            project = self.get(path.name)
            try:
                modified = (path / "studio.json").stat().st_mtime
            except OSError:
                modified = None
            projects.append({**project, "modified_at": modified})
        return projects


_STUDIOS = {}


def get_studio(root=None):
    if root is None:
        from .paths import studio_root

        root = studio_root()
    key = str(Path(root).expanduser().resolve())
    if key not in _STUDIOS:
        _STUDIOS[key] = Studio(key)
    return _STUDIOS[key]
