# Integrations and privacy

The core workflow does not require online accounts. `cutroom/integrations.py` contains optional adapters; most are not yet routed through the Studio or exposed in the native page.

| Adapter | Current boundary |
|---|---|
| Supported media import | Explicit confirmation, trusted provider hosts, public-IP/redirect checks, bounded subprocess/download and attribution metadata |
| Raster image import | Explicit confirmation, allowlisted HTTPS hosts, redirect/IP/MIME/size checks |
| OBS WebSocket v5 | Studio **Record with OBS** (person only; see below). Loopback only, explicit start/stop consent, a small built-in client (no extra package) |
| rclone | Studio **Send to the cloud** (person only; see below). CLI-owned credentials; matching remote MD5/SHA-1/SHA-256 verify content, name/size alone return `verified=false`, `verification="metadata_only"`. Existing files are never overwritten. No credential-file scraping. |
| Calendar | Local timezone-aware ICS file; no live service event creation is implied |
| Publication package | Local video/cover/caption/manifest files; not an automatic public post |

## Record with OBS

The home page has **Record with OBS** under Make a video. Start recording
starts OBS's recording; **Stop and edit** stops it and imports the file as a
new project.

- OBS must be open with its WebSocket server on (OBS: Tools → WebSocket Server
  Settings → Enable WebSocket server). Its password goes in Settings → Plugins
  → Cutroom; Hermes Desktop keeps it on this computer and sends it only with
  each OBS request. Cutroom never reads OBS's own settings files and never
  stores the password in a project.
- Only loopback addresses are accepted. Start and stop need explicit consent
  (`confirmed: true`); the agent has no OBS tool.
- The client speaks obs-websocket v5 directly: HTTP upgrade, Hello/Identify
  with the documented SHA-256 authentication, then Request/Response; events are
  not subscribed. OBS answers StartRecord and StopRecord before the output
  changes, so Cutroom waits up to 10 s for the new state.
- A wrong password, a closed OBS and a disabled server each give one plain
  sentence saying what to do.
- OBS's WebSocket server listens on all network interfaces by default and is
  protected by its password; turn it off in OBS when you do not record.

Live check (2026-11-14, OBS Studio on Windows): status, start, 3 s of
recording and stop through Cutroom's client; OBS wrote a 1920×1080 MP4 with
audio (3.1 s) that imported as a project. The test recording was deleted and
OBS closed afterwards.

## Send to the cloud (rclone)

Export shows **Send to the cloud** once the approved final has been exported.
It sends the final video, and any of the files made with it (captions,
thumbnail, chapter list), to a remote that was set up with `rclone config`.

- Only a person can send. The first click shows the files, their total size and
  the destination folder; nothing moves until **Send now**. The job requires
  `confirmed: true`, and the agent's `cutroom_job` tool has no upload action.
- Only the exported final of the currently approved version can be sent. Each
  file's size and SHA-256 are checked against the record made at export.
- Each send makes a new folder, `<folder>/<project name> <date time>`, and
  rclone runs with `--immutable --ignore-existing`, so nothing already in the
  cloud is replaced. Names may use any letters.
- Progress comes from rclone's JSON statistics; Cancel stops rclone.
- After each file is copied, rclone lists it with its hashes and Cutroom
  compares them with the local file. For Google Drive the result links to the
  file. Nothing is shared: only the owner of the Drive can open the link.
- Sending changes nothing in the project. An edit made while files are being
  sent does not hide what was sent.
- Google Drive limits requests from rclone's shared app. When that happens the
  message says so; for steady use, set up rclone with its own client ID
  (rclone.org/drive/#making-your-own-client-id).
- rclone is found on `PATH`, beside the Python interpreter, or in a user-scope
  WinGet install (for a Hermes that started before rclone was installed).

Live check (2026-11-14, Google Drive, `drive.file` scope): a Studio upload job
in a scratch workspace sent a video and its SRT through the job worker into a
folder with a Turkish name; both files were verified by MD5, SHA-1 and SHA-256,
progress moved 0.05 → 0.54 → 1.0 and the project revision did not change. The
approval in that scratch workspace was made by the check script, so it is
evidence of the sending path, not of a person's approval. The folder was
deleted afterwards. An earlier run met Google's per-minute limit on rclone's
shared app; that is why copies and checks now let rclone retry.

These adapters are not an OS/network sandbox. Do not weaken allowlists, enable arbitrary extractors or expose raw shell commands to make a demo appear successful.

## Required before live use

- Explain exactly which file, destination/account and action are requested.
- Obtain confirmation for downloads, recording start/stop and uploads.
- Use normal Hermes/account/application authorization routes. Do not paste secrets into chat or commit them.
- Verify the real recorded/uploaded target after the operation.
- Report missing applications/accounts as blockers, not success.

At the current checkpoint, local ICS/package behavior and adapter contracts are tested and cloud sending is live-checked as above. OBS recording is live-checked as above. Live calendar/account writes remain acceptance work, as do recording and sending from the native Desktop window by a person.
