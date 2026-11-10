# Collaboration

## Getting started

1. Accept the private repository invitation.
2. Read [overview](overview.md), [status](status.md) and [architecture](architecture.md).
3. Set up the environment using [development](development.md).
4. Pick one work package from [roadmap](roadmap.md) and agree its file ownership before editing.

## Suggested parallel ownership

| Work area | Primary files |
|---|---|
| Studio/worker integration | `cutroom/studio.py`, `job_worker.py`, `runtime.py`, `worker.py` |
| Native UI and REST contracts | `desktop/plugin.js`, `dashboard/plugin_api.py`, associated tests |
| Speech/editorial logic | `cutroom/speech.py`, `narrative.py`, associated tests |
| Vision/compositing | `cutroom/vision.py`, associated tests |
| Rendering/quality | `cutroom/postproduction.py`, associated tests |
| External adapters | `cutroom/integrations.py`, associated tests |

Avoid concurrent edits to the same files. Shared interfaces, manifests and dependency changes should be coordinated before implementation.

## Branch and review rules

- Create focused branches: `feat/studio-routing`, `fix/media-rotation`, `docs/setup`.
- Use pull requests with a clear scope, test commands, observed results and known limits.
- Keep code, documentation, commits and pull requests in English.
- Write a failing regression before fixing a behavior. Prefer one vertical, runnable workflow at a time.
- Do not merge a green isolated test while claiming a previously failing full suite is green.
- Review source/time mapping, stale approvals and no-overwrite behavior whenever editing export logic.
- Do not enable plugins in a collaborator's active Hermes profile without agreement.

## Before pushing

```bash
git status --short
git diff --check
uvx ruff check cutroom dashboard tests
python -m unittest discover -s tests -v
node --test tests/desktop-check.mjs
```

Use the intended interpreter and a valid TMPDIR. Run focused tests during implementation, then the complete suite before integration.

## Privacy and sharing

Never commit raw recordings, model caches, rendered evidence, credentials or private account settings. Do not upload creator footage or publish social posts as part of a test without explicit approval. A recording copied into a test directory does not grant redistribution rights.

## Definition of done

A feature needs working code, regression coverage, an exercised public interface, understandable error/cancellation behavior and updated documentation. Module tests, plugin registration, native UI behavior and live external integrations are separate proof levels.
