"""Minimal environments for Cutroom child processes.

Children never inherit the parent environment wholesale: provider keys, tokens and
unrelated configuration stay in the Hermes process. Only variables needed to locate
executables, temporary/home directories, locale, fonts and Cutroom's own settings
are forwarded.
"""

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]

FORWARDED = (
    # Executable lookup and Windows system essentials.
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    # Home, profile and temporary directories.
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "APPDATA",
    "TMPDIR",
    "TEMP",
    "TMP",
    # Locale, time zone and fonts used by FFmpeg text rendering.
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "FONTCONFIG_FILE",
    "FONTCONFIG_PATH",
    # Cutroom's own configuration.
    "CUTROOM_WORKSPACE",
    "CUTROOM_PYTHON",
)


NETWORK = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
)


def child_env(*, python=True, forward=(), prefixes=(), **overrides):
    """Return an allowlisted child environment.

    ``python`` adds Cutroom to ``PYTHONPATH`` (never the parent's value).
    ``forward`` and ``prefixes`` add variables a specific consented tool needs,
    for example rclone's own ``RCLONE_*`` configuration.
    """
    names = set(FORWARDED) | set(forward)
    env = {
        key: value
        for key, value in os.environ.items()
        if value and (key in names or key.startswith(tuple(prefixes)))
    }
    if python:
        env["PYTHONPATH"] = str(PACKAGE_ROOT)
        env["PYTHONIOENCODING"] = "utf-8"
    env.update({key: str(value) for key, value in overrides.items()})
    return env
