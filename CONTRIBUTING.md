# Contributing to Research Deck

Thank you for helping. This guide covers the development setup, the checks every change passes, and how to send it.
Research Deck is a local tool that drives AI agents inside people's research folders, so its safety rules matter as
much as its features: please read the **Safety** notes under [Conventions every slice follows](https://github.com/RickWayne1125/research-deck/blob/main/docs/ARCHITECTURE.md#conventions-every-slice-follows) before changing anything
that touches files, agents, the network or credentials.

## Set up

Requirements: Python 3.12+, Node.js 20+ with pnpm (`corepack enable`), git.

```bash
git clone https://github.com/RickWayne1125/research-deck.git
cd research-deck
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev,docs]'
(cd web && pnpm install --frozen-lockfile)
```

Run it while you work:

```bash
RD_FAKE_AGENT=1 scripts/dev.sh --vite   # backend + Vite with hot reload on http://127.0.0.1:5173, canned agent answers
RD_LOCAL_DIR=/tmp/rd-dev scripts/dev.sh # a throwaway machine state instead of ~/.research-deck
```

## The checks

CI runs these on every pull request and on `main`; run them before you push.

| Check | Command |
|---|---|
| Python lint | `.venv/bin/ruff check .` |
| Python tests | `.venv/bin/python -m pytest -q` |
| TypeScript (strict, no unused code) | `(cd web && pnpm typecheck)` |
| Web tests | `(cd web && pnpm test)` |
| Web build | `(cd web && pnpm exec vite build)` |
| Documentation | `.venv/bin/mkdocs build --strict` |

CI also starts the built app and checks that it serves the page, the API and the demo project.
To run ruff and a few file checks at each commit: `pip install pre-commit && pre-commit install` (configuration in
`.pre-commit-config.yaml`; the hooks only check, they never rewrite files).

## Conventions

- **Backend.** One package per area under `server/research_deck/` with its routes in `<pkg>/api.py`. Paths from
  requests go through `util.safe_join`; writes through `util.write_json` / `write_yaml` / `write_text_atomic`; after a
  change, `events.hub.publish(pid, topic, payload)`. Agent runs go through `agents.api.spec_for` and `runner`, never a
  CLI spawned directly. Whatever only the researcher may do checks `actors.is_human`. Docstrings say what a module is
  for and what its routes return; [docs/ARCHITECTURE.md](https://github.com/RickWayne1125/research-deck/blob/main/docs/ARCHITECTURE.md) lists the conventions in full.
- **Frontend.** One folder per view under `web/src/panels/`; shared pieces in `components/`. Colors are tokens from
  `styles/tokens.css`, never hex values in components. Every string goes through `i18n` in both Chinese and English.
- **Tests.** Backend tests use `RD_FAKE_AGENT` fakes (`runner.register_fake`) and temporary folders; never a real CLI,
  the network or `~/.research-deck`. Pure logic in the web app gets a `*.test.ts` next to it.
- **No project content in the repo.** Research Deck is generic: examples and tests use made-up content, and the only
  bundled project is the minimal demo in `demo/minimal`. Its files make the demo's fixed git history, so change them
  only on purpose (and expect `tests/test_demo.py` to tell you what moved).
- **Docs move with the code.** A new route goes into [docs/API.md](https://github.com/RickWayne1125/research-deck/blob/main/docs/API.md), a change to the map's model into
  [docs/DAG.md](https://github.com/RickWayne1125/research-deck/blob/main/docs/DAG.md), and anything a user sees into the guide under `docs/`.
- **Commits.** Small and focused, with a message that says what changes and why, in plain words. Keep unrelated
  formatting out of a change.

## Send a change

1. Fork the repository and branch from `main`.
2. Make the change with its tests and docs; run the checks above.
3. Open a pull request. The template asks what changed, how you tested it, and whether it touches safety.
4. A maintainer reviews it; CI must pass before it is merged.

For a larger change (a new view, a change to the map's model, anything that reaches the network), open an issue first
to agree on the approach.

## Report a problem

Open an issue with what you did, what you expected and what happened, plus the server log
(`~/.research-deck/logs/server.log`, or the terminal that runs `scripts/dev.sh`). Please report security problems
privately through GitHub's *Report a vulnerability* on the repository's Security tab, not in a public issue.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](https://github.com/RickWayne1125/research-deck/blob/main/LICENSE).
