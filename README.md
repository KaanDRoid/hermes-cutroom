# Cutroom

Local-first, non-destructive video editing for Hermes Agent.

**Development checkpoint, not a finished release.** Start with the [documentation index](docs/README.md), [current status](docs/status.md) and [collaboration guide](docs/collaboration.md).

Turn a local recording into an inspectable edit plan, review every cut, then render exactly that plan with FFmpeg. Source media stays local and is never overwritten. This is an early working core, not a complete video editor.

## Requirements

- Hermes Agent 0.23.0 or later for native tool registration.
- Python 3.11+.
- `ffmpeg` and `ffprobe` in PATH, with `libx264` and AAC encoding support.
- A local video file. The core needs no API keys or Python runtime dependencies; advanced modules use the optional environments described in [development setup](docs/development.md).
- An output filesystem with hard-link support (for example NTFS or ext4), used for atomic no-overwrite publication. FAT/exFAT outputs are not currently supported.

Verified on native Windows with FFmpeg 9.0.2 and Python 3.14. Other platforms are not yet exercised.

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

Advanced speech, vision, rendering and optional-integration modules now exist, with their own tests. They are **not yet a completed end-to-end Studio**: advanced job routing, native playback/action/approval controls, fresh-install acceptance and live external-service acceptance remain open. Hooks and captions are extractive drafts, gaze is a heuristic, and background removal uses MediaPipe rather than SAM. See [current status](docs/status.md) and [remaining work](docs/roadmap.md) for the exact boundary.

## Tests

```bash
python -m unittest discover -s tests -v
```

Media tests generate clearly identified synthetic tone/color fixtures and run real FFmpeg/ffprobe. Synthetic fixtures test mechanics; they are not evidence of quality on real speech. Use a consented recording to assess editorial quality.

## License

MIT. FFmpeg is supplied separately and has its own license obligations.
