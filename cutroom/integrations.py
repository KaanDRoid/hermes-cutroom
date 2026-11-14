"""Explicit-consent, optional adapters. Importing this module performs no I/O."""

import hashlib
import http.client
import importlib.util
import ipaddress
import json
import math
import os
import re
import select
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

try:
    from .childenv import NETWORK, child_env
except ImportError:  # loaded as a standalone module file
    from cutroom.childenv import NETWORK, child_env

MEDIA_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "x.com",
        "www.x.com",
        "twitter.com",
        "www.twitter.com",
        "pexels.com",
        "www.pexels.com",
        "pixabay.com",
        "www.pixabay.com",
    }
)
STATIC_MEDIA_HOSTS = frozenset({"videos.pexels.com", "cdn.pixabay.com"})
IMAGE_HOSTS = frozenset(
    {
        "images.pexels.com",
        "cdn.pixabay.com",
        "i.ytimg.com",
        "yt3.ggpht.com",
        "pbs.twimg.com",
        "abs.twimg.com",
        "openai.com",
        "www.openai.com",
        "images.openai.com",
        "cdn.openai.com",
        "obsproject.com",
        "www.obsproject.com",
        "rclone.org",
    }
)


def _public_destination(url, hosts):
    parsed = _clean_url(url)
    if parsed.hostname not in hosts:
        raise ValueError("URL host is not an approved provider")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise RuntimeError("Public provider DNS lookup failed") from None
    if not addresses or any(
        not ipaddress.ip_address(address[4][0]).is_global for address in addresses
    ):
        raise ValueError("All provider DNS addresses must be public")
    return parsed, addresses[0][4][0]


def _find_executable(name):
    executable = shutil.which(name)
    if executable is not None:
        return executable
    sibling = Path(sys.executable).parent / (name + (".exe" if os.name == "nt" else ""))
    if sibling.is_file():
        return str(sibling)
    if name == "rclone" and os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        # A user-scope WinGet install, when Hermes started before it was added
        # to PATH. Fixed location only; never a path from project data.
        packages = (
            Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "WinGet" / "Packages"
        )
        found = sorted(packages.glob("Rclone.Rclone_*/rclone-v*/rclone.exe"))
        if found:
            return str(found[-1])
    return None


def capability_report() -> dict:
    """Report discovery only; executable presence does not prove a live service."""
    result = {}
    for name in ("ffmpeg", "ffprobe", "yt-dlp", "rclone", "obs64"):
        executable = _find_executable(name)
        result[name] = {
            "available": executable is not None,
            "path": executable,
            "live_verified": False,
        }
    result["obsws_python"] = {
        "available": importlib.util.find_spec("obsws_python") is not None,
        "live_verified": False,
    }
    return result


def _consent(confirmed):
    if confirmed is not True:
        raise PermissionError("Explicit confirmation is required")


def _local(value, *, exists=False):
    raw = os.fspath(value)
    normalized = raw.replace("\\", "/")
    drive = re.match(r"^[a-zA-Z]:/", normalized)
    if (
        not raw
        or any(ord(c) < 32 for c in raw)
        or normalized.startswith("//")
        or ":" in (normalized[2:] if drive else normalized)
    ):
        raise ValueError("Only local paths are allowed")
    path = Path(raw).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Linked paths are not allowed")
    path = path.resolve()
    if str(path).replace("\\", "/").startswith("//"):
        raise ValueError("Network paths are not allowed")
    if exists and not path.is_file():
        raise FileNotFoundError("A local regular file is required")
    return path


def _clean_url(url):
    if (
        not isinstance(url, str)
        or any(ord(c) <= 32 or ord(c) == 127 for c in url)
        or "\\" in url
    ):
        raise ValueError("Invalid URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise ValueError("An HTTPS URL without credentials on port 443 is required")
    return parsed


def _source_url(url):
    parsed = _clean_url(url)
    query = ""
    if (
        parsed.hostname
        in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
        and parsed.path == "/watch"
    ):
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", video_id):
            query = urlencode({"v": video_id})
    return urlunsplit(("https", parsed.hostname, parsed.path, query, ""))


def _ics_text(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _fold_ics(line):
    lines = [""]
    for char in line:
        if len((lines[-1] + char).encode("utf-8")) > 75:
            lines.append(" ")
        lines[-1] += char
    return "\r\n".join(lines)


def create_calendar_event(path, title, start, end, description="", url="") -> dict:
    """Write a new local UTC iCalendar event; never contact a calendar service."""
    path = _local(path)
    if path.exists():
        raise FileExistsError(path)

    def instant(value):
        value = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError("Timezone-aware start and end are required")
        return value.astimezone(timezone.utc)

    start, end = instant(start), instant(end)
    if end <= start:
        raise ValueError("End must follow start")
    if url:
        _clean_url(url)

    def stamp(value):
        return value.strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Cutroom//Calendar//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@cutroom.local",
        f"DTSTAMP:{stamp(datetime.now(timezone.utc))}",
        f"DTSTART:{stamp(start)}",
        f"DTEND:{stamp(end)}",
        "SUMMARY:" + _ics_text(title),
        "DESCRIPTION:" + _ics_text(description),
    ]
    if url:
        lines.append("URL:" + _source_url(url))
    lines += ["END:VEVENT", "END:VCALENDAR"]
    with path.open("xb") as stream:
        stream.write(
            ("\r\n".join(_fold_ics(line) for line in lines) + "\r\n").encode("utf-8")
        )
    return {
        "path": str(path),
        "external_write": False,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


MAX_MEDIA_BYTES = 512 * 1024 * 1024
EXTRACTOR_HOSTS = (
    MEDIA_HOSTS
    | STATIC_MEDIA_HOSTS
    | IMAGE_HOSTS
    | frozenset(
        {
            "api.x.com",
            "api.twitter.com",
            "video.twimg.com",
            "www.youtube-nocookie.com",
            "youtubei.googleapis.com",
        }
    )
)


class _ExtractorHosts:
    def __contains__(self, host):
        return host in EXTRACTOR_HOSTS or host.endswith(".googlevideo.com")


@contextmanager
def _restricted_proxy():
    """A pinned-public-IP CONNECT proxy for cooperative extractor HTTPS traffic."""

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(HTTP_TIMEOUT)
            try:
                line = self.rfile.readline(4097).decode("ascii")
                match = re.fullmatch(
                    r"CONNECT ([A-Za-z0-9.-]+):443 HTTP/1\.[01]\r\n", line
                )
                if match is None:
                    raise ValueError("Only HTTPS CONNECT is allowed")
                total = 0
                while True:
                    header = self.rfile.readline(4097)
                    total += len(header)
                    if total > 16384 or not header or len(header) > 4096:
                        raise ValueError("Invalid proxy headers")
                    if header == b"\r\n":
                        break
                _, address = _public_destination(
                    "https://" + match[1], _ExtractorHosts()
                )
                upstream = socket.create_connection(
                    (address, 443), timeout=HTTP_TIMEOUT
                )
            except Exception:
                try:
                    self.wfile.write(
                        b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n"
                    )
                except OSError:
                    pass
                return
            with upstream:
                self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                self.wfile.flush()
                deadline = time.monotonic() + PROCESS_TIMEOUT
                try:
                    while time.monotonic() < deadline:
                        ready, _, _ = select.select(
                            [self.request, upstream], [], [], HTTP_TIMEOUT
                        )
                        if not ready:
                            return
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                return
                            with self.server.budget_lock:
                                self.server.transferred += len(data)
                                if (
                                    self.server.transferred
                                    > MAX_MEDIA_BYTES + 16 * 1024 * 1024
                                ):
                                    return
                            (
                                upstream if source is self.request else self.request
                            ).sendall(data)
                except OSError:
                    return

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = False

    with Server(("127.0.0.1", 0), Handler) as server:
        server.transferred = 0
        server.budget_lock = threading.Lock()
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            worker.join(timeout=2)


def _media_metadata(raw):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise RuntimeError("Downloader returned invalid metadata") from None
    if not isinstance(value, dict):
        raise RuntimeError("Downloader returned invalid metadata")
    if value.get("_type") in ("playlist", "multi_video") or "entries" in value:
        raise ValueError("Playlists and multi-video imports are not allowed")
    if value.get("is_live") or value.get("live_status") in (
        "is_live",
        "is_upcoming",
        "post_live",
    ):
        raise ValueError("Live and scheduled streams are not allowed")
    duration = value.get("duration")
    if duration is not None and (
        not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
        or duration > 3600
    ):
        raise ValueError("Media duration must be at most one hour")
    return value


def _probe_media(path, kind):
    result = _run(
        [
            _executable("ffprobe"),
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            "-i",
            str(path),
        ],
        timeout=30,
    )
    try:
        metadata = json.loads(result.stdout)
        duration = float(metadata["format"]["duration"])
        streams = [stream["codec_type"] for stream in metadata["streams"]]
        if (
            kind not in streams
            or not math.isfinite(duration)
            or not 0 < duration <= 3600
        ):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("Downloaded file failed media verification") from None
    return {"duration": duration, "streams": streams, "size": path.stat().st_size}


def download_media(url, output_dir, confirmed=False, kind="video") -> dict:
    """Import one supported public media item with bounded native HTTPS downloads."""
    _consent(confirmed)
    if kind != "video":
        raise ValueError("Kind must be video")
    output_dir = _local(output_dir)
    if output_dir.exists():
        raise FileExistsError(output_dir)
    parsed = _clean_url(url)
    if parsed.hostname not in MEDIA_HOSTS | STATIC_MEDIA_HOSTS:
        raise ValueError("URL host is not an approved media provider")
    if "list" in parse_qs(parsed.query) or parsed.path.rstrip("/").endswith(
        "/playlist"
    ):
        raise ValueError("Playlists are not allowed")
    static = parsed.hostname in STATIC_MEDIA_HOSTS
    if static and not re.search(
        r"\.(?:mp4|webm|mov|m4a|mp3|ogg|wav)$", parsed.path, re.I
    ):
        raise ValueError("Static provider URLs must name a media file")
    if parsed.hostname in {
        "pexels.com",
        "www.pexels.com",
        "pixabay.com",
        "www.pixabay.com",
    }:
        raise ValueError("Use a direct videos.pexels.com or cdn.pixabay.com media URL")
    executable = _executable("yt-dlp")
    _executable("ffprobe")
    connection, response, _ = _follow_https(
        url, MEDIA_HOSTS | STATIC_MEDIA_HOSTS, "HEAD"
    )
    connection.close()
    if response.status not in (200, 405):
        raise RuntimeError("Media provider refused the initial URL")
    with tempfile.TemporaryDirectory(
        prefix=".cutroom-import-", dir=output_dir.parent
    ) as directory:
        directory = Path(directory)
        with _restricted_proxy() as proxy:
            common = [
                executable,
                "--ignore-config",
                "--no-plugin-dirs",
                "--no-js-runtimes",
                "--no-remote-components",
                "--no-cache-dir",
                "--no-playlist",
                "--playlist-items",
                "1",
                "--no-overwrites",
                "--no-continue",
                "--no-progress",
                "--quiet",
                "--socket-timeout",
                "10",
                "--retries",
                "1",
                "--fragment-retries",
                "1",
                "--extractor-retries",
                "1",
                "--max-filesize",
                str(MAX_MEDIA_BYTES),
                "--match-filters",
                "!is_live & !is_upcoming & duration <=? 3600",
                "--proxy",
                proxy,
                "--use-extractors",
                "generic" if static else "youtube,twitter",
                "--downloader",
                "native",
                "--fixup",
                "never",
                "--format",
                "best[protocol=https]",
                "--output",
                str(directory / "media.%(ext)s"),
            ]
            metadata = _media_metadata(
                _run(
                    [*common, "--skip-download", "--dump-single-json", "--", url]
                ).stdout
            )
            selected = metadata.get("requested_downloads") or [metadata]
            for item in selected:
                if item.get("protocol") not in (None, "https"):
                    raise ValueError("Only direct HTTPS media formats are supported")
                if item.get("url"):
                    _public_destination(item["url"], _ExtractorHosts())
            metadata = _media_metadata(
                _run([*common, "--no-simulate", "--dump-single-json", "--", url]).stdout
            )
        files = list(directory.iterdir())
        if (
            len(files) != 1
            or not files[0].is_file()
            or files[0].is_symlink()
            or not re.fullmatch(r"media\.[A-Za-z0-9]{1,8}", files[0].name)
        ):
            raise RuntimeError(
                "Downloader did not produce exactly one completed media file"
            )
        source = files[0]
        if not 0 < source.stat().st_size <= MAX_MEDIA_BYTES:
            raise ValueError("Downloaded media exceeds the size limit or is empty")
        probe = _probe_media(source, kind)
        if probe["size"] > MAX_MEDIA_BYTES:
            raise ValueError("Converted media exceeds the size limit")
        attribution = {
            "source_url": _source_url(url),
            "provider": parsed.hostname,
            "title": str(metadata.get("title") or "")[:1000],
            "creator": str(metadata.get("uploader") or metadata.get("creator") or "")[
                :1000
            ],
            "license": str(
                metadata.get("license") or "Not supplied; verify usage rights"
            )[:1000],
        }
        output_dir.mkdir()
        try:
            target = output_dir / source.name
            os.link(source, target)
            attribution_path = output_dir / "attribution.json"
            with attribution_path.open("x", encoding="utf-8") as stream:
                json.dump(attribution, stream, ensure_ascii=False, indent=2)
        except Exception:
            shutil.rmtree(output_dir)
            raise
    return {
        "output": str(target),
        "attribution_path": str(attribution_path),
        "source_url": attribution["source_url"],
        "kind": kind,
        "probe": probe,
        "media_verified": True,
    }


IMAGE_MAX_BYTES = 20 * 1024 * 1024
HTTP_TIMEOUT = 10
TRANSFER_TIMEOUT = 60


def _open_https(url, hosts, method="GET"):
    parsed, address = _public_destination(url, hosts)
    connection = http.client.HTTPSConnection(parsed.hostname, 443, timeout=HTTP_TIMEOUT)
    connection._create_connection = lambda endpoint, timeout, source_address=None: (
        socket.create_connection((address, 443), timeout, source_address)
    )
    try:
        connection.request(
            method,
            urlunsplit(("", "", parsed.path or "/", parsed.query, "")),
            headers={"User-Agent": "Cutroom/0.1", "Accept-Encoding": "identity"},
        )
        return connection, connection.getresponse()
    except Exception:
        connection.close()
        raise RuntimeError("HTTPS provider request failed") from None


def _follow_https(url, hosts, method="GET"):
    for _ in range(6):
        parsed = _clean_url(url)
        if parsed.hostname not in hosts:
            raise ValueError("Redirect host is not an approved provider")
        connection, response = _open_https(url, hosts, method)
        if response.status not in (301, 302, 303, 307, 308):
            return connection, response, url
        location = response.getheader("Location")
        connection.close()
        if not location:
            raise ValueError("Redirect has no target")
        url = urljoin(url, location)
    raise ValueError("Too many provider redirects")


def _image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def download_image(url, output, confirmed=False) -> dict:
    """Fetch a trusted HTTPS raster image without replacing an existing file."""
    _consent(confirmed)
    output = _local(output)
    if output.exists():
        raise FileExistsError(output)
    connection, response, final_url = _follow_https(url, IMAGE_HOSTS)
    try:
        if response.status != 200:
            raise RuntimeError("Image provider did not return HTTP 200")
        mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
        extensions = {
            "image/png": {".png"},
            "image/jpeg": {".jpg", ".jpeg"},
            "image/gif": {".gif"},
            "image/webp": {".webp"},
        }
        if mime not in extensions or output.suffix.lower() not in extensions[mime]:
            raise ValueError("Only matching PNG, JPEG, GIF, or WebP files are allowed")
        declared = response.getheader("Content-Length")
        if declared is not None and (
            not declared.isdigit() or int(declared) > IMAGE_MAX_BYTES
        ):
            raise ValueError("Image exceeds the byte limit")
        data = bytearray()
        deadline = time.monotonic() + TRANSFER_TIMEOUT
        while True:
            if time.monotonic() >= deadline:
                raise RuntimeError("Image transfer timed out")
            block = response.read(min(65536, IMAGE_MAX_BYTES + 1 - len(data)))
            if not block:
                break
            data.extend(block)
            if len(data) > IMAGE_MAX_BYTES:
                raise ValueError("Image exceeds the byte limit")
        if _image_type(data) != mime or (
            declared is not None and len(data) != int(declared)
        ):
            raise ValueError("Image content does not match its declared type or length")
        with tempfile.TemporaryDirectory(
            prefix=".cutroom-image-", dir=output.parent
        ) as directory:
            staging = Path(directory) / "image"
            staging.write_bytes(data)
            os.link(staging, output)
        return {
            "output": str(output),
            "bytes": len(data),
            "mime": mime,
            "source_url": _source_url(url),
            "resolved_url": _source_url(final_url),
            "attribution": "Source: " + _source_url(url),
        }
    except (OSError, http.client.HTTPException):
        raise RuntimeError("Image transfer failed") from None
    finally:
        connection.close()


PROCESS_TIMEOUT = 300


def _executable(name):
    executable = _find_executable(name)
    if executable is None:
        raise RuntimeError(f"Optional executable is unavailable: {name}")
    return executable


def _run(argv, *, timeout=PROCESS_TIMEOUT):
    try:
        return subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=True,
            timeout=timeout,
            env=child_env(python=False, forward=NETWORK, prefixes=("RCLONE_",)),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Integration command timed out") from None
    except (subprocess.CalledProcessError, OSError):
        raise RuntimeError(
            "Integration command failed; no success has been verified"
        ) from None


def _rclone_env():
    return child_env(python=False, forward=NETWORK, prefixes=("RCLONE_",))


def list_remotes() -> list:
    """Remotes configured in rclone (name and type); none when rclone is absent."""
    executable = _find_executable("rclone")
    if executable is None:
        return []
    response = _run([executable, "listremotes", "--long"], timeout=30)
    remotes = []
    for line in response.stdout.splitlines():
        name, _, kind = line.partition(":")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", name.strip()):
            remotes.append({"name": name.strip(), "type": kind.strip()})
    return remotes


def _remote_target(remote_path):
    """Split ``remote:folder/file`` and refuse anything but a plain relative path.

    Folder and file names may use any letters (project names are often not
    English); control characters, backslashes, colons and dot segments are
    refused.
    """
    if not isinstance(remote_path, str) or ":" not in remote_path:
        raise ValueError("Use a configured remote name and a relative object path")
    remote, key = remote_path.split(":", 1)
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", remote)
        or not key
        or len(key) > 1000
        or key.startswith("/")
        or key.endswith("/")
        or any(ord(c) < 32 or c in '\\:*?"<>|' for c in key)
        or any(part.strip() in ("", ".", "..") for part in key.split("/"))
    ):
        raise ValueError("Use a configured remote name and a relative object path")
    return remote, key


def _upload_problem(detail):
    """One plain sentence for a failed copy; provider JSON details are dropped."""
    text = (detail or "").split("\nDetails:", 1)[0].strip()
    lowered = text.lower()
    if "quota exceeded" in lowered or "ratelimitexceeded" in lowered.replace(" ", ""):
        return (
            "Google Drive is limiting requests from rclone's shared app. Wait a "
            "minute and send again; for steady use, give rclone its own client ID "
            "(rclone.org/drive/#making-your-own-client-id). Nothing was verified as sent"
        )
    text = re.sub(r"\s+", " ", text)[:240]
    return (
        f"Upload failed: {text}. Nothing was verified as sent"
        if text
        else ("Upload failed. Nothing was verified as sent")
    )


def _copy_with_progress(argv, *, timeout, progress, cancelled):
    """Run ``rclone copyto`` and report its byte progress; stop on cancel."""
    import queue

    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=_rclone_env(),
        )
    except OSError:
        raise RuntimeError(
            "rclone could not start; no success has been verified"
        ) from None
    lines = queue.Queue()

    def read():
        for line in process.stderr:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + timeout
    problem = None
    finished = False

    def stop():
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    while not finished:
        if cancelled is not None and cancelled():
            stop()
            raise InterruptedError("Upload cancelled")
        if time.monotonic() > deadline:
            stop()
            raise RuntimeError("Upload timed out; no success has been verified")
        try:
            line = lines.get(timeout=0.5)
        except queue.Empty:
            continue
        if line is None:
            finished = True
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("level") in ("error", "critical") and entry.get("msg"):
            problem = str(entry["msg"]).strip()[:300]
        figures = entry.get("stats")
        if progress is not None and isinstance(figures, dict):
            done, total = figures.get("bytes"), figures.get("totalBytes")
            if isinstance(done, int) and isinstance(total, int) and total > 0:
                progress(min(1.0, done / total))
    if process.wait(timeout=30) != 0:
        raise RuntimeError(_upload_problem(problem))


def upload_rclone(
    local_file,
    remote_path,
    confirmed=False,
    *,
    progress=None,
    cancelled=None,
    remote_type=None,
) -> dict:
    """Copy to an explicitly approved configured remote; verify the exact object.

    Never replaces a file already at the destination. ``progress`` receives
    0..1 while bytes move; ``cancelled`` is polled and stops rclone. For
    Google Drive remotes the result carries a link that only the owner of the
    Drive can open: nothing is shared.
    """
    _consent(confirmed)
    local = _local(local_file, exists=True)
    remote, key = _remote_target(remote_path)
    executable = _executable("rclone")
    size = local.stat().st_size
    # At least 5 minutes, and enough for 100 kB/s; never more than 6 hours.
    timeout = min(6 * 3600, max(300, size / 100_000))
    _copy_with_progress(
        [
            executable,
            "copyto",
            "--immutable",
            "--ignore-existing",
            "--use-json-log",
            "--stats",
            "1s",
            "--stats-log-level",
            "NOTICE",
            # rclone backs off and retries when a provider limits the rate.
            "--retries",
            "3",
            "--low-level-retries",
            "10",
            "--contimeout",
            "10s",
            "--timeout",
            "30s",
            "--",
            str(local),
            remote_path,
        ],
        timeout=timeout,
        progress=progress,
        cancelled=cancelled,
    )
    try:
        # Listing right after a copy can meet the same rate limit: let rclone retry.
        response = _run(
            [
                executable,
                "lsjson",
                "--stat",
                "--hash",
                "--low-level-retries",
                "10",
                "--contimeout",
                "10s",
                "--timeout",
                "30s",
                "--",
                remote_path,
            ],
            timeout=120,
        )
    except RuntimeError as error:
        how = "timed out" if "timed out" in str(error) else "failed"
        raise RuntimeError(
            f"The file was sent, but checking it in the cloud {how}. Look in the "
            "folder before sending again"
        ) from None
    try:
        metadata = json.loads(response.stdout)
        if (
            metadata.get("IsDir") is not False
            or metadata.get("Size") != size
            or metadata.get("Name") != key.rsplit("/", 1)[-1]
        ):
            raise ValueError
        # rclone names hashes in lowercase ("md5"); accept the older spelling too.
        hashes = {
            re.sub(r"[^a-z0-9]", "", str(name).lower()): value
            for name, value in (metadata.get("Hashes") or {}).items()
        }
        checked = []
        for name, algorithm in (
            ("MD5", "md5"),
            ("SHA-1", "sha1"),
            ("SHA-256", "sha256"),
        ):
            digest = hashes.get(algorithm)
            if digest:
                if str(digest).lower() != _hash_file(local, algorithm):
                    raise ValueError
                checked.append(name)
    except (ValueError, TypeError, AttributeError):
        raise RuntimeError(
            "Remote object verification failed; upload may have occurred"
        ) from None
    file_id = metadata.get("ID")
    link = (
        f"https://drive.google.com/file/d/{file_id}/view"
        if remote_type == "drive"
        and isinstance(file_id, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{10,200}", file_id)
        else None
    )
    return {
        "remote": remote_path,
        "size": metadata["Size"],
        "verified": bool(checked),
        "verification": "hash" if checked else "metadata_only",
        "hash_verified": checked,
        "link": link,
        "external_write": True,
    }


class _Password(str):
    def __str__(self):
        return "[redacted]"

    def __repr__(self):
        return "'[redacted]'"

    def __format__(self, spec):
        return format("[redacted]", spec)


def obs_record(
    action, host="127.0.0.1", port=4455, password=None, confirmed=False
) -> dict:
    """Use obs-websocket v5 on loopback only; credentials are supplied explicitly."""
    if action in ("start", "stop"):
        _consent(confirmed)
    if action not in ("start", "stop", "status"):
        raise ValueError("Action must be start, stop, or status")
    host = "127.0.0.1" if host == "localhost" else host
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("OBS must be on loopback")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Invalid OBS port")
    if password is not None and not isinstance(password, str):
        raise ValueError("Password must be supplied as text by the credential provider")
    try:
        import obsws_python
    except ImportError:
        raise RuntimeError("Install the optional obsws-python dependency") from None
    client = None
    output = None
    try:
        client = obsws_python.ReqClient(
            host=host, port=port, password=_Password(password or ""), timeout=5
        )
        if action == "start":
            client.start_record()
        elif action == "stop":
            output = client.stop_record().output_path
        status = client.get_record_status()
        active = bool(status.output_active)
        if action in ("start", "stop") and active != (action == "start"):
            raise RuntimeError("OBS did not reach the requested recording state")
        result = {
            "action": action,
            "recording": active,
            "paused": bool(status.output_paused),
            "timecode": status.output_timecode,
        }
    except Exception:
        raise RuntimeError(
            "OBS connection or request failed; check local OBS and provider configuration"
        ) from None
    finally:
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
    if action == "stop":
        path = _local(output, exists=True)
        if path.stat().st_size == 0:
            raise ValueError("OBS recording is empty")
        result.update(output=str(path), file_verified=True)
    return result


def _hash_file(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def publish_package(
    directory, video, cover=None, caption="", *, confirmed=False
) -> dict:
    """Copy a delivery package locally. This does not publish or share anything."""
    _consent(confirmed)
    directory = _local(directory)
    video = _local(video, exists=True)
    cover = _local(cover, exists=True) if cover is not None else None
    if not isinstance(caption, str):
        raise ValueError("Caption must be text")
    directory.mkdir()
    try:
        files = {}
        for role, source in (("video", video), ("cover", cover)):
            if source is None:
                continue
            target = directory / (role + source.suffix.lower())
            with source.open("rb") as incoming, target.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            files[target.name] = {
                "size": target.stat().st_size,
                "sha256": _hash_file(target),
            }
        (directory / "caption.txt").write_text(caption, encoding="utf-8")
        files["caption.txt"] = {
            "size": (directory / "caption.txt").stat().st_size,
            "sha256": _hash_file(directory / "caption.txt"),
        }
        manifest = {"version": 1, "external_write": False, "files": files}
        (directory / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return {
            "directory": str(directory),
            "manifest": str(directory / "manifest.json"),
            "external_write": False,
        }
    except Exception:
        shutil.rmtree(directory)
        raise
