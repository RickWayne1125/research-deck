"""This computer's Docmost site, the saved sign-in, and the few page calls the note sync needs.

settings.json {"docmost": {"url": "https://docs.example.com"}}. The sign-in is the set of cookies the site set while
the researcher signed in (login.py), kept in ~/.research-deck/secrets/docmost/session.json. They are sent only to that
site and never on a redirect: a redirect (an SSO proxy asking to sign in again) or a 401 means "sign in again".
Docmost's API is POST /api/<area>/<action> with JSON, answered as {"data": …, "success": true, "status": 200}.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from .. import __version__, config, vault

SESSION = ("docmost", "session.json")
UA = f"research-deck/{__version__}"
TIMEOUT = httpx.Timeout(30.0, connect=8.0)
TRANSPORT: httpx.BaseTransport | None = None      # tests put an httpx.MockTransport here
LOCAL_SUFFIXES = (".local", ".lan", ".internal", ".home.arpa", ".localhost")


class DocmostError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class SignInNeeded(DocmostError):
    pass


# ---------------------------------------------------------------- the site

def _plain_http_ok(host: str) -> bool:
    """http:// is accepted only inside this computer or a private network; anything else must be https."""
    if host in ("localhost",) or host.endswith(LOCAL_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def normalize(url: str) -> str:
    """The site's address as https://host[:port][/path], or ValueError."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("enter the address of your Docmost site")
    if "://" not in raw:
        raw = "https://" + raw
    p = urlparse(raw)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("the address must start with https://")
    if p.username or p.password or p.query or p.fragment:
        raise ValueError("enter the site's address only, without a user, query or #fragment")
    if p.scheme == "http" and not _plain_http_ok(p.hostname):
        raise ValueError("use https:// (plain http is accepted only on this computer or a private network)")
    host = p.hostname if ":" not in p.hostname else f"[{p.hostname}]"
    port = f":{p.port}" if p.port else ""
    path = re.sub(r"/(s|p|settings|login|home)(/.*)?$", "", p.path.rstrip("/"))   # a page link pasted by mistake
    return f"{p.scheme}://{host}{port}{path}"


def site() -> str | None:
    url = (config.user_settings().get("docmost") or {}).get("url")
    try:
        return normalize(url) if url else None
    except ValueError:
        return None


def set_site(url: str | None) -> str | None:
    """Save the site's address (None forgets it). A different site forgets the sign-in, which belonged to the old one."""
    new = normalize(url) if url else None
    old = site()
    config.save_user_setting("docmost", {"url": new} if new else None)
    if new != old:
        vault.delete(*SESSION)
    return new


def session() -> dict | None:
    """The saved sign-in for the current site, or None."""
    data = vault.read_json(*SESSION)
    if not isinstance(data, dict) or not data.get("cookies") or data.get("url") != site():
        return None
    return data


def save_session(data: dict) -> None:
    vault.write_json(data, *SESSION)


def forget_session() -> None:
    vault.delete(*SESSION)


# ---------------------------------------------------------------- calls

def _message(r: httpx.Response) -> str:
    try:
        body = r.json()
        msg = body.get("message") if isinstance(body, dict) else None
        if isinstance(msg, list):
            msg = "; ".join(str(m) for m in msg)
        return str(msg or r.text[:200])
    except ValueError:
        return r.text.strip()[:200]


class Client:
    def __init__(self, url: str | None = None, sess: dict | None = None, http: httpx.Client | None = None):
        self.url = url or site()
        if not self.url:
            raise DocmostError("set the address of your Docmost site in Settings → Docmost")
        sess = sess or session()
        if not sess:
            raise SignInNeeded("sign in to Docmost in Settings → Docmost")
        self.cookie = "; ".join(f"{c['name']}={c['value']}" for c in sess.get("cookies") or []
                                if isinstance(c, dict) and c.get("name") and c.get("value") is not None)
        self.ua = sess.get("user_agent") or UA
        self.http = http or httpx.Client(timeout=TIMEOUT, transport=TRANSPORT)

    def post(self, path: str, body: dict | None = None) -> Any:
        host = urlparse(self.url).hostname
        try:
            r = self.http.post(self.url + path, json=body or {}, follow_redirects=False,
                               headers={"Cookie": self.cookie, "User-Agent": self.ua, "Accept": "application/json"})
        except httpx.HTTPError as e:
            raise DocmostError(f"cannot reach {host}: {e.__class__.__name__}") from e
        if r.status_code == 401 or 300 <= r.status_code < 400:
            raise SignInNeeded("Docmost asks to sign in again", r.status_code)
        if r.status_code == 404:
            raise DocmostError(_message(r) or "not found", 404)
        if r.status_code >= 400:
            raise DocmostError(f"Docmost answered {r.status_code}: {_message(r)}", r.status_code)
        try:
            data = r.json()
        except ValueError as e:                  # an HTML page: a sign-in proxy in front of the site
            raise SignInNeeded("Docmost answered with a web page instead of data: sign in again") from e
        if isinstance(data, dict) and "data" in data and ("success" in data or "status" in data):
            return data["data"]
        return data

    def me(self) -> dict:
        data = self.post("/api/users/me") or {}
        user = data.get("user") if isinstance(data, dict) and isinstance(data.get("user"), dict) else data
        return {"id": user.get("id"), "name": user.get("name"), "email": user.get("email")} if isinstance(user, dict) else {}

    def page(self, page_id: str, markdown: bool = False) -> dict:
        body: dict[str, Any] = {"pageId": page_id}
        if markdown:
            body["format"] = "markdown"
        return self.post("/api/pages/info", body) or {}

    def create_page(self, space_id: str, parent_id: str, title: str, markdown: str) -> dict:
        return self.post("/api/pages/create", {"spaceId": space_id, "parentPageId": parent_id, "title": title,
                                               "content": markdown, "format": "markdown"}) or {}

    def update_page(self, page_id: str, title: str, markdown: str) -> dict:
        return self.post("/api/pages/update", {"pageId": page_id, "title": title, "content": markdown,
                                               "format": "markdown", "operation": "replace"}) or {}


# ---------------------------------------------------------------- page links

SLUG_ID = re.compile(r"^[A-Za-z0-9]{6,40}$")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def page_ref(link: str) -> str:
    """The page id in a link copied from Docmost (…/s/<space>/p/<title>-<slugId>), or a bare slug id or page id."""
    raw = (link or "").strip()
    if UUID.match(raw) or SLUG_ID.match(raw):
        return raw
    p = urlparse(raw if "://" in raw else "https://" + raw)
    here = site()
    if here and p.hostname and p.hostname != urlparse(here).hostname:
        raise ValueError(f"this link is not on {urlparse(here).hostname}, the Docmost site in Settings")
    parts = [x for x in p.path.split("/") if x]
    if "p" in parts and parts.index("p") + 1 < len(parts):
        token = parts[parts.index("p") + 1]
        ref = token.rsplit("-", 1)[-1]
        if SLUG_ID.match(ref) or UUID.match(token):
            return token if UUID.match(token) else ref
    raise ValueError("paste the link of a page, as Docmost shows it in the address bar (…/s/<space>/p/<page>)")


def page_url(slug_id: str, title: str = "", space_slug: str | None = None) -> str | None:
    base = site()
    if not base or not slug_id:
        return None
    words = re.sub(r"[^A-Za-z0-9]+", "-", (title or "").lower()).strip("-")[:60] or "page"
    return f"{base}/s/{space_slug}/p/{words}-{slug_id}" if space_slug else f"{base}/p/{slug_id}"
