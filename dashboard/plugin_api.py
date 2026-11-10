"""Profile-scoped studio HTTP API mounted by the Hermes plugin loader."""

import base64
import hashlib
import importlib
import importlib.util
import json
import sys
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter()


_import_lock = threading.Lock()


def get_studio():
    """Load our adjacent package, not a same-named package on the host path.

    Hermes loads this file as a standalone module with spec_from_file_location,
    in both its in-process and isolated plugin hosts. A private package spec
    preserves our relative imports without changing sys.path or Hermes code.
    The factory is called per request so its profile-aware storage stays scoped.
    """
    package = Path(__file__).resolve().parents[1] / "cutroom"
    key = "_cutroom_dashboard_" + hashlib.sha256(str(package).encode()).hexdigest()[:16]
    with _import_lock:
        if key not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                key, package / "__init__.py", submodule_search_locations=[str(package)]
            )
            if spec is None or spec.loader is None:
                raise ImportError("Cutroom package is unavailable")
            module = importlib.util.module_from_spec(spec)
            sys.modules[key] = module
            try:
                spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(key, None)
                raise
        studio = importlib.import_module(key + ".studio")
    return studio.get_studio()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateProject(RequestModel):
    source: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, min_length=1, max_length=200)


ProjectId = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]


def invoke(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (KeyError, FileNotFoundError) as error:
        raise HTTPException(404, "Project, job or artifact not found") from error
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error
    except (ValueError, RuntimeError) as error:
        message = str(error)
        conflict = any(
            word in message.lower()
            for word in ("revision", "stale", "digest", "changed")
        )
        raise HTTPException(409 if conflict else 422, message) from error


class UpdateProject(RequestModel):
    changes: dict[str, Any] = Field(min_length=1, max_length=6)
    revision: int = Field(ge=0)

    @field_validator("changes")
    @classmethod
    def editable_fields(cls, value):
        if set(value) - {
            "name",
            "settings",
            "transcript",
            "segments",
            "excluded_word_ids",
            "gaze_exclusions",
            "brief",
            "voice",
            "selected_hook",
        }:
            raise ValueError("Only editable project fields may be changed")
        if len(json.dumps(value, allow_nan=False)) > 2_000_000:
            raise ValueError("Project changes exceed 2 MB")
        if "name" in value and (
            not isinstance(value["name"], str) or not 1 <= len(value["name"]) <= 200
        ):
            raise ValueError("Name must contain 1 to 200 characters")
        for key in ("settings", "transcript"):
            if key in value and not isinstance(value[key], dict):
                raise ValueError(f"{key} must be an object")
        for key in ("segments", "gaze_exclusions", "excluded_word_ids"):
            if key in value and (
                not isinstance(value[key], list) or len(value[key]) > 100_000
            ):
                raise ValueError(f"{key} must be a bounded array")
        for key in ("brief", "voice"):
            if key in value and (
                not isinstance(value[key], str) or len(value[key]) > 10_000
            ):
                raise ValueError(f"{key} must be a string under 10000 characters")
        if "selected_hook" in value and (
            type(value["selected_hook"]) is not int
            or not 0 <= value["selected_hook"] < 3
        ):
            raise ValueError("selected_hook must be an index from zero to two")
        return value


@router.get("/projects/{project_id}")
def get_project(project_id: ProjectId, studio=Depends(get_studio)):
    return invoke(studio.get, project_id)


@router.patch("/projects/{project_id}")
def update_project(
    project_id: ProjectId, body: UpdateProject, studio=Depends(get_studio)
):
    return invoke(studio.update, project_id, body.changes, body.revision)


@router.post("/projects", status_code=201)
def create_project(body: CreateProject, studio=Depends(get_studio)):
    return invoke(studio.create, body.source, name=body.name)


@router.get("/projects")
def list_projects(studio=Depends(get_studio)):
    return invoke(studio.list)


Action = Literal[
    "transcribe",
    "vision",
    "segment",
    "storyboard",
    "preview",
    "final",
    "cover",
    "qa",
    "download",
    "publish",
]


class SubmitJob(RequestModel):
    action: Action
    options: dict[str, Any] = Field(default_factory=dict, max_length=64)

    @field_validator("options")
    @classmethod
    def bounded_options(cls, value):
        if len(json.dumps(value, allow_nan=False)) > 65_536:
            raise ValueError("Job options exceed 64 KiB")
        return value


class ApproveProject(RequestModel):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: bool

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit human confirmation is required")
        return value


@router.post("/projects/{project_id}/jobs", status_code=202)
def submit_job(project_id: ProjectId, body: SubmitJob, studio=Depends(get_studio)):
    if (
        body.action in ("download", "publish")
        and body.options.get("confirmed") is not True
    ):
        raise HTTPException(422, "Explicit consent is required for remote adapters")
    return invoke(studio.submit, project_id, body.action, body.options)


@router.get("/jobs")
def list_jobs(
    project_id: Annotated[
        str | None, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    ] = None,
    studio=Depends(get_studio),
):
    return invoke(studio.jobs, project_id=project_id)


@router.get("/jobs/{job_id}")
def get_job(job_id: ProjectId, studio=Depends(get_studio)):
    return invoke(studio.job, job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: ProjectId, studio=Depends(get_studio)):
    return invoke(studio.cancel, job_id)


@router.get("/projects/{project_id}/review")
def review_project(project_id: ProjectId, studio=Depends(get_studio)):
    return invoke(studio.review, project_id)


@router.post("/projects/{project_id}/approve")
def approve_project(
    project_id: ProjectId, body: ApproveProject, studio=Depends(get_studio)
):
    current = invoke(studio.review, project_id)
    if current["digest"] != body.digest:
        raise HTTPException(
            409, "Review digest changed; review the current project again"
        )
    return invoke(studio.approve, project_id, body.digest)


ArtifactKind = Literal[
    "source",
    "preview",
    "final",
    "cover",
    "quality",
    "captions_srt",
    "captions_vtt",
    "captions_ass",
    "qa",
    "captions",
    "subtitles",
]
MediaKind = Literal["source", "preview", "final", "cover"]
MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
    ".srt": "text/plain",
    ".ass": "text/plain",
    ".vtt": "text/vtt",
}


def artifact_path(studio, project_id, kind):
    canonical = {
        "qa": "quality",
        "captions": "captions_srt",
        "subtitles": "captions_vtt",
    }.get(kind, kind)
    path = Path(invoke(studio.artifact, project_id, canonical))
    if not path.is_file():
        raise HTTPException(404, "Artifact not found")
    mime = MEDIA_TYPES.get(path.suffix.lower())
    if mime is None:
        raise HTTPException(422, "Artifact format is not supported")
    return path, mime


@router.api_route("/projects/{project_id}/files/{kind}", methods=["GET", "HEAD"])
def file_artifact(
    project_id: ProjectId, kind: ArtifactKind, studio=Depends(get_studio)
):
    """Only facade-resolved artifacts; Hermes supplies the namespace auth gate."""
    path, mime = artifact_path(studio, project_id, kind)
    return FileResponse(
        path,
        media_type=mime,
        filename=path.name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


@router.get("/projects/{project_id}/media/{kind}")
def media_chunk(
    project_id: ProjectId,
    kind: MediaKind,
    offset: Annotated[int, Query(ge=0)] = 0,
    length: Annotated[int, Query(ge=1, le=1_048_576)] = 1_048_576,
    version: Annotated[str | None, Query(max_length=128)] = None,
    studio=Depends(get_studio),
):
    """JSON transport for ctx.rest, which does not expose binary responses.

    Native grants never enter media URLs. The renderer builds and revokes a
    local Blob URL from bounded, authenticated chunks after an explicit click.
    """
    path, mime = artifact_path(studio, project_id, kind)
    if not mime.startswith(("video/", "image/")):
        raise HTTPException(422, "Artifact is not playable media")
    stat = path.stat()
    current = f"{stat.st_size:x}-{stat.st_mtime_ns:x}"
    if version is not None and version != current:
        raise HTTPException(409, "Media changed while loading; reload the player")
    if stat.st_size > 268_435_456:
        raise HTTPException(
            413, "Native player supports files up to 256 MiB; render a smaller preview"
        )
    if offset >= stat.st_size:
        raise HTTPException(416, "Media offset is outside the file")
    with path.open("rb") as stream:
        stream.seek(offset)
        chunk = stream.read(length)
    after = path.stat()
    if (after.st_size, after.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
        raise HTTPException(409, "Media changed while loading; reload the player")
    return {
        "data": base64.b64encode(chunk).decode("ascii"),
        "offset": offset,
        "next_offset": offset + len(chunk),
        "total": stat.st_size,
        "mime": mime,
        "version": current,
    }
