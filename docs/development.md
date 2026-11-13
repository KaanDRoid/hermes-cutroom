# Development setup

## Prerequisites

- Git and access to the private repository.
- Python 3.12 for the tested native-model runtime; the dependency-free core also runs on Python 3.14.
- `uv`, Node.js 20+ and maintained `ffmpeg` / `ffprobe` executables in PATH.
- FFmpeg with H.264/AAC, libass and drawtext support. FFmpeg 9.0.2 is the local reference build; CI checks its own installed build.
- An output filesystem with hard-link support, such as NTFS or ext4. FAT/exFAT output is not currently supported.

## Clone and install

```bash
git clone https://github.com/KaanDRoid/hermes-cutroom.git
cd hermes-cutroom
uv venv --python 3.12
uv pip install --python .venv/Scripts/python.exe -e ".[dev,speech,vision,integrations]"
```

The command above uses the Windows interpreter path. On Linux/macOS, replace it with `.venv/bin/python`.

For tests without native models, installing `.[dev]` is enough. The advanced runtime and core should not share an environment unless their native dependencies are compatible.

## Test commands

For a repository-contained run with exact result counts and saved logs:

```bash
.venv/Scripts/python.exe scripts/check.py
```

Use `.venv/bin/python` on Linux/macOS. The runner confines temporary files to `artifacts/tmp` and writes evidence to `artifacts/checks/<run-id>/`. It runs the full Python suite, Node contract tests, Ruff and `git diff --check`; it exits nonzero if any gate fails. Native-model/media skips remain visible in `summary.json`. Keep development environments, test media, temporary files and logs inside this checkout; do not scatter generated files into sibling project directories or the system temp directory.

For individual manual commands, set a valid temporary directory first. In Git Bash on Windows:

```bash
export TMPDIR="$PWD/artifacts/tmp"
mkdir -p "$TMPDIR"
.venv/Scripts/python.exe -m unittest discover -s tests -v
node --test tests/desktop-check.mjs
uvx ruff check cutroom dashboard tests
```

Use a native absolute Windows TMPDIR path if the shell's `/c/...` path is not recognized by Python. On Linux/macOS use `.venv/bin/python`.

Real model tests skip if their local models or consented footage are absent. A skip is not an acceptance pass. See [testing](testing.md).

## Existing core workflow

```bash
python -m cutroom inspect /absolute/path/source.mp4
python -m cutroom draft /absolute/path/source.mp4 /absolute/path/new-project
python -m cutroom review /absolute/path/new-project/plan.json
python -m cutroom approve /absolute/path/new-project/plan.json --digest <reviewed-digest>
python -m cutroom render /absolute/path/new-project/plan.json
```

Open the generated HTML review before approving. These are the existing core commands; do not assume advanced Studio CLI commands exist yet.

## Native models

Models are not committed or downloaded by ordinary inference. Place verified local assets at:

```text
models/whisper-tiny/{config.json,model.bin,tokenizer.json,vocabulary.txt}
models/face_landmarker.task
models/selfie_segmenter.tflite
```

The tested Whisper source is `Systran/faster-whisper-tiny`. It is fast and enough for tests, but it can invent or drop short words; for editing by words use `Systran/faster-whisper-small` (see [where a removed word is cut](studio-jobs.md#where-a-removed-word-is-cut)). FaceLandmarker and selfie ImageSegmenter assets come from the official MediaPipe model bucket. The model configuration/setup UX and reproducible downloader remain release tasks; do not copy a private cache or redistribute model files without checking their licenses.

## Hermes validation

```bash
hermes plugins doctor /absolute/path/hermes-cutroom --ci
hermes plugins validate /absolute/path/hermes-cutroom --json
```

`--install-deps` is the catalog-parity validation flag and may install this package into the invoking environment. Use the intended development interpreter. Do not enable a development checkout in someone else's active profile without their consent.

## Local media

Raw user media belongs in ignored `raw_vids/`; reference audio and rendered evidence belong in ignored `artifacts/`. Never commit these folders, `.env`, credentials, model binaries or `.venv`.
