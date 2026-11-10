# Architecture

## Current code map

| Location | Responsibility |
|---|---|
| `plugin.yaml`, root `__init__.py` | Native Hermes manifest and entry point |
| `cutroom/hermes_plugin.py` | Four currently registered core tools |
| `cutroom/media.py` | Local ffprobe, silence detection, trim/concat rendering |
| `cutroom/plan.py`, `project.py` | Legacy edit plans, HTML review and exact-plan receipts |
| `cutroom/speech.py` | Local transcription, word exclusions, filler suggestions, timeline remapping and subtitle files |
| `cutroom/narrative.py` | Extractive hook/storyboard/caption drafts grounded in timed source text |
| `cutroom/vision.py` | Face/head-facing/mouth review and person-layer compositing |
| `cutroom/postproduction.py` | Brand validation, preview/final export, covers and quality reports |
| `cutroom/integrations.py` | Consent-gated download, OBS, rclone, local package and ICS adapters |
| `cutroom/studio.py` | Versioned project persistence, revision checks, artifact access and job facade |
| `cutroom/job_worker.py` | Detached per-workspace job supervisor |
| `cutroom/runtime.py`, `worker.py` | Bounded isolated engine process and allowlisted engine entry point |
| `dashboard/plugin_api.py` | Profile-scoped REST facade and authenticated media chunks |
| `desktop/plugin.js` | Native SDK page, project import and editing forms |
| `tests/` | Unit, subprocess, media and adapter-contract checks |

## Two project formats

The working core uses `plan.json` and `approval.json` inside a caller-selected new project directory. The evolving Studio uses version-2 `studio.json` records under a workspace's `projects/<id>/` directory, plus `jobs/<id>/` records and snapshots.

Do not confuse these formats or imply that every advanced action is already routed. At this checkpoint, the Studio supervisor and engine dispatcher execute `inspect` and `silence`; other action routing remains an integration task. Silence results are applied under the state lock to matching revisions without restoring manual cuts; see [Studio background jobs](studio-jobs.md).

## Planned execution path

```text
Hermes tools / Desktop SDK
          |
Profile-scoped REST / Studio facade
          |
Revision-checked project + immutable source identity
          |
Detached job supervisor
          |
Optional Python 3.12 model runtime / FFmpeg
          |
Verified artifacts + project update + review checkpoint
```

Native dependencies stay in a dedicated runtime rather than being injected into Hermes's interpreter. Import and tool registration must not load models, execute media jobs or start network requests.

## Persistence and concurrency

Project and job JSON writes use temporary files and atomic replacement. Workspace locks serialize state updates. Revisions reject stale edits. Manual scene ranges remain the authoritative base; word-derived selections are intersected with that base before gaze exclusions are subtracted, so changing one exclusion field cannot silently restore manually removed footage. Windows sharing violations receive a short bounded retry; malformed content and permanent failures must not be swallowed.

Queued cancellation, facade reopening and a queued silence job surviving real submitter-process exit are tested. An isolated runtime test exercises real worker/FFmpeg subtree termination without killing an unrelated process, using a controlled test launcher. Crash recovery, complete running-action cancellation and artifact-lineage publication still need integration coverage. Project and job completion are separate atomic file replacements under one lock, not a crash-atomic transaction.

## Review and artifact safety

Final exports must bind approval to the current source, settings, edit ranges and relevant assets. Source changes invalidate the project. A review receipt is a consistency guard, not proof of a real human's identity. Keep approval out of model-facing tool schemas.

The REST backend accepts only facade-resolved artifact kinds; it does not offer an arbitrary file-read route. Canonical report/subtitle keys are `quality`, `captions_srt`, `captions_vtt` and `captions_ass`; legacy aliases map explicitly as `qa` -> `quality`, `captions` -> `captions_srt` and `subtitles` -> `captions_vtt`. Native media playback uses bounded authenticated JSON chunks to construct a local Blob URL, not credentials embedded in a video URL. The media player controls still need to be wired into the Desktop page.
