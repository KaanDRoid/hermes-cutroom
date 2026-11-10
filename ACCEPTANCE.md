# Full workflow acceptance

A capability is complete only after its input, implementation, output and observed checks are linked. External-account integrations remain unverified until exercised with a connected account and explicit consent; adapters alone do not establish completion.

| ID | Capability | Acceptance |
|---|---|---|
| A01 | Local import and projects | Immutable source fingerprint, resumable project, no overwrite |
| A02 | Word transcription | Real local Whisper inference, timed words, explicit model setup, no-audio handling |
| A03 | Text and filler edits | Word selection maps to source ranges; filler suggestions require review |
| A04 | Face, gaze and mouth | Real landmark inference, frame/time scores, confidence limitations, no-face handling |
| A05 | Person background removal | Real segmentation mask and behind-subject composite, no-person handling |
| A06 | Hooks and script voice | Three editable hook/storyboard options derived from supplied transcript/brief; never invented factual claims |
| A07 | Brand persistence | Validated fonts/colors/safe areas/templates and saved corrections |
| A08 | Media references | Explicit download consent, safe URL/redirect checks, attribution records |
| A09 | Graphics and subtitles | Real timed captions and title/graphic layers, local render |
| A10 | Real screen recording | Explicit OBS start/stop adapter and actual recording path verification |
| A11 | Preview and final | Distinct approved 1080 preview and 4K final, no silent upscaling claim |
| A12 | Cover and caption | Actual image output plus editable publication caption |
| A13 | Pre/post render QA | Dimensions/duration/audio/safe area/text and every-frame anomaly scan with honest heuristic limits |
| A14 | Human checkpoints | Reviewed exact revision before final render/download/publish; no model-exposed approval shortcut |
| A15 | Desktop studio | Native SDK-only UI for import, progress, transcript edits, preview, explicit confirmation and export |
| A16 | Storage and calendar | Optional explicit-consent rclone upload and calendar/ICS outputs; live services separately verified |
| A17 | Recovery and portability | Job errors/cancellation, dependency diagnostics, tests, package and plugin validation |
| A18 | Demo and submission | Truthful under-90-second demo; catalog PR/form/publication require separate authorization |

## Consented acceptance source

`raw_vids/12511-239934660.mp4`: 3840×2160, approximately 22.37 s, no audio stream, landscape/river aerial footage. This source cannot validate speech recognition, human gaze or person segmentation. Keep raw media, model caches and generated artifacts out of version control.
