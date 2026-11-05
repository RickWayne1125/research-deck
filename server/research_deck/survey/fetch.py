"""Outbound HTTP for the survey: the scholarly APIs and open-access PDFs.

- every request has a timeout and a generic User-Agent (no personal data is sent);
- a PDF link comes from an API's answer, so it is treated as untrusted: http(s) only; every hop of a redirect (followed
  by hand, at most MAX_REDIRECTS) must resolve to public addresses only (no loopback, private, link-local or reserved
  ones); the body must start with %PDF; at most MAX_PDF_BYTES are written, through a temporary file next to the target.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from .. import __version__

UA = f"research-deck/{__version__}"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_PDF_BYTES = 60 * 1024 * 1024
MAX_REDIRECTS = 5

RETRIES = 2
RETRY_WAIT_S = 15.0

_transport: httpx.BaseTransport | None = None      # tests put an httpx.MockTransport here
sleep = time.sleep                                 # tests make it a no-op
_local = threading.local()                         # .stop: the calling survey's stop event (bind_stop)


def bind_stop(event: threading.Event | None) -> None:
    """Let waits and downloads in this thread end early (FetchError "cancelled") once `event` is set."""
    _local.stop = event


def stopped() -> bool:
    ev = getattr(_local, "stop", None)
    return ev is not None and ev.is_set()


def pause(seconds: float) -> None:
    """Wait `seconds` in short slices, ending early when the survey is cancelled."""
    left = seconds
    while left > 0:
        if stopped():
            raise FetchError("cancelled")
        step = min(left, 0.25)
        sleep(step)
        left -= step
    if stopped():
        raise FetchError("cancelled")


class FetchError(Exception):
    pass


def client(**kw: Any) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": UA}, transport=_transport, **kw)


def is_public_host(host: str) -> bool:
    """Every address the host resolves to is a public one."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


_public = is_public_host                           # tests replace it for their made-up hosts


def describe(e: BaseException) -> str:
    """A short reason for a failed request (the state file and the UI show it)."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        return f"HTTP {code}" + (" (rate limited)" if code == 429 else " (unavailable)" if code in (502, 503, 504) else "")
    if isinstance(e, httpx.TimeoutException):
        return "timed out"
    if isinstance(e, httpx.TransportError):
        return "network error: " + (str(e) or e.__class__.__name__)[:120]
    return (str(e) or e.__class__.__name__)[:200]


def _get(url: str, params: dict | None) -> httpx.Response:
    """GET an API page; a 429 or 503 (the keyless rate limits) is retried after Retry-After (at most RETRY_WAIT_S)."""
    with client(follow_redirects=True) as c:
        for attempt in range(RETRIES + 1):
            r = c.get(url, params=params)
            if r.status_code not in (429, 503) or attempt == RETRIES:
                r.raise_for_status()
                return r
            try:
                wait = float(r.headers.get("retry-after") or 0)
            except ValueError:
                wait = 0.0
            pause(min(max(wait, 4.0 * (attempt + 1)), RETRY_WAIT_S))
    raise FetchError("unreachable")


def get_json(url: str, params: dict | None = None) -> Any:
    return _get(url, params).json()


def get_text(url: str, params: dict | None = None) -> str:
    return _get(url, params).text


def fetch_pdf(url: str, dest: Path, max_bytes: int = MAX_PDF_BYTES) -> int:
    """Save the PDF at `url` as `dest`; returns its size in bytes. Raises FetchError when it is not a reachable PDF."""
    for _ in range(MAX_REDIRECTS + 1):
        try:
            u = httpx.URL(url)
        except (httpx.InvalidURL, TypeError) as e:
            raise FetchError(f"bad URL: {e}")
        if u.scheme not in ("http", "https") or not u.host:
            raise FetchError("not an http(s) URL")
        if not _public(u.host):
            raise FetchError(f"{u.host} is not a public address")
        with client(follow_redirects=False) as c, c.stream("GET", url) as r:
            if r.is_redirect:
                location = r.headers.get("location")
                if not location:
                    raise FetchError("a redirect without a location")
                url = str(u.join(location))
                continue
            if r.status_code != 200:
                raise FetchError(f"HTTP {r.status_code}")
            try:
                declared = int(r.headers.get("content-length") or 0)
            except ValueError:
                declared = 0
            if declared > max_bytes:
                raise FetchError(f"larger than {max_bytes // (1024 * 1024)} MB")
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".download-", suffix=".part")
            size, head = 0, b""
            try:
                with os.fdopen(fd, "wb") as f:
                    for chunk in r.iter_bytes(65536):
                        if stopped():
                            raise FetchError("cancelled")
                        if len(head) < 5:
                            head += chunk[:5 - len(head)]
                        size += len(chunk)
                        if size > max_bytes:
                            raise FetchError(f"larger than {max_bytes // (1024 * 1024)} MB")
                        f.write(chunk)
                if not head.startswith(b"%PDF"):
                    raise FetchError("not a PDF")
                os.replace(tmp, dest)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            return size
    raise FetchError("too many redirects")
