# What Cutroom is

Cutroom is a local-first video editing studio and native Hermes Agent plugin. Its purpose is to turn recordings into reviewable, reproducible edits without forcing creators to assemble a collection of unrelated scripts.

## Intended user journey

1. Import a local recording or explicitly approve a supported media download.
2. Inspect audio/video metadata and establish an immutable source fingerprint.
3. Transcribe speech locally with timed words; suggest silence and filler cuts.
4. Review face/head-facing and mouth-motion estimates, without silently discarding footage.
5. Review three source-grounded hook alternatives and a storyboard covering all selected scenes.
6. Edit word selection, scene ranges, brand rules, captions and optional graphic/background layers.
7. Render a smaller preview, inspect the result and make corrections.
8. Approve the exact current revision, then produce the final export, cover, subtitles and publication draft.
9. Review automated quality findings.
10. Optionally record real screen footage with OBS, upload approved outputs through rclone, and prepare a calendar event.

## Product principles

- Original media is not overwritten. Edits are source-time plans and reproducible settings.
- Local processing is the default. Model downloads are an explicit setup step.
- Filler cuts and head-facing scores are suggestions, not automatic editorial decisions.
- Gaze scores do not prove eye contact. Segmentation and anomaly detection are imperfect model/heuristic outputs.
- Digest receipts detect stale inputs or edits; they are not an authentication boundary against programs with filesystem access.
- External downloads, recording control and uploads require explicit consent.
- The implementation is model-provider independent at the plugin boundary.

## Technology choices

FFmpeg/ffprobe perform media operations. Optional faster-whisper supplies local word timestamps. MediaPipe supplies local face landmarks and selfie segmentation; the current implementation is not SAM. Titles, lower thirds and captions render through FFmpeg rather than depending on Remotion or CapCut. The Desktop surface uses only the public Hermes plugin SDK.

These choices implement functionality, not a promise to reproduce another creator's private skills, voice or brand assets.

## Completion boundary

The full requested workflow is the target, not merely the four-tool editing core. Current gaps are tracked in [status](status.md) and [roadmap](roadmap.md). Marketplace submission, public visibility and posting a demo are separate release actions.
