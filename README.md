# Cutroom

A local-first video editing studio for Hermes Agent.

Cutroom turns a local recording into a reviewable edit: word-timed transcript cuts and filler review, silence removal, face/gaze/mouth review, person segmentation for graphics behind the subject, three source-quoted hook options with a storyboard, a preview render, a human-approved final export, a cover and automated quality checks. Media and models stay on your machine, and source files are never overwritten.

It ships three surfaces:

- **Hermes Desktop Studio page** — import, edit words, captions and ranges, pick a hook, run jobs, play previews, review the exact digest and approve the final export.
- **Agent tools** — `cutroom_project` and `cutroom_job` let Hermes create projects, edit settings and run allowlisted background jobs. There is no approval tool: only a person can approve a final export.
- **CLI** — `cutroom doctor`, `cutroom setup-models` and the plan-file commands below.

See the [documentation index](docs/README.md), [Studio jobs](docs/studio-jobs.md) and [current status](docs/status.md) for exact contracts and limits.

## Studio workflow

1. `transcribe` (local faster-whisper) → review fillers and exclude words.
2. `silence` → trims pauses while preserving manual cuts.
3. `storyboard` → three hook options quoted from the transcript; choose one, run again for scenes.
4. `vision` (MediaPipe face landmarks) → review-only gaze/mouth intervals. `segment` → person layer to place graphics or a background behind the subject.
5. `preview` → a fast render with word-timed captions and SRT/VTT sidecars.
6. Human review and approval of the exact digest in the Desktop Studio page.
7. `final`, `cover`, `qa` (resolution, decode, black/freeze frames, timing, loudness, clipping, captions, safe area).

Every job is bound to the project revision and its input files. Edits revoke approval and unlink stale renders; published files carry SHA-256 lineage.

## Models

Nothing is downloaded automatically. `cutroom setup-models DIR` prints the pinned URLs and SHA-256 values; add `--confirm-downloads` to fetch them over HTTPS with size limits and no-overwrite installation. `cutroom doctor --models-dir DIR` checks FFmpeg, the runtime interpreter, optional packages and model hashes. Advanced modules need the optional Python dependencies described in [development setup](docs/development.md).

## Plan-file core

The original plan-file workflow remains available for simple silence edits.

## Requirements

- Hermes Agent 0.23.0 or later for native tool registration.
- Python 3.11+.
- `ffmpeg` and `ffprobe` in PATH, with `libx264` and AAC encoding support.
- A local video file. The core needs no API keys or Python runtime dependencies; advanced modules use the optional environments described in [development setup](docs/development.md).
- An output filesystem with hard-link support (for example NTFS or ext4), used for atomic no-overwrite publication. FAT/exFAT outputs are not currently supported.

Verified on native Windows with FFmpeg 9.0.2; CI runs the test suite on Windows and Ubuntu.

## Quick start

From this checkout:

```bash
python -m cutroom inspect /absolute/path/recording.mp4
python -m cutroom draft /absolute/path/recording.mp4 /absolute/path/new-project
```

Open `new-project/review.html` in your local browser. It shows the source, a keep/remove timeline, and the source-time ranges to retain. This is a plan review, not a rendered edited-video preview. Listen around every proposed cut.

The draft is editable JSON. After changing `plan.json`, regenerate its review:

```bash
python -m cutroom review /absolute/path/new-project/plan.json
```

The review prints an exact digest. Confirm it from your terminal:

```bash
python -m cutroom approve /absolute/path/new-project/plan.json --digest <reviewed-digest>
python -m cutroom render /absolute/path/new-project/plan.json
```

The result is `new-project/render.mp4`. Existing outputs are rejected rather than overwritten. A changed plan or source invalidates the approval. Create a fresh project for another export in this initial version.

Optional installation as a standalone CLI: `python -m pip install .` using the same Python interpreter as your environment. No installation is needed for the commands above.

## Hermes plugin

The root `plugin.yaml` and `__init__.py` implement the documented native plugin contract. Validate this directory with:

```bash
hermes plugins doctor /absolute/path/hermes-cutroom --ci
hermes plugins validate /absolute/path/hermes-cutroom --install-deps
```

For local development, link this directory as `<active-HERMES_HOME>/plugins/cutroom`, then explicitly enable `cutroom` using `hermes plugins enable cutroom`. Installing/enabling modifies the active profile; this checkout does not do that automatically.

| Tool | Behavior |
| --- | --- |
| `cutroom_inspect` | Read media dimensions, duration and audio availability |
| `cutroom_draft` | Detect silence, preserve configurable padding, save an editable plan and local HTML review |
| `cutroom_review` | Regenerate review and digest after plan edits |
| `cutroom_render` | Render the approved plan; reject stale approval and existing output |
| `cutroom_project` | Create, list, read, update and review Studio projects (no approval) |
| `cutroom_job` | Submit, list, read and cancel allowlisted Studio jobs |

There is deliberately **no approval tool**. Show the draft to the user and let them confirm locally. Receipts are an accidental-stale-render guard, **not** an authenticated approval mechanism: another program with filesystem access can write receipts. Do not describe them as a security sandbox.

## Editing semantics

- Silence threshold: -35 dB, minimum silence: 0.5 seconds, speech-side padding: 0.12 seconds by default.
- Cuts use source timestamps, not word boundaries. Silence detection cannot distinguish hesitation from intentional pauses.
- No-audio video keeps its full duration.
- Audio/video are trimmed together and re-encoded to H.264/AAC MP4. This is not lossless editing.
- Only the selected primary video/audio streams are used; extra tracks, chapters and subtitle tracks are not a preservation feature.
- Path-based local media only; URL/network imports are out of scope.
- Each run creates a separate directory. Plan and SHA-256 source fingerprints make accidental changes detectable.

## Data and permissions

The plugin reads the video path explicitly supplied, launches local FFmpeg/ffprobe subprocesses, and writes only the requested new project and its render artifacts. It does not send media anywhere, read credential stores, update itself, alter Hermes core, or attach global hooks. FFmpeg is an external executable the user supplies. A malicious media file can exploit a vulnerable decoder: use a maintained FFmpeg build and only process trusted files. Local protocols are restricted; this is defense in depth, not an OS sandbox.

## Current boundaries

Hooks, storyboards and captions are extractive drafts from your own transcript, not generated writing. Gaze is a heuristic for review, not an automatic cut. Background separation uses MediaPipe person segmentation, not SAM. Optional download, OBS, rclone and calendar adapters are consent-gated and not part of the Studio pipeline; they have not been accepted against live services. Verified primarily on Windows. See [current status](docs/status.md) and [remaining work](docs/roadmap.md).

## Tests

```bash
python -m unittest discover -s tests -v
```

Media tests generate clearly identified synthetic tone/color fixtures and run real FFmpeg/ffprobe. Synthetic fixtures test mechanics; they are not evidence of quality on real speech. Use a consented recording to assess editorial quality.

## License

MIT. FFmpeg is supplied separately and has its own license obligations.
