# Configuration

## Machine settings: `~/.research-deck/settings.json`

Your own defaults, shared by every project on this machine. Missing keys take the built-in defaults.

```json
{
  "agent_defaults": {"claude": {"model": "claude-opus-5-5", "effort": "high"}, "codex": {"effort": "high"}},
  "dag_defaults": {"gates": {"blocking": false}, "autocommit": {"enabled": false}, "stages": {"mode": "strict"}},
  "new_projects": {"dir": "~/Research", "git_init": true,
                   "survey": {"sources": ["arxiv", "semantic_scholar", "openalex"], "count": 15,
                              "download_pdfs": true, "papers_dir": "papers"}},
  "tailnet": {"host": "<machine>.<tailnet>.ts.net", "https_port": 8765, "owners": ["you@example.com"]}
}
```

| Key | What |
|---|---|
| `agent_defaults` | model and effort per CLI for new conversations |
| `dag_defaults` | defaults for new maps: blocking gates, git autocommit of the map, stage rules (`strict`, `ahead`, `free`) |
| `new_projects` | where **New from an idea** creates folders, `git init`, and the early survey's sources, size and PDF folder |
| `tailnet` | accept requests through Tailscale Serve from these owners only (see [Installation](../getting-started/install.md)) |

Most of these are also in **Settings**.

## A project: `.research/project.yaml`

Name, kind (`research` or `engineering`), `views`, summary, venue, deadline, stage, language, and where the paper
(`paper.main`, `paper.dir`), code (`code.roots`), figures and experiment records live.

## A project's map: `.research/dag/config.yaml`

The map's policy: gates (and whether they block), autocommit, stage rules, code and config roots for fingerprints, and
`policy.agent_auto_run` (the platforms agents may queue runs on and their daily GPU-hour budget).

## Outline templates: `~/.research-deck/templates/`

Your outline templates, one YAML file each; see [An outline template of your own](../examples/template.md).

## Environment variables

| Variable | Default | What |
|---|---|---|
| `RD_PORT` | `8765` | the port (the server always binds 127.0.0.1) |
| `RD_LOCAL_DIR` | `~/.research-deck` | machine state: registry, settings, templates, demo |
| `RD_FAKE_AGENT` | unset | `1`: canned agent answers instead of the CLIs |
| `RD_NO_DEMO` | unset | `1`: do not create the demo project |
| `RD_CLAUDE_CLI`, `RD_CODEX_CLI` | found on `PATH` | paths to the CLIs |
| `RD_FIGURE_PYTHON` | the project venv's Python | the Python that renders matplotlib figures |
| `RD_EXTRA_ORIGINS` | none | extra allowed origins, comma-separated |
| `RD_NODE_BIN` | none | a folder with `node` and `pnpm` for `scripts/dev.sh` |
