# Integrations and privacy

The core workflow does not require online accounts. `cutroom/integrations.py` contains optional adapters; most are not yet routed through the Studio or exposed in the native page.

| Adapter | Current boundary |
|---|---|
| Supported media import | Explicit confirmation, trusted provider hosts, public-IP/redirect checks, bounded subprocess/download and attribution metadata |
| Raster image import | Explicit confirmation, allowlisted HTTPS hosts, redirect/IP/MIME/size checks |
| OBS WebSocket v5 | Loopback connection, explicit start/stop consent, lazy SDK import; a real running OBS instance is required |
| rclone | Explicit upload consent and CLI-owned credentials. Matching supported remote digests verify content; name/size alone return `verified=false`, `verification="metadata_only"`. Existing files are not silently overwritten. No credential-file scraping. |
| Calendar | Local timezone-aware ICS file; no live service event creation is implied |
| Publication package | Local video/cover/caption/manifest files; not an automatic public post |

These adapters are not an OS/network sandbox. Do not weaken allowlists, enable arbitrary extractors or expose raw shell commands to make a demo appear successful.

## Required before live use

- Explain exactly which file, destination/account and action are requested.
- Obtain confirmation for downloads, recording start/stop and uploads.
- Use normal Hermes/account/application authorization routes. Do not paste secrets into chat or commit them.
- Verify the real recorded/uploaded target after the operation.
- Report missing applications/accounts as blockers, not success.

At the current checkpoint, local ICS/package behavior and adapter contracts are tested. Real OBS capture, remote uploads and live calendar/account writes remain acceptance work.
