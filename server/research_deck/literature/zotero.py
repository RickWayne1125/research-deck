"""This computer's Zotero connection and a small client for Zotero's HTTP API (Web API v3 and the local API).

settings.json {"zotero": {"mode": "local" | "web", "library": "users/<id>" | "groups/<id>", "credential": "keychain:<item>"}}

  local  the desktop app's local API at http://127.0.0.1:23119/api/ (writes and uploads need Zotero 10 or later, and
         Settings → Advanced → "Allow other applications on this computer to communicate with Zotero"). Writing needs a
         key the app grants in a dialog (authorize_local): "Always Allow" keeps it, "Allow" makes it good for one write.
         The key is kept in ~/.research-deck/secrets/zotero.json (vault.py). The library defaults to "users/0", the
         app's own library.
  web    the zotero.org Web API with an API key that may write to the library. The key stays in the macOS Keychain (or
         an environment variable): the settings only name it, as the resource pools do (pools/sources.py).

Requests carry no personal data beyond the key, never follow redirects, and back off on 429/503 and Backoff headers.
The PDF upload goes to the address Zotero returns (zotero.org's file storage over https, or the local app itself) and
carries no key.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .. import __version__, config, vault
from ..survey import bib

LOCAL_ORIGIN = "http://127.0.0.1:23119"
WEB_ORIGIN = "https://api.zotero.org"
MODES = ("local", "web")
LIBRARY_RE = re.compile(r"^(users|groups)/\d{1,12}$")
CREDENTIAL_RE = re.compile(r"^(keychain|env):[A-Za-z0-9_.@-]{1,120}$")
UA = f"research-deck/{__version__}"
TIMEOUT = httpx.Timeout(30.0, connect=5.0)
TRANSPORT: httpx.BaseTransport | None = None      # tests put an httpx.MockTransport here
SECRET = "zotero.json"


class ZoteroError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- settings

def settings() -> dict:
    raw = config.user_settings().get("zotero") or {}
    mode = raw.get("mode") if raw.get("mode") in MODES else "local"
    library = raw.get("library") if isinstance(raw.get("library"), str) and LIBRARY_RE.match(raw["library"]) else ""
    credential = raw.get("credential") if isinstance(raw.get("credential"), str) and CREDENTIAL_RE.match(raw["credential"]) else ""
    return {"mode": mode, "library": library or ("users/0" if mode == "local" else ""), "credential": credential}


def update(patch: dict) -> dict:
    """Change mode, library or credential (null or "" removes the last two). Raises ValueError on a bad value."""
    cur = dict(config.user_settings().get("zotero") or {})
    if "mode" in patch:
        if patch["mode"] not in MODES:
            raise ValueError("mode is local (the Zotero app on this computer) or web (zotero.org)")
        cur["mode"] = patch["mode"]
    for key, pattern, hint in (("library", LIBRARY_RE, "users/<id> or groups/<id>"),
                               ("credential", CREDENTIAL_RE, "keychain:<item name> or env:<VARIABLE>")):
        if key in patch:
            value = (patch[key] or "").strip() if isinstance(patch[key], str) or patch[key] is None else None
            if value is None:
                raise ValueError(f"{key} must be text")
            if not value:
                cur.pop(key, None)
            elif not pattern.match(value):
                raise ValueError(f"{key} must look like {hint}")
            else:
                cur[key] = value
    config.save_user_setting("zotero", cur or None)
    _STATE["check"] = None
    return status()


_STATE: dict[str, Any] = {"connect": {"state": "idle", "message": ""}, "check": None}
_LOCK = threading.Lock()


def status() -> dict:
    s = settings()
    key = vault.read_json(SECRET) or {}
    return {**s, "local_key": bool(key.get("key")), "local_remember": key.get("remember"),
            "connect": dict(_STATE["connect"]), "check": _STATE["check"]}


def forget_local_key() -> None:
    vault.delete(SECRET)


# ---------------------------------------------------------------- the client

def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _explain(mode: str, r: httpx.Response) -> str:
    code = r.status_code
    try:
        detail = r.text.strip()[:200]
    except Exception:  # noqa: BLE001
        detail = ""
    if mode == "local" and code == 403:
        return ("Zotero refuses other applications: turn on Settings → Advanced → \"Allow other applications on this "
                "computer to communicate with Zotero\"")
    if mode == "local" and code == 401:
        return "Zotero needs to authorize Research Deck again: Settings → Zotero → Connect, and choose Always Allow"
    if code in (401, 403):
        return "the API key cannot write to this Zotero library (create one with write access at zotero.org/settings/keys)"
    if code == 404:
        return f"Zotero has no such library, collection or item ({detail or 'not found'})"
    if code == 409:
        return "the Zotero library is locked; try again in a moment"
    if code == 413:
        return "the file does not fit in your Zotero storage"
    if code == 428:
        return "Zotero expected a precondition header (Zotero-Server-ID or If-None-Match)"
    return f"Zotero answered {code}: {detail}"


def _unreachable(mode: str, e: Exception) -> str:
    if mode == "local":
        return "the Zotero app is not running on this computer (writing through it needs Zotero 10 or later)"
    return f"cannot reach api.zotero.org: {e.__class__.__name__}"


class Client:
    def __init__(self, mode: str, library: str, key: str | None = None, http: httpx.Client | None = None):
        if mode not in MODES or not LIBRARY_RE.match(library or ""):
            raise ZoteroError("the Zotero settings are incomplete: choose the app or zotero.org, and the library")
        self.mode, self.library, self.key = mode, library, key
        self.origin = LOCAL_ORIGIN if mode == "local" else WEB_ORIGIN
        self.base = self.origin + ("/api" if mode == "local" else "")
        self.prefix = "/" + library
        self.http = http or httpx.Client(timeout=TIMEOUT, transport=TRANSPORT)
        self.server_id: str | None = None

    def _headers(self, write: bool, extra: dict | None) -> dict:
        h = {"Zotero-API-Version": "3", "User-Agent": UA}
        if self.mode == "local":
            h["Zotero-Allowed-Request"] = "1"
            if write and self.server_id:
                h["Zotero-Server-ID"] = self.server_id
        if self.key and (write or self.mode == "web"):
            h["Zotero-API-Key"] = self.key
        h.update(extra or {})
        return h

    def request(self, method: str, path: str, *, write: bool = False, headers: dict | None = None, **kw: Any) -> httpx.Response:
        if write and self.mode == "local" and not self.server_id:
            self.request("GET", f"{self.prefix}/collections", params={"limit": 1})
        r: httpx.Response | None = None
        for attempt in range(3):
            try:
                r = self.http.request(method, self.base + path, headers=self._headers(write, headers),
                                      follow_redirects=False, **kw)
            except httpx.HTTPError as e:
                raise ZoteroError(_unreachable(self.mode, e)) from e
            if r.headers.get("Zotero-Server-ID"):
                self.server_id = r.headers["Zotero-Server-ID"]
            if r.status_code in (429, 503) and attempt < 2:
                time.sleep(min(_seconds(r.headers.get("Retry-After"), 2.0), 10.0))
                continue
            break
        assert r is not None
        if r.headers.get("Backoff"):
            time.sleep(min(_seconds(r.headers["Backoff"], 0.0), 10.0))
        if r.status_code >= 400:
            raise ZoteroError(_explain(self.mode, r), r.status_code)
        return r

    # ------------------------------------------------------------ reads

    def check(self) -> dict:
        """Who the key belongs to (zotero.org) and whether the library answers."""
        out: dict[str, Any] = {"mode": self.mode, "library": self.library}
        if self.mode == "web":
            k = self.request("GET", "/keys/current").json()
            out["user"] = {"id": k.get("userID"), "name": k.get("username")}
            lib = (k.get("access") or {}).get("user") or {}
            out["write"] = bool(lib.get("write")) if self.library.startswith("users/") else None
        r = self.request("GET", f"{self.prefix}/collections", params={"limit": 1})
        out["version"] = _int(r.headers.get("Last-Modified-Version"))
        return out

    def collections(self) -> list[dict]:
        out: list[dict] = []
        start = 0
        while True:
            r = self.request("GET", f"{self.prefix}/collections", params={"format": "json", "limit": 100, "start": start})
            batch = r.json() or []
            out += [{"key": c.get("key"), "name": (c.get("data") or {}).get("name") or "",
                     "parent": (c.get("data") or {}).get("parentCollection") or None} for c in batch]
            start += len(batch)
            if not batch or start >= (_int(r.headers.get("Total-Results")) or 0):
                return out

    def items(self, collection: str, since: int | None = None) -> tuple[list[dict] | None, int | None]:
        """The collection's top-level items (their Zotero JSON data) and the library version; (None, since) when the
        library has not changed since `since`."""
        out: list[dict] = []
        start, version = 0, None
        while True:
            extra = {"If-Modified-Since-Version": str(since)} if since and start == 0 else None
            r = self.request("GET", f"{self.prefix}/collections/{collection}/items/top",
                             params={"format": "json", "limit": 100, "start": start}, headers=extra)
            if r.status_code == 304:
                return None, since
            version = version or _int(r.headers.get("Last-Modified-Version"))
            batch = r.json() or []
            out += [dict(b.get("data") or {}, key=b.get("key") or (b.get("data") or {}).get("key")) for b in batch]
            start += len(batch)
            if not batch or start >= (_int(r.headers.get("Total-Results")) or 0):
                return out, version

    # ------------------------------------------------------------ writes

    def _write(self, kind: str, objects: list[dict]) -> list[tuple[str | None, str | None]]:
        """POST objects in batches of 50; (key, None) for each one written, (None, why) for each one refused."""
        out: list[tuple[str | None, str | None]] = []
        for i in range(0, len(objects), 50):
            chunk = objects[i:i + 50]
            data = self.request("POST", f"{self.prefix}/{kind}", write=True, json=chunk,
                                headers={"Zotero-Write-Token": uuid.uuid4().hex}).json() or {}
            ok, keys, failed = data.get("successful") or {}, data.get("success") or {}, data.get("failed") or {}
            for j in range(len(chunk)):
                s = ok.get(str(j))
                key = (s.get("key") or (s.get("data") or {}).get("key")) if isinstance(s, dict) else keys.get(str(j))
                if key:
                    out.append((key, None))
                else:
                    f = failed.get(str(j)) or {}
                    out.append((None, f.get("message") or "Zotero did not say why"))
        return out

    def create_collection(self, name: str, parent: str | None = None) -> str:
        obj = {"name": name[:255] or "Research Deck"}
        if parent:
            obj["parentCollection"] = parent
        (key, why), = self._write("collections", [obj])
        if not key:
            raise ZoteroError(f"Zotero refused the collection: {why}")
        return key

    def create_items(self, items: list[dict]) -> list[tuple[str | None, str | None]]:
        return self._write("items", items)

    def attach_pdf(self, parent: str, file: Path, filename: str, url: str | None = None) -> str:
        """Add the PDF as a stored attachment of the item `parent` (create, authorize, upload, register)."""
        att: dict[str, Any] = {"itemType": "attachment", "parentItem": parent,
                               "linkMode": "imported_url" if url else "imported_file", "title": "Full Text PDF",
                               "contentType": "application/pdf", "charset": "", "filename": filename, "tags": [],
                               "relations": {}}
        if url:
            att.update(url=url, accessDate=_now())
        (key, why), = self._write("items", [att])
        if not key:
            raise ZoteroError(f"Zotero refused the attachment: {why}")
        data = file.read_bytes()
        form = {"md5": hashlib.md5(data).hexdigest(), "filename": filename, "filesize": str(len(data)),
                "mtime": str(int(file.stat().st_mtime * 1000))}
        auth = self.request("POST", f"{self.prefix}/items/{key}/file", write=True, data=form,
                            headers={"If-None-Match": "*"}).json() or {}
        if auth.get("exists"):
            return key
        target = self._upload_url(str(auth.get("url") or ""))
        body = str(auth.get("prefix") or "").encode() + data + str(auth.get("suffix") or "").encode()
        headers = {"Content-Type": str(auth.get("contentType") or "application/pdf"), "User-Agent": UA}
        if self.mode == "local":
            headers["Zotero-Allowed-Request"] = "1"
        try:
            up = self.http.post(target, content=body, headers=headers, follow_redirects=False, timeout=120.0)
        except httpx.HTTPError as e:
            raise ZoteroError(f"the PDF upload failed: {e.__class__.__name__}") from e
        if up.status_code not in (200, 201, 204):
            raise ZoteroError(f"the PDF upload failed: {up.status_code}")
        self.request("POST", f"{self.prefix}/items/{key}/file", write=True, data={"upload": str(auth.get("uploadKey") or "")},
                     headers={"If-None-Match": "*"})
        return key

    def _upload_url(self, url: str) -> str:
        """The upload address Zotero returned: zotero.org's storage over https, or the local app itself."""
        if self.mode == "local":
            if url.startswith("/"):
                url = self.origin + url
            host = urlparse(url).hostname or ""
            if host not in ("127.0.0.1", "localhost", "::1"):
                raise ZoteroError("Zotero returned an upload address that is not this computer")
            return url
        p = urlparse(url)
        if p.scheme != "https" or not p.hostname:
            raise ZoteroError("Zotero returned an upload address that is not https")
        return url


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _seconds(v: Any, default: float) -> float:
    try:
        return max(0.0, float(v))
    except (TypeError, ValueError):
        return default


def client(http: httpx.Client | None = None) -> Client:
    """A client for this computer's Zotero settings. Raises ZoteroError when they are incomplete."""
    s = settings()
    if s["mode"] == "local":
        key = (vault.read_json(SECRET) or {}).get("key")
        return Client("local", s["library"] or "users/0", key=key, http=http)
    if not s["library"]:
        raise ZoteroError("set the zotero.org library (users/<id> or groups/<id>) in Settings → Zotero")
    if not s["credential"]:
        raise ZoteroError("name the Keychain item that holds your zotero.org API key in Settings → Zotero")
    from ..pools.sources import SourceError, resolve_credential
    try:
        key = resolve_credential(s["credential"])
    except SourceError as e:
        raise ZoteroError(str(e)) from e
    return Client("web", s["library"], key=key, http=http)


# ---------------------------------------------------------------- connecting

def authorize_local(app_name: str = "Research Deck", timeout: float = 180.0) -> dict:
    """Ask the Zotero app for a write key: it shows Allow / Always Allow / Deny. The key is kept in the vault."""
    c = Client("local", "users/0")
    c.request("GET", "/users/0/collections", params={"limit": 1})       # running, allowed, and its server id
    try:
        r = c.http.post(LOCAL_ORIGIN + "/api/local/authorize", json={"appName": app_name}, follow_redirects=False,
                        headers={"Zotero-Server-ID": c.server_id or "", "Zotero-Allowed-Request": "1", "User-Agent": UA},
                        timeout=httpx.Timeout(timeout, connect=5.0))
    except httpx.TimeoutException as e:
        raise ZoteroError("Zotero's authorization dialog was not answered in time") from e
    except httpx.HTTPError as e:
        raise ZoteroError(_unreachable("local", e)) from e
    if r.status_code == 403:
        raise ZoteroError("Research Deck was denied in Zotero's dialog")
    if r.status_code == 429:
        raise ZoteroError("too many authorization requests: wait a minute and try again")
    if r.status_code >= 400:
        raise ZoteroError(_explain("local", r), r.status_code)
    data = r.json() or {}
    if not data.get("key"):
        raise ZoteroError("Zotero granted no key")
    vault.write_json({"key": data["key"], "remember": bool(data.get("remember")), "server_id": c.server_id, "at": _now()}, SECRET)
    return {"remember": bool(data.get("remember"))}


def connect() -> dict:
    """The app: start the authorization (the dialog waits for the researcher, so it runs in a thread). zotero.org:
    check the key now. Returns the status."""
    s = settings()
    if s["mode"] == "web":
        check_now()
        return status()
    with _LOCK:
        if _STATE["connect"]["state"] == "waiting":
            return status()
        _STATE["connect"] = {"state": "waiting", "message": "answer the dialog in Zotero (choose Always Allow)"}

    def run() -> None:
        try:
            res = authorize_local()
            msg = "connected" if res["remember"] else "connected for one write only: connect again and choose Always Allow"
            _STATE["connect"] = {"state": "done", "message": msg}
            check_now()
        except ZoteroError as e:
            _STATE["connect"] = {"state": "error", "message": str(e)}

    threading.Thread(target=run, name="rd-zotero-authorize", daemon=True).start()
    return status()


def check_now() -> dict:
    try:
        res = client().check()
        _STATE["check"] = {"ok": True, "at": _now(), **res}
    except ZoteroError as e:
        _STATE["check"] = {"ok": False, "at": _now(), "message": str(e)}
    return _STATE["check"]


# ---------------------------------------------------------------- papers ⇄ items

def _creators(names: list[str]) -> list[dict]:
    out = []
    for n in names or []:
        n = (n or "").strip()
        if not n:
            continue
        first, _, last = n.rpartition(" ")
        out.append({"creatorType": "author", "firstName": first, "lastName": last} if first else
                   {"creatorType": "author", "name": n})
    return out


def item_from_paper(p: dict, citation_key: str, collection: str | None) -> dict:
    """A Zotero item for a paper the survey kept. Its citation key goes in Extra, where Better BibTeX looks too."""
    venue = (p.get("venue") or "").strip()
    if p.get("arxiv") and venue in ("", "arXiv"):
        item: dict[str, Any] = {"itemType": "preprint", "repository": "arXiv", "archiveID": f"arXiv:{p['arxiv']}"}
    elif bib.CONFERENCE.search(venue):
        item = {"itemType": "conferencePaper", "proceedingsTitle": venue}
    elif venue:
        item = {"itemType": "journalArticle", "publicationTitle": venue}
    else:
        item = {"itemType": "preprint"}
    item.update(title=(p.get("title") or "")[:1000], creators=_creators(p.get("authors") or []),
                date=str(p.get("year") or ""), url=p.get("url") or "", extra=f"Citation Key: {citation_key}",
                tags=[{"tag": "Research Deck"}], collections=[collection] if collection else [])
    if p.get("doi"):
        item["DOI"] = p["doi"]
    if p.get("abstract"):
        item["abstractNote"] = str(p["abstract"])[:10000]
    return item


KEY_IN_EXTRA = re.compile(r"^\s*citation key\s*:\s*(\S+)\s*$", re.I | re.M)
ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5}(?:v\d+)?)")


def citation_key(item: dict) -> str | None:
    """The key the item asks for: Zotero's own citationKey field, or "Citation Key: …" in Extra (Better BibTeX's pin)."""
    for raw in (item.get("citationKey"), (KEY_IN_EXTRA.search(item.get("extra") or "") or [None, None])[1]):
        if raw:
            key = re.sub(r"[^A-Za-z0-9_:.\-]", "", str(raw))[:80]
            if key:
                return key
    return None


def paper_from_item(item: dict) -> dict:
    """The fields references.bib needs, from an item's Zotero JSON."""
    creators = item.get("creators") or []
    authors = [c for c in creators if c.get("creatorType") in (None, "author", "inventor", "programmer")] or creators
    names = [c.get("name") or " ".join(x for x in (c.get("firstName"), c.get("lastName")) if x) for c in authors]
    year = re.search(r"\b(1[5-9]\d\d|2\d\d\d)\b", item.get("date") or "")
    venue = next((item.get(k) for k in ("publicationTitle", "proceedingsTitle", "conferenceName", "bookTitle",
                                         "university", "institution", "publisher", "repository", "websiteTitle")
                  if item.get(k)), "")
    arxiv = None
    for source in (item.get("archiveID"), item.get("extra"), item.get("url")):
        m = ARXIV_ID.search(source or "") if source and ("arxiv" in source.lower()) else None
        if m:
            arxiv = m.group(1)
            break
    return {"title": item.get("title") or "", "authors": [n for n in names if n], "year": int(year.group(1)) if year else None,
            "venue": venue, "doi": item.get("DOI") or None, "arxiv": arxiv, "url": item.get("url") or None,
            "type": item.get("itemType")}


def item_link(library: str, key: str) -> str:
    kind, _, lid = library.partition("/")
    return f"zotero://select/library/items/{key}" if kind == "users" else f"zotero://select/groups/{lid}/items/{key}"


def pdf_link(library: str, key: str) -> str:
    kind, _, lid = library.partition("/")
    return f"zotero://open-pdf/library/items/{key}" if kind == "users" else f"zotero://open-pdf/groups/{lid}/items/{key}"
