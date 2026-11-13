"""Model-facing Studio adapters; importing and registering never opens a profile.

Human approval of a final export is deliberately absent from this surface: it
stays in Cutroom Studio (Desktop) and the local REST API only.
"""

import json
import math
from pathlib import Path

TRANSCRIPT_PREVIEW_WORDS = 50
MEDIA_KINDS = ("preview", "final", "cover")
QA_NAME_LIMIT = 20
TEXT_LIMIT = 200
DISPLAY_HINT = "Show it to the person with a line: MEDIA:"

PROJECT_CHANGES = frozenset(
    {
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
)
JOB_OPERATIONS = frozenset(
    {
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
    }
)
# action -> (allowed fields, required fields)
PROJECT_ACTIONS = {
    "create": ({"source", "name"}, {"source"}),
    "list": (set(), set()),
    "get": ({"project_id"}, {"project_id"}),
    "update": (
        {"project_id", "changes", "revision"},
        {"project_id", "changes", "revision"},
    ),
    "review": ({"project_id"}, {"project_id"}),
    "post_text": ({"project_id", "post"}, {"project_id"}),
    "package": ({"project_id", "post", "cover_time"}, {"project_id"}),
    "packages": ({"project_id"}, {"project_id"}),
    "verify_package": ({"project_id", "package"}, {"project_id", "package"}),
    "find_clips": (
        {"project_id", "min_s", "max_s", "count", "platform"},
        {"project_id"},
    ),
    "create_clip": (
        {
            "project_id",
            "platform",
            "candidate_id",
            "start",
            "end",
            "name",
            "final_resolution",
        },
        {"project_id", "platform"},
    ),
    "derive": (
        {"project_id", "platform", "name", "final_resolution"},
        {"project_id", "platform"},
    ),
}
# Mirrors cutroom.platforms.PLATFORMS; kept literal so registering tools stays cheap.
PLATFORMS = ("custom", "instagram_reels", "youtube_shorts", "tiktok", "youtube")
JOB_ACTIONS = {
    "submit": ({"project_id", "operation", "options"}, {"project_id", "operation"}),
    "list": ({"project_id"}, set()),
    "get": ({"job_id"}, {"job_id"}),
    "cancel": ({"job_id"}, {"job_id"}),
}
LIST_FIELDS = ("id", "name", "revision", "status", "source")
APPROVAL_NOTICE = (
    "Human approval of the exact reviewed digest is required before final job "
    "submission and is checked again on completion. Approval stays in Cutroom "
    "Studio (Desktop) or the local REST API: only a person can approve. This "
    "tool cannot approve, and you must never claim that anything was approved; "
    "ask the user to review and approve it in Cutroom Studio."
)
WORKFLOW = (
    "Usual order: cutroom_project create from a local path; cutroom_job submit "
    "transcribe, then get every few seconds and report stage and percent; "
    "cutroom_project update with the agreed cuts, settings.platform, caption "
    "style and framing; submit preview; submit qa; the person reviews and "
    "approves in Cutroom Studio; then submit final."
)


def get_studio():
    """Resolve the current profile only when a validated handler is invoked."""
    from .studio import get_studio as factory

    return factory()


def _arguments(args, actions):
    if not isinstance(args, dict):
        raise ValueError("Arguments must be an object")
    action = args.get("action")
    if not isinstance(action, str) or action not in actions:
        raise ValueError("Unsupported action; expected one of: " + ", ".join(actions))
    allowed, required = actions[action]
    unknown = set(args) - allowed - {"action"}
    if unknown:
        raise ValueError(
            f"Unsupported arguments for {action}: " + ", ".join(sorted(unknown))
        )
    missing = required - set(args)
    if missing:
        raise ValueError(
            f"Missing required arguments for {action}: " + ", ".join(sorted(missing))
        )
    for field in ("source", "name", "project_id", "job_id", "operation", "platform"):
        if field in args and (
            not isinstance(args[field], str) or not args[field].strip()
        ):
            raise ValueError(field + " must be a nonempty string")
    json.dumps(args, allow_nan=False)
    return action


def _response(function):
    try:
        return json.dumps({"ok": True, "result": function()}, allow_nan=False)
    except Exception as error:
        return json.dumps(
            {"ok": False, "error": str(error), "type": type(error).__name__},
            allow_nan=False,
        )


def _summarize(project):
    """Replace the full word list with a count and a short preview."""
    if not isinstance(project, dict):
        return project
    transcript = project.get("transcript")
    if not isinstance(transcript, dict) or not isinstance(
        transcript.get("words"), list
    ):
        return project
    words = transcript["words"]
    summary = dict(
        transcript,
        words=words[:TRANSCRIPT_PREVIEW_WORDS],
        word_count=len(words),
        words_truncated=len(words) > TRANSCRIPT_PREVIEW_WORDS,
    )
    return dict(project, transcript=summary)


def _compact(project):
    result = {key: project.get(key) for key in LIST_FIELDS}
    result["artifacts"] = sorted(project.get("artifacts") or {})
    return result


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _text(value):
    return value[:TEXT_LIMIT] if isinstance(value, str) else None


def _json_safe(value):
    """Replace non-finite numbers so a result always serialises."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _upstream_job(job):
    identity = job.get("upstream_identity")
    if isinstance(identity, dict):
        return identity.get("job_id")
    return None


def qa_summary(job):
    """Counts from the check statuses; a warning alone never means failure."""
    checks = (job.get("result") or {}).get("checks")
    checks = [check for check in checks or [] if isinstance(check, dict)]
    statuses = [check.get("status") for check in checks]

    def names(status):
        return [
            _text(check.get("name")) or "check"
            for check in checks
            if check.get("status") == status
        ][:QA_NAME_LIMIT]

    failed = statuses.count("fail")
    warnings = statuses.count("warning")
    return {
        "job_id": job.get("id"),
        "status": "fail" if failed else "warning" if warnings else "pass",
        "passed": statuses.count("pass"),
        "failed": failed,
        "warnings": warnings,
        "total": len(checks),
        "failed_checks": names("fail"),
        "warning_checks": names("warning"),
    }


def _latest_qa(studio, project_id, render_job_id):
    if not render_job_id:
        return None
    matching = [
        job
        for job in studio.jobs(project_id=project_id) or []
        if isinstance(job, dict)
        and job.get("action") == "qa"
        and job.get("status") == "completed"
        and _upstream_job(job) == render_job_id
    ]
    if not matching:
        return None
    latest = max(
        matching,
        key=lambda job: (
            _number(job.get("completed_at")) or _number(job.get("created_at")) or 0
        ),
    )
    return qa_summary(latest)


def _media(studio, job, project=None):
    """Display summary of a completed preview, final or cover; None otherwise."""
    if not isinstance(job, dict) or job.get("status") != "completed":
        return None
    kind = job.get("action")
    result = job.get("result")
    if kind not in MEDIA_KINDS or not isinstance(result, dict):
        return None
    value = (result.get("artifacts") or {}).get(kind) or result.get("output")
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        return None
    if project is None:
        project = studio.get(job["project_id"])
    lineage = project.get("artifact_lineage") or {}
    render_kind = kind
    render_job_id = job.get("id")
    if kind == "cover":
        render_job_id = _upstream_job(job)
        render_kind = (job.get("upstream_identity") or {}).get("kind") or "preview"
    approval = project.get("approval") or {}
    platform = (
        result.get("platform")
        or (lineage.get(render_kind) or {}).get("platform")
        or (project.get("settings") or {}).get("platform")
    )
    return {
        "path": value,
        "kind": kind,
        "project_id": project.get("id"),
        "project_name": _text(project.get("name")),
        "platform": _text(platform),
        "duration": _number(result.get("duration")),
        "width": _number(result.get("width")),
        "height": _number(result.get("height")),
        "current": (lineage.get(kind) or {}).get("job_id") == job.get("id"),
        "qa": _latest_qa(studio, project.get("id"), render_job_id),
        "approved": bool(approval)
        and approval.get("revision") == project.get("revision"),
    }


def _with_media(studio, job):
    """Add ``media`` and ``display_hint``; lookup problems never hide the job."""
    try:
        media = _media(studio, job)
    except Exception:
        media = None
    if media is None:
        return job
    # A displayable render must still serialise; drop non-finite numbers.
    return _json_safe(dict(job, media=media, display_hint=DISPLAY_HINT + media["path"]))


def _project_media(studio, project):
    summary = {}
    lineage = project.get("artifact_lineage") or {}
    for kind in ("preview", "final"):
        job_id = (lineage.get(kind) or {}).get("job_id")
        if kind not in (project.get("artifacts") or {}) or not job_id:
            continue
        try:
            media = _media(studio, studio.job(job_id=job_id), project)
        except Exception:
            media = None
        if media is not None:
            summary[kind] = media
    return summary


def project_handler(args, **kwargs):
    """Validate the action-specific contract before resolving Studio."""

    def perform():
        action = _arguments(args, PROJECT_ACTIONS)
        if "post" in args:
            from .packages import normalize_post

            normalize_post(args["post"])
        if action == "verify_package":
            from .packages import PACKAGE_NAME

            if not isinstance(args["package"], str) or not PACKAGE_NAME.fullmatch(
                args["package"]
            ):
                raise ValueError("Invalid package folder name")
        if action == "find_clips":
            from .clips import _bounds

            _bounds(
                args.get("min_s"),
                args.get("max_s"),
                args.get("count"),
                args.get("platform"),
            )
        if action == "create_clip":
            from .clips import validate_pick

            validate_pick(args.get("candidate_id"), args.get("start"), args.get("end"))
            if args["platform"] not in PLATFORMS:
                raise ValueError("Unsupported platform")
        if action in {"derive", "create_clip"} and args.get(
            "final_resolution", "1080"
        ) not in ("1080", "2160"):
            raise ValueError("final_resolution must be '1080' or '2160'")
        if action == "derive" and args["platform"] not in PLATFORMS:
            raise ValueError(
                "Unsupported platform; expected one of: " + ", ".join(PLATFORMS)
            )
        if action == "derive" and args.get("final_resolution", "1080") not in (
            "1080",
            "2160",
        ):
            raise ValueError("final_resolution must be '1080' or '2160'")
        if action == "update":
            changes = args["changes"]
            if not isinstance(changes, dict) or not changes:
                raise ValueError("changes must be a nonempty object")
            unsupported = set(changes) - PROJECT_CHANGES
            if unsupported:
                raise ValueError(
                    "Unsupported project changes: " + ", ".join(sorted(unsupported))
                )
            if "settings" in changes:
                from .captions import validate_settings

                validate_settings(changes["settings"], allow_reset=True)
            revision = args["revision"]
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 1
            ):
                raise ValueError("revision must be a positive integer")
        values = {key: value for key, value in args.items() if key != "action"}
        studio = get_studio()
        if action == "verify_package":
            result = studio.verify_package(
                studio.package_path(args["project_id"], args["package"])
            )
        elif action == "post_text" and "post" in args:
            result = studio.set_post(args["project_id"], args["post"])
        else:
            result = getattr(studio, action)(**values)
        if action == "list":
            return [_compact(project) for project in result]
        if action == "get" and isinstance(result, dict):
            media = _project_media(studio, result)
            longform = None
            if (result.get("settings") or {}).get("platform") == "youtube":
                # Chapters and their problems; lookup problems never hide the project.
                try:
                    longform = _json_safe(studio.longform_summary(result))
                except Exception:
                    longform = None
            result = _summarize(result)
            if longform is not None:
                result = dict(result, longform=longform)
            return dict(result, media=media) if media else result
        if action == "find_clips":
            return {
                **result,
                "candidates": [
                    {
                        key: value
                        for key, value in item.items()
                        if key
                        in {"id", "rank", "start", "end", "duration", "score", "hook"}
                    }
                    | {
                        "text": item.get("text", "")[:400],
                        "reasons": [
                            f"{r['text']} ({r['points']:+d})"
                            for r in item.get("reasons", [])
                        ],
                    }
                    for item in result.get("candidates", [])
                ],
                "note": "Local signals, not a topic judgement. Pick a candidate; bounds stay on sentence boundaries.",
            }
        if action in ("get", "create", "update", "derive", "create_clip"):
            return _summarize(result)
        if action == "review" and isinstance(result, dict) and "project" in result:
            return dict(result, project=_summarize(result.get("project")))
        return result

    return _response(perform)


def job_handler(args, **kwargs):
    """Validate the job contract before resolving Studio."""

    def perform():
        action = _arguments(args, JOB_ACTIONS)
        studio_call = None
        if action == "submit":
            if args["operation"] not in JOB_OPERATIONS:
                raise ValueError(
                    "Unsupported operation; expected one of: "
                    + ", ".join(sorted(JOB_OPERATIONS))
                )
            options = args.get("options")
            if "options" in args and not isinstance(options, dict):
                raise ValueError("options must be an object")
            studio_call = (
                "submit",
                {
                    "project_id": args["project_id"],
                    "action": args["operation"],
                    "options": options,
                },
            )
        elif action == "list":
            studio_call = ("jobs", {"project_id": args.get("project_id")})
        elif action == "get":
            studio_call = ("job", {"job_id": args["job_id"]})
        else:
            studio_call = ("cancel", {"job_id": args["job_id"]})
        method, values = studio_call
        studio = get_studio()
        result = getattr(studio, method)(**values)
        if action in ("get", "submit"):
            result = _with_media(studio, result)
        return result

    return _response(perform)


def _string(description):
    return {"type": "string", "minLength": 1, "description": description}


def definitions():
    """Return the Hermes tool definitions without touching Studio."""
    changes = {
        "type": "object",
        "additionalProperties": False,
        "minProperties": 1,
        "description": "Editable project fields only (update). Approval, "
        "artifacts, source, revision and status cannot be changed here.",
        "properties": {
            "settings": {
                "type": "object",
                "description": "Render/model settings; settings.music is an optional local audio object (path, volume_db, fade_in, fade_out, duck, duck_db, loop, start_offset, source_note); settings.cut_sfx takes path and volume_db; assets are hashed into approval. settings.voice_cleanup is off/light/strong. settings.pacing sets punch-ins, push-ins, the longest pause and transitions; null removes it.",
                "properties": {
                    "pacing": {
                        "type": ["object", "null"],
                        "additionalProperties": False,
                        "description": "Pacing for short-form edits; ask the person "
                        "before turning it on. Defaults: punch_in off, cut transition, "
                        "no pause limit",
                        "properties": {
                            "punch_in": {
                                "type": "string",
                                "enum": ["off", "alternate"],
                                "description": "alternate: every other edit cut "
                                "zooms in on the face",
                            },
                            "punch_in_zoom": {
                                "type": "number",
                                "minimum": 1.05,
                                "maximum": 1.3,
                                "description": "Punch-in zoom, default 1.12",
                            },
                            "max_upscale": {
                                "type": "number",
                                "minimum": 1,
                                "maximum": 4,
                                "description": "Most total enlargement of the source "
                                "including framing, default 2; larger zooms are reduced",
                            },
                            "push_in": {
                                "type": "boolean",
                                "description": "Slow eased push-in over ranges of 4 s "
                                "or more",
                            },
                            "push_in_zoom": {
                                "type": "number",
                                "minimum": 1.02,
                                "maximum": 1.15,
                                "description": "Push-in end zoom, default 1.06",
                            },
                            "max_pause": {
                                "type": ["number", "null"],
                                "minimum": 0.2,
                                "maximum": 2,
                                "description": "Shorten pauses between kept words "
                                "to this many seconds; null keeps pauses",
                            },
                            "transition": {
                                "type": "string",
                                "enum": ["cut", "crossfade", "dip"],
                            },
                            "transition_duration": {
                                "type": "number",
                                "minimum": 0.04,
                                "maximum": 0.5,
                                "description": "Seconds, default 0.2; rendered as "
                                "2 to 12 frames",
                            },
                        },
                    },
                    "post": {
                        "type": "object",
                        "description": "Upload text only: title, caption, hashtags (array). Not part of video approval.",
                    },
                    "caption_style": {
                        "type": "string",
                        "enum": ["classic", "highlight", "pop", "one_word"],
                    },
                    "chapters": {
                        "type": ["array", "null"],
                        "maxItems": 100,
                        "description": "YouTube chapters in program seconds: first at "
                        "0, at least three, each at least 10 s. get() shows "
                        "longform.suggested_chapters and chapter_problems; suggest, "
                        "let the person edit the titles, then save; null removes",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["start", "title"],
                            "properties": {
                                "start": {"type": "number", "minimum": 0},
                                "title": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": 100,
                                },
                            },
                        },
                    },
                    "thumbnail": {
                        "type": ["object", "null"],
                        "additionalProperties": False,
                        "description": "16:9 YouTube thumbnail: frame at program "
                        "time (omit for a face-forward frame) and optional title text",
                        "properties": {
                            "time": {"type": ["number", "null"], "minimum": 0},
                            "text": {"type": ["string", "null"], "maxLength": 100},
                        },
                    },
                    "subtitles_file": {
                        "type": ["boolean", "null"],
                        "description": "Write captions.srt next to a YouTube video "
                        "(default true)",
                    },
                    "end_screen_s": {
                        "type": ["number", "null"],
                        "minimum": 5,
                        "maximum": 20,
                        "description": "Keep the last seconds free for a YouTube end "
                        "screen; QA warns about burned text there; null turns it off",
                    },
                    "caption_highlight_color": {
                        "type": ["string", "null"],
                        "pattern": "^#[0-9A-Fa-f]{6}$",
                        "description": "Highlight colour; null restores the default",
                    },
                    "caption_word_y": {
                        "type": ["number", "null"],
                        "minimum": 0,
                        "maximum": 1,
                        "description": "One-word vertical position in the safe "
                        "area (0 top, 1 bottom); null restores the default 0.8, below "
                        "a talking head's face",
                    },
                },
            },
            "brief": {"type": "string", "description": "Editorial brief"},
            "voice": {"type": "string", "description": "Narrative voice"},
            "excluded_word_ids": {
                "type": "array",
                "description": "Transcript word ids to cut",
            },
            "gaze_exclusions": {
                "type": "array",
                "description": "Time ranges excluded for gaze",
            },
            "selected_hook": {"description": "Chosen opening hook"},
            "segments": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Kept time ranges [{start, end}] in seconds",
            },
            "transcript": {
                "type": ["object", "null"],
                "description": "Corrected transcript",
            },
            "name": {"type": "string", "description": "Project display name"},
        },
    }
    project = {
        "name": "cutroom_project",
        "description": (
            "Manage Cutroom Studio projects. "
            + WORKFLOW
            + " Actions: create(source, name?) imports "
            "a local video; list() returns compact rows (id, name, revision, status, "
            "source, artifact kinds); get(project_id) returns the project with the "
            f"transcript summarized to word_count plus the first "
            f"{TRANSCRIPT_PREVIEW_WORDS} words to protect context; "
            "update(project_id, changes, revision) applies editable fields with "
            "optimistic revision checking (settings.platform selects a delivery "
            "profile, settings.final_resolution is '1080' or '2160'); "
            "review(project_id) returns the exact plan digest and notice for the "
            "human; derive(project_id, platform, name?, final_resolution?) creates a "
            "sibling project for another platform that copies the edit but starts "
            "unapproved at revision 1 with its own digest and the target "
            "profile's default final resolution unless final_resolution is given. "
            "find_clips(project_id, min_s?, max_s?, count?, platform?) finds whole-sentence "
            "20–90 s candidates with local scores and reasons (Shorts defaults to 60 s). "
            "create_clip(project_id, platform, candidate_id? or start/end?, name?) creates "
            "an unapproved derived project limited to that source range; typed bounds snap "
            "to sentence boundaries. Ask the person which clip to use. "
            + " post_text(project_id, post?) reads or saves upload copy; package(project_id, post?, cover_time?) makes local delivery files from a current approved final; packages(project_id) lists them; verify_package(project_id, package) checks checksums. Nothing is posted; never claim it was posted. "
            + APPROVAL_NOTICE
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create",
                        "list",
                        "get",
                        "update",
                        "review",
                        "derive",
                        "find_clips",
                        "create_clip",
                        "post_text",
                        "package",
                        "packages",
                        "verify_package",
                    ],
                    "description": "Operation to perform",
                },
                "post": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string", "maxLength": 1000},
                        "caption": {"type": "string", "maxLength": 20000},
                        "hashtags": {
                            "type": "array",
                            "maxItems": 100,
                            "items": {"type": "string", "maxLength": 100},
                        },
                    },
                },
                "cover_time": {"type": "number", "minimum": 0},
                "package": _string(
                    "Package folder name (verify_package); never an arbitrary path"
                ),
                "source": _string("Absolute local video path (create)"),
                "name": _string("Optional project name (create, derive)"),
                "project_id": _string("Project id (get, update, review, derive)"),
                "platform": {
                    "type": "string",
                    "enum": list(PLATFORMS),
                    "description": "Delivery profile of the new sibling (derive)",
                },
                "final_resolution": {
                    "type": "string",
                    "enum": ["1080", "2160"],
                    "description": "Final resolution of the new sibling; defaults "
                    "to the target profile's default (derive)",
                },
                "min_s": {"type": "number", "minimum": 20, "maximum": 90},
                "max_s": {"type": "number", "minimum": 20, "maximum": 90},
                "count": {"type": "integer", "minimum": 1, "maximum": 20},
                "candidate_id": {
                    "type": "string",
                    "pattern": "^clip-[0-9]{1,10}-[0-9]{1,10}$",
                },
                "start": {"type": "number", "minimum": 0, "maximum": 10800},
                "end": {"type": "number", "minimum": 0, "maximum": 10800},
                "changes": changes,
                "revision": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Current project revision (update)",
                },
            },
        },
    }
    job = {
        "name": "cutroom_job",
        "description": (
            "Run and track background Cutroom Studio jobs. "
            + WORKFLOW
            + " Actions: submit(project_id, operation, options?) queues inspect, "
            "transcribe, silence, vision, segment, storyboard, preview, final, "
            "cover or qa; list(project_id?), get(job_id), cancel(job_id). A "
            "completed preview, final or cover includes media (absolute path, "
            "platform, duration, size, qa status pass/warning/fail, approved) "
            "and display_hint: show the file with a line MEDIA:<path>. QA "
            "'warning' means ready with notes; only 'fail' needs changes. The "
            "cutroom:edit-video skill has the full workflow. " + APPROVAL_NOTICE
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["submit", "list", "get", "cancel"],
                    "description": "Operation to perform",
                },
                "project_id": _string("Project id (submit, optional filter for list)"),
                "job_id": _string("Job id (get, cancel)"),
                "operation": {
                    "type": "string",
                    "enum": sorted(JOB_OPERATIONS),
                    "description": "Studio pipeline step to queue (submit)",
                },
                "options": {
                    "type": "object",
                    "description": "Operation-specific options (submit)",
                },
            },
        },
    }
    return [project, job]


HANDLERS = {"cutroom_project": project_handler, "cutroom_job": job_handler}
