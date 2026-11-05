# The MCP server in your own terminal

The dashboard passes its MCP server to every run it starts. To give your own Claude Code or Codex session in the
project folder the same tools (the outline, the map, impact previews, proposals), register the server once. Nothing
registers it by itself.

## 1. Get the command for your machine

**Settings** shows the exact commands, with your paths filled in. The same is available from the API:

```bash
curl -s 'http://127.0.0.1:8765/api/mcp/config?project=<project id>'
```

`commands.claude` and `commands.codex` in the answer look like this (paths shortened):

```bash
claude mcp add research-deck -s user \
  -e PYTHONPATH=…/research-deck/server -e RD_URL=http://127.0.0.1:8765 \
  -e RD_LOCAL_DIR=~/.research-deck -e RD_ACTOR=agent:claude:terminal \
  -- …/research-deck/.venv/bin/python -m research_deck.mcp_server --project <project id>
```

Research Deck must be running for the tools to answer. The server identifies itself to the dashboard with the agents'
token in `~/.research-deck/`, so what it does is recorded as an agent's, with an agent's permissions.

## 2. Use it

In the project folder, start `claude` (or `codex`) and ask, for example:

- *"Read the brief and the outline. Which items of the current phase do not hold yet, and what would make each hold?"*
  (`rd_brief`, `rd_outline`)
- *"Suggest experiment tasks for 5.2 and add an item under 3.1 for the tie-breaking rule."* (`rd_suggest_task`,
  `rd_outline_ops`; both wait for you on the outline page)
- *"What would changing the cache capacity to 128 blocks invalidate?"* (`rd_impact`)

## 3. Remove it

```bash
claude mcp remove research-deck -s user
codex mcp remove research-deck
```
