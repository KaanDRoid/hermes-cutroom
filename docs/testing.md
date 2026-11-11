# Testing and acceptance

## Evidence levels

1. Unit/contract tests: timestamp algorithms, validation, schema and adapter behavior.
2. Subprocess/media tests: actual FFmpeg/ffprobe transforms, codecs, dimensions, output duration and pixels.
3. Model acceptance: actual local Whisper or MediaPipe inference using explicitly identified inputs.
4. Studio acceptance: the facade routes actions, persists correct results and rejects stale work.
5. Desktop acceptance: the native page completes the workflow in the real application.
6. External acceptance: a consented account/application operation is performed and read back.

Passing one level does not imply the others passed.

## Input coverage

- Synthetic tone/color fixtures test mechanics and must remain labeled synthetic.
- The official whisper.cpp `jfk.wav` sample tests real speech recognition; it is not speech from either user video.
- The consented landscape clip has no audio and no visible person.
- The consented portrait clip has a visible woman and mouth motion, but no audio stream.
- Local model/media fixtures are intentionally absent from Git and may cause acceptance tests to skip on fresh clones.

## Running

See [development](development.md) for environment setup. `CUTROOM_TEST_USER_MEDIA=1` opts into the additional consented-media preview/cover/QA test. Never set this variable against someone else's recordings without permission.

```bash
python -m unittest discover -s tests -v
node --test tests/desktop-check.mjs
```

The full local model suite uses the dedicated Python 3.12 runtime. The core can be checked separately under the Hermes interpreter. Logs and output media stay in `artifacts/` or temporary directories, not Git.

## Important limits

- Head-facing scores are uncertain geometry proxies, not verified eye contact.
- Segmentation can fail around hair, glasses, objects and unfamiliar scenes.
- Black/freeze/signal/timing/audio checks are measurable heuristics, not a guarantee that no one-frame defect exists.
- A local ICS file is not a created Google/Outlook event.
- A mocked OBS/rclone/download contract is not live service acceptance.
- A recorded terminal job status does not by itself prove worker exit, crash recovery or caller-exit durability.

Release is blocked until every applicable row of `ACCEPTANCE.md` has the right proof level.

## Deferred transcription acceptance

This pass deliberately implements routing with focused mechanical checks and leaves extensive testing for later. Nothing below is claimed complete by the contract fixtures in `test_studio_transcription.py`.

- [ ] Set up the pinned speech dependencies in a repo-local supported runtime and obtain verified/licensed local Whisper assets under `models/`. Keep any package/model caches inside this checkout. No model was downloaded for the routing work.
- [ ] Run real speech end to end through `Studio.submit(..., "transcribe")`, first with the attributed JFK reference, then with a short explicitly consented English/Turkish recording. Verify actual words, source-time boundaries and recognition limitations by listening; synthetic tones do not substitute for speech.
- [ ] Prove inference remains offline and does not consult credential stores or remote model services.
- [ ] Exercise language detection and supported explicit codes, empty recognitions on audio-bearing silence, overlapping/zero-duration word boundaries, Unicode and filler false positives. Confirm suggestions never become automatic edits.
- [ ] Exercise repeated retranscriptions after word/manual/silence/gaze edits, including a simultaneous direct transcript/word-selection update. Verify old ranges survive, new IDs are not mistaken for old IDs and preserved cuts can be intentionally restored only through explicit range editing.
- [ ] Test real model/source/asset changes while queued and running, including optional model assets added/removed/replaced and model-path aliases. Results must not publish against changed inputs.
- [ ] Cancel real jobs during decoder startup, model loading and inference; verify owned processes exit and unrelated processes survive. Exercise caller exit, supervisor crash, restart and the gap between project publication and job completion. The existing runtime subtree check is not proof of each of these phases.
- [ ] Measure memory, model-load and inference latency on long recordings. Include the cost of hashing model assets while holding the workspace lock and verify project size/write bounds for large transcripts and filler lists.
- [ ] Exercise REST and the eventual native Desktop action controls with real transcript edits, approval invalidation and stale artifact rejection. Preview/final/subtitle integration remains a separate action-routing task.
- [ ] Run the supported Linux/Windows runtime matrix and compare the final full suite with the recorded baseline. Keep the local FFmpeg 7.1 export-duration defect separate from transcription results.

Store recordings in ignored `raw_vids/`, models in ignored `models/`, and evidence/temp files under ignored `artifacts/`. Never upload creator media as part of acceptance without explicit permission.
