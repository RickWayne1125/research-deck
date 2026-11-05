## What changes and why

<!-- A few sentences: what a user or a developer will notice, and the reason. Link the issue if there is one. -->

## How it was tested

- [ ] `ruff check .` and `python -m pytest -q`
- [ ] `pnpm typecheck`, `pnpm test` and `pnpm exec vite build` in `web/`
- [ ] `mkdocs build --strict` (when docs changed)
- [ ] Tried in the browser (what you clicked through):

## Checklist

- [ ] Tests cover the change (backend: fakes and temporary folders; web: `*.test.ts` for pure logic)
- [ ] Docs updated: `docs/API.md` for routes, `docs/DAG.md` for the map's model, the guide for anything users see
- [ ] Both languages for new UI strings (Chinese and English)
- [ ] No project content, personal data or credentials in the change

## Safety

<!-- Does this touch files outside .research/, agent permissions, the network, credentials or what the server accepts?
     If yes, say how it stays within docs/ARCHITECTURE.md (Safety). -->
- [ ] It does not touch any of these
