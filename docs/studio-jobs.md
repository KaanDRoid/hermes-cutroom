# Studio background jobs

The public Python facade currently executes **`inspect`, `silence` and `transcribe`**. Other accepted action names still fail as uninstalled operations; they are not completed workflows. Transcription routing is implemented, but real-model Studio acceptance is deferred; contract tests are not evidence of recognition accuracy.

## Silence selection

```python
import time
from cutroom.studio import Studio

studio = Studio("/absolute/path/to/new-workspace")
project = studio.create("/absolute/path/to/local-recording.mp4")
job = studio.submit(project["id"], "silence", {
    "noise_db": -35.0,
    "min_duration": 0.5,
    "padding": 0.12,
})
while job["status"] not in {"completed", "failed", "cancelled"}:
    time.sleep(0.1)
    job = studio.job(job["id"])
if job["status"] != "completed":
    raise RuntimeError(job["error"])
project = studio.get(project["id"])
print(project["revision"], project["segments"])
```

The job runs FFmpeg through the isolated engine runtime. Only the three options above are accepted. Values must be finite numbers (not booleans); minimum duration must be positive and padding non-negative. Defaults match the core draft workflow. Job options cannot substitute a different source.

On success, detected keep ranges are intersected with existing manual base ranges; existing timed-word and gaze exclusions are reapplied. No manually removed footage is restored. The resulting selection must remain nonempty and pass plan validation. A no-audio source retains its current selection. A successful job increments the project revision, resets its status to `draft`, removes approval and records `applied_revision` in the job. The job's `result` is the detected full-source plan, **not** the final intersection with the project's other selections; read the project for the applied ranges.

Source identity, project revision, asset digest and cancellation are checked under the workspace state lock before execution and again before publication. Stale, cancelled or invalid results do not change the selection. Source media is never written. Cancellation is forwarded to the isolated runtime. A controlled launcher test exercises real worker/FFmpeg subtree termination while leaving an unrelated process alive; complete running-action cancellation still needs facade acceptance. A separate subprocess test proves a queued silence job survives its submitter exiting.

## Transcription and text editing

For media with an audio stream, first set an existing local model directory and, optionally, a dedicated runtime interpreter:

```python
project = studio.update(project["id"], {"settings": {
    "whisper_model": "/absolute/path/to/repo/models/whisper-tiny",
    # "runtime_python": "/absolute/path/to/repo/.venv/Scripts/python.exe",
}}, project["revision"])
job = studio.submit(project["id"], "transcribe", {"language": "en"})
# Poll job status as above, then reload the current project before editing.
```

The only job option is `language`: a lowercase two/three-letter code or `None` for detection. Source, model and runtime paths come from the project snapshot, not job-option overrides. Unknown language codes that match the format can still be rejected by the inference library.

Required local assets are `config.json`, `model.bin` and `tokenizer.json`. Present optional `vocabulary.txt`, `vocabulary.json` and `preprocessor_config.json` are validated too. Recognized model files are fingerprinted at submission and checked again before execution and before publication. Missing, empty, escaped or changed model assets fail closed; no download is attempted. A no-audio video requires no model and completes with an empty `no_audio` transcript.

On success, the validated transcript is saved in the project with review-only `transcript.fillers`, the revision advances and approval is removed. The raw inference transcript remains in the job result, and `applied_revision` links it to the project. Neither first transcription nor retranscription automatically removes filler candidates.

### Replacement policy

Both a new `transcribe` job and a direct `Studio.update(..., {"transcript": ...}, revision)` use the same replacement policy:

- Preserve existing word-derived cuts as source-time `base_segments` before clearing old `excluded_word_ids`. Reused numeric IDs never silently exclude different words, and old removals are not silently restored.
- Keep gaze exclusions separate and reversible. Manual/silence base ranges remain authoritative.
- Recompute filler suggestions for the new words. An explicitly supplied `excluded_word_ids` field in the same direct update refers to the new transcript.
- Clear old story/hook selection and links to transcript-dependent preview/final/cover/subtitle/quality/storyboard/caption/package artifacts. Files are not deleted. This is targeted invalidation, not a full artifact-lineage implementation.
- Record `transcript_update.preserved_word_cuts` and `cleared_word_ids` in successful transcription jobs. To restore baked word cuts later, explicitly edit the base ranges via `segments`; merely rechecking a new word cannot restore them.

The resulting selection must remain valid and nonempty before anything is written. Stale, cancelled, changed-model or invalid results leave the previous project intact.

## Limits

- This is a Python facade workflow, not a completed native Desktop or advanced CLI workflow.
- Real-model transcription acceptance, preview/final export and other advanced action routing remain open.
- Applying project state and completing a job are separate atomic JSON replacements under one lock, **not** a crash-atomic multi-file transaction. Recovery from a crash between those writes remains a P1 task.
- Artifact lineage and invalidation across edits still need the broader P1 implementation.
- Synthetic tone/silence fixtures prove mechanics, not editorial quality on human speech.

## Local verification

With Python 3.11.15 and FFmpeg 7.1 on Windows:

```bash
python -m unittest discover -s tests -p test_studio_silence.py -v
```

Nine silence tests pass, covering real isolated detection, persisted background application, option rejection, stale queued work, no-audio media, manual/word/gaze selection preservation, empty-intersection rollback, deterministic publication races and real submitter-process exit. The race test mocks inference and launch; the separate runtime test substitutes a controlled launcher but uses a real worker/FFmpeg subtree.

For all local quality gates, run `python scripts/check.py` with the development interpreter. It sets `TMPDIR`, `TEMP`, `TMP` and Python's temporary directory to `artifacts/tmp`, and writes raw Python/Node/Ruff logs plus an exact `summary.json` under `artifacts/checks/<run-id>/`. A failed or skipped check is not disguised as a pass.

Six focused transcription checks pass: worker dispatch, bad-option/missing-model rejection, validated persistence and filler generation, safe job/direct replacement, invalid/stale/model-change/cancellation rejection, and a real no-audio detached job. Audio transcript application is contract-tested using clearly labeled fixtures, not a real Whisper model.

The transcription branch's local suite collected **126 tests: 113 passed, 12 skipped and one existing error**. Ruff and all four Node Desktop contract tests pass; no new native Desktop acceptance or branch CI result is implied. Skips include missing native models/consented media and unavailable Windows symlink privileges. Extensive transcription acceptance is deliberately deferred; see [the pending checklist](testing.md#deferred-transcription-acceptance).

### Existing export-duration defect

`test_final_portrait_and_real_safe_area_cover` raises `Cover time must precede end of video`; the same error was present in the pre-change 110-test baseline. Further synthetic reproduction with local FFmpeg 7.1 shows that `export_video` reports a 0.1-second MP4 for a requested 0.2-second, 10-fps selection. `ffprobe -show_frames` decodes only the first frame despite the stream declaring two frames; the cover request at 0.1 seconds therefore falls at the incorrectly shortened end. This is not fixed by relaxing the cover bounds check. Forcing a constant output frame rate fixes that fixture but can alter variable-frame-rate media, so it has not been applied as an unreviewed export-semantics change. Reproduction scripts and media are local in ignored `artifacts/`, and the original failing acceptance test remains enabled.
