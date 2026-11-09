# Zotero and Docmost

Two optional connections, both set up under **Settings**. Without them, a project keeps its papers as files and its
notes stay in the project folder.

## Zotero: papers in a collection instead of files

**Connect this computer** (Settings → Zotero → This computer), one of two ways:

- **The Zotero app here.** Needs Zotero 10 or later running, with Settings → Advanced → "Allow other applications on
  this computer to communicate with Zotero" on. Click **Connect**: Zotero asks whether Research Deck may write to it.
  Choose **Always Allow** ("Allow" is good for one write only). The key Zotero grants is kept in
  `~/.research-deck/secrets/`.
- **zotero.org.** Create a key with write access at <https://www.zotero.org/settings/keys>, put it in the Keychain,
  and enter its name and your library (`users/<your ID>`, shown on that page, or `groups/<group ID>`):

    ```bash
    security add-generic-password -s zotero-api-key -a "$USER" -w     # paste the key when asked
    ```

**Choose it for a project** (Settings → Zotero → This project): **A Zotero collection**, then pick an existing
collection or let Research Deck create one named after the project. To use Zotero for every new project, choose it
under Settings → New projects → Literature.

From then on the early survey makes each paper it keeps an item of the collection, with the open-access PDF attached,
and writes no PDFs into the project. The project keeps only `references.bib`, so a LaTeX paper still builds:

- **Export now** rewrites it from the collection (the survey does so too). Only the block between `% >>> zotero` and
  `% <<< zotero` is rewritten; entries you wrote yourself stay. An entry of yours with the same key as an exported
  one is commented out, not deleted.
- Keys come from `Citation Key: …` in an item's Extra field, where Better BibTeX pins its keys, or are made up as
  lastname + year + first title word. The survey pins the keys it chooses.
- In `notes/survey.md`, a paper's link opens it in Zotero (`zotero://…`).

## Docmost: notes on a wiki page

**Sign in** (Settings → Docmost → This computer): enter your site's address and click **Sign in**. A window opens on
the computer that runs Research Deck; sign in as you always do, single sign-on included. The window closes once
Docmost knows who you are. Research Deck keeps that site's cookies in `~/.research-deck/secrets/docmost/` and sends
them only to that site.

Why a window of its own: your usual browser keeps Docmost's sign-in to itself (another site cannot read it), and the
sync runs on the server, also when no browser is open.

- **On a Mac** it is a Mac window with the system's WebKit, the engine of Safari: nothing to download. Research Deck
  builds it the first time (a few seconds) with Xcode's Command Line Tools; if they are missing, run
  `xcode-select --install`.
- **Elsewhere**, or if your single sign-on refuses to open inside an app window (Google's does), use Chromium through
  Playwright, installed once:

    ```bash
    .venv/bin/pip install -e '.[docmost]'      # then Settings → Docmost → Install the sign-in browser (about 150 MB)
    ```

**Bind a project** (Settings → Docmost → This project): paste the link of a Docmost page and click **Bind**. Every
`.md` file under `notes/` becomes a page under it. A note's first `# ` heading is the page's title, or else its file
name is. Research Deck's own `<!-- rd:… -->` tags stay out of the pages; the outline file (`notes/outline.md`) is
pushed like any note, but cannot take Docmost's version, since it follows the outline.

**Sync** goes one way, notes → Docmost: right after binding, then every minute while you are signed in, and on
**Sync now**. A page edited in Docmost since the last push is never overwritten. Its note shows **Conflict**, and
**Review** shows what was changed there. Merge what you want to keep into the note and **Push my note**, or **Use
Docmost's version** to write the page into the note. A page deleted in Docmost is not recreated until you ask; a note
you delete leaves its page in place.

When Docmost asks you to sign in again, Research Deck first tries your saved browser profile without a window. Settings
shows **Not signed in** only if that fails.
