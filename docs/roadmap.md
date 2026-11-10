# Remaining work packages

Use these as parallel work boundaries. A work package is complete only when its acceptance scenario passes through the public interface, not merely a helper function.

## P1 — Wire the Studio engine

- Route speech, silence, vision, segmentation, storyboard, preview, final, cover and QA actions.
- Apply successful results transactionally to the matching project revision.
- Reject changed source/assets and stale queued/running results.
- Make running cancellation terminate only the owned worker subtree and clean partial artifacts.
- Prove queued jobs survive caller exit and recover explicitly after a crash.

Acceptance: import -> transcribe -> select words -> preview -> exact revision approval -> final + subtitles + cover + QA, all through the Studio facade.

## P2 — Complete the Desktop workflow

- Add job action controls, progress, cancellation, failure detail and retry.
- Add source/preview/final playback using the existing authenticated chunk route.
- Add a review summary and explicit confirmation for the exact current digest.
- Reconcile every artifact kind and settings key with the facade.
- Add graphic/background selection, caption editing and persistent brand corrections.

Acceptance: complete the same P1 scenario from the native page; verify it in a real Desktop window, not only mocked SDK tests.

## P3 — Package and model setup

- Provide explicit, reproducible dependency/model setup and health diagnostics.
- Preserve Desktop/dashboard assets in native plugin distribution.
- Test supported platforms/interpreters and document unsupported filesystems/codecs.
- Exercise a fresh install and uninstall without modifying unrelated profiles.

## P4 — Optional integration acceptance

- Finish adapter documentation and expose configuration/consent controls.
- Exercise real media download with attribution and redirect protection.
- Exercise OBS start/stop with a real local recording, without recording unrelated content.
- Exercise rclone against an explicitly selected remote and verify the resulting object.
- Keep local ICS export distinct from a live calendar write.
- Never call a mocked external interaction a live integration pass.

## P5 — Creative and editorial quality

- The current hooks/captions are extractive drafts, not a personalized writing engine. Add explicit voice/brand examples and reviewable writing if the user wants that behavior.
- Validate silence/filler cuts on more than one short reference recording and multiple languages.
- Review segmentation edges and head-facing estimates on real consented creators.
- Extend graphics beyond the existing title/lower-third effects where required.
- Retain honest limits: models cannot guarantee perfect eye contact or detect every one-frame visual defect.

## P6 — Release gate

- Close every applicable criterion in `ACCEPTANCE.md` with reproducible evidence.
- Security review, full tests, native UI exercise and catalog validation.
- Record a truthful demo shorter than 90 seconds.
- Confirm public visibility, then prepare the pinned catalog PR and official submission separately.

Do not replace this scope with an MVP completion claim. Partial module success remains partial until integrated.
