"""The Docmost sign-in window, a process of its own:

    python -m research_deck.docmost.login --url https://docs.example.com --profile DIR --out FILE [--headless] [--timeout S]

Chromium (Playwright, the optional extra research-deck[docmost]) opens the site with a browser profile of its own, and
the researcher signs in as they always do, SSO included. Once the site has set Docmost's `authToken` cookie and
/api/users/me answers, the site's cookies, the browser's user agent and who signed in are written to --out (mode
0600) and the window closes. --headless only tries the saved profile, for a sign-in that is still valid, and gives up
quietly. Nothing else is read from the browser, and nothing is sent anywhere.

Exit codes: 0 signed in, 2 Playwright is not installed, 3 the window was closed, 4 timed out, 5 Chromium is missing,
6 the site could not be opened.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

KEEP = ("name", "value", "domain", "path", "expires", "secure", "httpOnly", "sameSite")


def _write_private(path: str, data: dict) -> None:
    tmp = f"{path}.tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m research_deck.docmost.login")
    ap.add_argument("--url", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--timeout", type=float, default=300.0)
    a = ap.parse_args(argv)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed: pip install 'research-deck[docmost]'", file=sys.stderr)
        return 2
    url = a.url.rstrip("/")
    with sync_playwright() as pw:
        try:
            ctx = pw.chromium.launch_persistent_context(a.profile, headless=a.headless, no_viewport=not a.headless)
        except PlaywrightError as e:
            text = str(e)
            if "Executable doesn't exist" in text or "playwright install" in text:
                print("Chromium is not installed: python -m playwright install chromium", file=sys.stderr)
                return 5
            print(f"the browser did not start: {text.splitlines()[0] if text else e}", file=sys.stderr)
            return 6
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except PlaywrightError as e:
                print(f"could not open {url}: {str(e).splitlines()[0]}", file=sys.stderr)
                return 6
            deadline = time.monotonic() + a.timeout
            while time.monotonic() < deadline:
                if not ctx.pages:
                    return 3
                cookies = ctx.cookies([url])
                if any(c.get("name") == "authToken" for c in cookies):
                    r = ctx.request.post(url + "/api/users/me", data="{}", headers={"Content-Type": "application/json"})
                    if r.ok:
                        body = r.json()
                        data = body.get("data", body) if isinstance(body, dict) else {}
                        user = data.get("user") if isinstance(data.get("user"), dict) else data
                        try:
                            ua = ctx.pages[0].evaluate("navigator.userAgent") if ctx.pages else ""
                        except PlaywrightError:
                            ua = ""
                        _write_private(a.out, {
                            "url": url, "user_agent": ua, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "cookies": [{k: c[k] for k in KEEP if k in c} for c in ctx.cookies([url])],
                            "user": {k: user.get(k) for k in ("id", "name", "email")} if isinstance(user, dict) else {}})
                        return 0
                time.sleep(1.0)
            return 4
        finally:
            try:
                ctx.close()
            except PlaywrightError:
                pass


if __name__ == "__main__":
    sys.exit(main())
