"""Safe automation service layer for SIRIUS (Module 3.3).

The only SIRIUS layer that talks to the operating system, exposing exactly
two explicit actions:

- ``open_url``: open a validated http(s) URL in the user's default browser.
- ``launch_app``: start one of the fixed allowlisted applications.

The AI never calls this layer directly. Requests arrive only through
AgentLoop -> ToolRegistry -> core.tools validation, so this service receives
either a validated http(s) URL or one allowlist identifier. It never accepts
shell commands, command arguments, executable paths, or arbitrary
executables, and it re-checks both rules itself (defense in depth) before
any OS call. Launchers are injectable so tests never open real browsers or
start real applications.
"""

import os
import webbrowser
from urllib.parse import urlsplit

from app.core.tools import ALLOWED_URL_SCHEMES, SAFE_AUTOMATION_APPS


def open_url(url, open_url_fn=None):
    """Open a validated http(s) URL in the user's default browser.

    Returns True when the opener reported success and False when opening
    failed. Raises ValueError for anything that is not a well-formed
    http(s) URL.
    """
    _require_allowed_url(url)
    opener = open_url_fn if open_url_fn is not None else _open_in_browser
    try:
        return bool(opener(url))
    except Exception:
        # OS/browser failures never leak out of the service; the registry
        # executor turns this into a clean user-facing observation.
        return False


def launch_app(app, launch_fn=None):
    """Start one allowlisted application through its fixed executable.

    Returns True on success and False when launching failed. Raises
    ValueError for any identifier that is not on the safe allowlist.
    """
    canonical = _require_allowed_app(app)
    executable = SAFE_AUTOMATION_APPS[canonical]["executable"]
    launcher = launch_fn if launch_fn is not None else _launch_executable
    try:
        return bool(launcher(executable))
    except Exception:
        return False


def _require_allowed_url(url):
    """Re-check the URL rules at the OS boundary (defense in depth)."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("A URL is required to open a link.")
    if any(character.isspace() for character in url):
        raise ValueError("A URL cannot contain whitespace.")
    try:
        parts = urlsplit(url)
    except ValueError as error:
        raise ValueError(
            "Only well-formed http and https links can be opened."
        ) from error
    if parts.scheme.lower() not in ALLOWED_URL_SCHEMES or not parts.netloc:
        raise ValueError("Only http and https links can be opened.")


def _require_allowed_app(app):
    """Re-check the allowlist at the OS boundary; return the canonical id."""
    if not isinstance(app, str):
        raise ValueError(
            "That application is not on the SIRIUS automation allowlist."
        )
    canonical = app.strip().lower()
    if canonical not in SAFE_AUTOMATION_APPS:
        raise ValueError(
            "That application is not on the SIRIUS automation allowlist."
        )
    return canonical


def _open_in_browser(url):
    """Default browser opener; kept separate so tests can inject a fake."""
    return webbrowser.open(url)


def _launch_executable(executable):
    """Start one allowlisted executable with no shell and no arguments."""
    os.startfile(executable)