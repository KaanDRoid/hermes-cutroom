# Implementation status

## November 11 integration checkpoint — supersedes the historical snapshot below

- Studio now routes every editing job: inspect, transcribe, silence, vision, segment, storyboard, preview, final, cover and qa. Results are revision-bound; stale renders are unlinked and final export requires current human approval.
- Six agent tools are implemented, including `cutroom_project` and `cutroom_job`; no agent approval action is exposed.
- `cutroom doctor` and consent-gated `cutroom setup-models` are implemented. Six local model-file hashes match their pins.
- The public-facade harness produced a 2160×3840 reference final, cover and 14 passing QA checks, but it granted its own approval. This is **automated render evidence only, not human-approval acceptance**. Independent review rejected this harness behavior; its correction must stop at preview/review and resume only after separate human approval.
- Real portrait face analysis covered 264 frames; segmentation/compositing completed. Desktop SDK contract tests: 13 passed. Ruff checks pass.
- Integrated Python suite after review fixes: **189 tests, 186 passed, 3 skipped**, no failures (84.302 seconds). Independent re-review **passed**: automatic harness approval removed, publication hashes verified, downstream artifacts validated and derivatives bound to exact upstream identity. An earlier integrated run failed two dashboard alias fixture assertions; its stale QA fixture was updated to supply a valid render identity without weakening production validation. Native Desktop-window acceptance, fresh installation and external-service acceptance remain open. No live profile installation, repository visibility change or submission is authorized by this checkpoint.
- The older FFmpeg 7.1 duration/cover defect has a CFR-specific correction with a CFR/VFR regression; direct retest on 7.1 remains open (local FFmpeg is 9).

## Historical snapshot

Snapshot: November 10, 2026. The boundaries and counts below describe the earlier checkpoint, not the current integration.

## Working public core

The four registered Hermes tools and existing CLI support metadata inspection, silence-based draft plans, HTML review, exact-plan/source confirmation and real no-overwrite rendering.

## Advanced modules present

| Area | Observed boundary |
|---|---|
| Speech | Local CPU Whisper inference on the separately attributed JFK reference; timed words, exclusions, fillers, remapping and SRT/VTT/ASS exports |
| Narrative | Three extractive hook alternatives, selected-range storyboard and editable source-quote publication drafts; not personalized generative writing |
| Vision | Real MediaPipe face/mouth/head-facing inference on all 264 portrait frames; review-only heuristics |
| Segmentation | Actual local person-mask compositing, including graphics behind the subject; not SAM |
| Postproduction | Real preview/final dimension presets, title/lower-third/caption effects, covers, audio normalization and frame/signal/timing/audio checks |
| Integrations | Consent/validation and adapter-contract coverage; actual local ICS and publication-package writes; live OBS/cloud/calendar operations not accepted |
| Studio | Project persistence, revisions, digest review and background inspection; queued cancellation and facade reopening tests |
| REST | Strict request models, profile-aware sibling loading, bounded authenticated media chunks and facade artifact routes |
| Desktop | SDK route/sidebar/palette, import and editing forms, transcript/filler/hook/brand/vision controls; action/player/approval/job panels are not complete |

## Integration blockers

- The Studio and engine dispatchers execute `inspect`, `silence` and `transcribe`. Matching-revision publication preserves cuts and revokes approval; transcript replacement clears old word IDs while preserving their time-range cuts, recomputes filler suggestions and invalidates dependent artifact links. Transcription's audio-result application is contract-tested, not accepted with a real model through Studio yet. Other advanced module APIs are not a complete action pipeline. See [Studio jobs](studio-jobs.md) for current local evidence and an existing export-duration failure.
- Successful advanced results still need transactionally applied revision checks and artifact lineage.
- Running cancellation, caller-exit durability and crash recovery need complete integration tests.
- Native player/action/progress/review/approval controls need implementation and real Desktop acceptance.
- Native tooling/model acquisition needs a reproducible first-run setup flow.
- Graphic/voice/editorial functionality must be judged against the full accepted workflow, not the existence of helpers.
- External account/application operations require configuration, consent and read-back validation.
- No Marketplace entry, public demo or contest submission has been made.

## Verification

The transcription routing branch was tested locally with Python 3.11.15 and FFmpeg 7.1: **126 tests collected, 113 passed, 12 skipped, one pre-existing export/cover error**. Its six focused checks pass, including a real detached no-audio job and contract-tested audio-result application. All four Node Desktop contract tests and Ruff pass. Use `python scripts/check.py` to reproduce with generated files confined to `artifacts/`; see [Studio jobs](studio-jobs.md) for details. This is not a full-suite pass, real-model Studio acceptance or native Desktop acceptance. Extensive transcription testing is deferred to [the acceptance checklist](testing.md#deferred-transcription-acceptance).

### Original author checkpoint (different environment)

The original local Python 3.12 run reported **110 tests: 109 passed, 1 skipped, no failures**. This run enabled the consented-media preview/cover/QA test and exercised real local speech, face and segmentation models. The skipped check requires native Windows symlink-creation privileges; its controlled alias-resolution regression passes. Logs and media evidence remain local in `artifacts/`.

The earlier pre-fix run had two failures (display rotation and premature decoder-end coverage); both were reproduced and fixed. Additional regressions now cover manual-range preservation, canonical report/subtitle routes, resolved network-path rejection and metadata-only remote-upload verification. FFmpeg filter-script compatibility now selects the modern flag, with a narrowly tested legacy fallback.

Hermes Plugin Doctor passed. Catalog validation of a clean source-only checkout passed without warnings; the working-tree scan can additionally see ignored local model binaries, which are not part of the repository. GitHub Actions platform results must be read separately and are not implied by this local run.

Four Node Desktop contract tests pass. Ruff passes. Initial Linux CI exposed Windows-specific temporary-directory and default-font assumptions; the portability corrections retain the same assertions, prefer an installed approved font only for new defaults and never silently replace an explicitly selected family. Read the latest Actions run for platform results. These checks are not evidence of a complete native-user workflow.

See [remaining work](roadmap.md), [architecture](architecture.md) and [testing](testing.md) before claiming a feature is finished.
