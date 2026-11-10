# Implementation status

Snapshot: November 10, 2026. This is a development checkpoint, not a complete release.

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

- The Studio and engine dispatchers currently execute `inspect` only. Advanced module APIs are not yet a complete action pipeline.
- Successful advanced results still need transactionally applied revision checks and artifact lineage.
- Running cancellation, caller-exit durability and crash recovery need complete integration tests.
- Native player/action/progress/review/approval controls need implementation and real Desktop acceptance.
- Native tooling/model acquisition needs a reproducible first-run setup flow.
- Graphic/voice/editorial functionality must be judged against the full accepted workflow, not the existence of helpers.
- External account/application operations require configuration, consent and read-back validation.
- No Marketplace entry, public demo or contest submission has been made.

## Verification

The final local Python 3.12 run collected **108 tests: 107 passed, 1 skipped, no failures**. This run enabled the consented-media preview/cover/QA test and exercised real local speech, face and segmentation models. The skipped check requires native Windows symlink-creation privileges; its controlled alias-resolution regression passes. Logs and media evidence remain local in `artifacts/`.

The earlier pre-fix run had two failures (display rotation and premature decoder-end coverage); both were reproduced and fixed. Additional regressions now cover manual-range preservation, canonical report/subtitle routes, resolved network-path rejection and metadata-only remote-upload verification. FFmpeg filter-script compatibility now selects the modern flag, with a narrowly tested legacy fallback.

Hermes Plugin Doctor passed. Catalog validation of a clean source-only checkout passed without warnings; the working-tree scan can additionally see ignored local model binaries, which are not part of the repository. GitHub Actions platform results must be read separately and are not implied by this local run.

Four Node Desktop contract tests pass. Ruff passes. These are not evidence of a complete native-user workflow.

See [remaining work](roadmap.md), [architecture](architecture.md) and [testing](testing.md) before claiming a feature is finished.
