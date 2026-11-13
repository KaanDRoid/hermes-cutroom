# Cutroom roadmap

The accepted target is the full creator workflow. The current work breakdown is maintained in [docs/roadmap.md](docs/roadmap.md), and the current implementation boundary is in [docs/status.md](docs/status.md). The notes below describe the original sequencing, not a reduction of the accepted scope.

## Working core

- Native Hermes tool registration through documented APIs.
- Local FFmpeg metadata, silence detection and non-destructive source-time plans.
- HTML plan review, exact-plan/source fingerprints and explicit local confirmation.
- Real H.264/AAC render with no-overwrite publication.

## Original implementation sequence

1. Creator talking-head recordings as the first target.
2. Local word-timestamp transcription as an optional dependency, with an explicit model download prompt.
3. Transcript-driven cut review: deleted text maps to precise source ranges.
4. Subtitle export and one configurable portrait caption preset.
5. A native Hermes Desktop review pane, using only the Desktop SDK and a documented plugin backend.
6. One consented real recording for editorial acceptance and a demo shorter than 90 seconds.

The exact-plan receipt is a consistency guard, not user authentication. A native confirmation action should stay outside model-exposed tools.

## Full workflow integration

Face/head-facing review, person segmentation, graphic layers, explicit-consent media import, OBS recording and optional storage/calendar adapters are included in the accepted scope. They must be integrated and verified, not merely listed as helpers. See the current work packages linked above.

## Later: GPU acceleration (deferred)

Everything runs on the CPU today. Measured on an RTX 5060 Laptop GPU
(2026-11-13, 60 s of the Sandra interview):

- Encoding at 1080p: libx264 5.0 s, h264_nvenc 2.1 s. NVENC ships with the
  bundled FFmpeg builds. Plan: use it when present, fall back to libx264 on
  any failure, and choose its quality setting by comparing output, since
  NVENC needs more bits for the same quality.
- Transcription with whisper-small: CPU int8 8 s. CUDA failed because the
  CUDA 12 cuBLAS/cuDNN libraries (about 1 GB) are not installed; support for
  RTX 50 series cards is unverified. Plan: an opt-in "Use the GPU" setting,
  with the libraries installed only after the person agrees.
- Face analysis (MediaPipe) has no GPU path on Windows and stays on the CPU.

## Submission gate

- Validate and test the pinned plugin commit.
- Review external FFmpeg/model dependencies and disclose local writes and subprocess execution.
- Choose final name and license; the current name and MIT license are provisional.
- Obtain approval before creating a public repository or uploading any footage.
- Open the catalog PR with a full commit pin.
- Record a truthful working demo; do not portray synthetic fixtures as creator footage.
- Submit the PR and demo links using the official form.

Nothing is published by this checkout.
