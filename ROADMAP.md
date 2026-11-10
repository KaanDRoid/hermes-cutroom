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

## Submission gate

- Validate and test the pinned plugin commit.
- Review external FFmpeg/model dependencies and disclose local writes and subprocess execution.
- Choose final name and license; the current name and MIT license are provisional.
- Obtain approval before creating a public repository or uploading any footage.
- Open the catalog PR with a full commit pin.
- Record a truthful working demo; do not portray synthetic fixtures as creator footage.
- Submit the PR and demo links using the official form.

Nothing is published by this checkout.
