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
