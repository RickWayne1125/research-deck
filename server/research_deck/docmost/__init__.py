"""Docmost: this computer's sign-in to a Docmost site, and a project's notes kept in sync with a page there.

  client.py   the site (settings.json "docmost": {"url"}), the saved sign-in, and the page calls the sync needs
  login.swift the sign-in window on macOS, a process of its own: a Mac window with the system's WebKit opens the site,
              the researcher signs in as usual (SSO included), and the site's cookies come back once Docmost knows
              who they are. Built once with `xcrun swiftc`; nothing to download
  login.py    the same window elsewhere (python -m research_deck.docmost.login): Chromium through Playwright, the
              optional extra research-deck[docmost]
  session.py  which window this computer uses, building or installing it, starting and watching it, and a quiet
              renewal with what the window kept of the site
  sync.py     a project's binding (project.yaml "docmost") and the one-way sync of notes/*.md into child pages of
              the bound page; a page edited in Docmost since the last push waits for the researcher's review
  api.py      routes (docs/API.md § Docmost)

The sign-in and the browser profile live in ~/.research-deck/secrets/docmost/ (vault.py) and go only to that site.
"""
