#!/bin/zsh
# Build the web app and serve Research Deck on http://127.0.0.1:8765 (loopback only).
#   scripts/dev.sh          build web/ then serve the backend
#   scripts/dev.sh --vite   serve the backend and the Vite dev server (http://127.0.0.1:5173) with hot reload
set -e
ROOT="${0:A:h:h}"
# Node.js 20+ and pnpm come from PATH, or from RD_NODE_BIN (a folder that holds both).
[[ -n "$RD_NODE_BIN" ]] && export PATH="$RD_NODE_BIN:$PATH"
command -v pnpm >/dev/null || { echo "pnpm not found: install Node.js 20+ and run 'corepack enable', or set RD_NODE_BIN"; exit 1; }
cd "$ROOT"
[[ -d web/node_modules ]] || (cd web && pnpm install --frozen-lockfile)
if [[ "$1" == "--vite" ]]; then
  export RD_DEV=1          # lets the Vite origin (:5173) call the API
  (cd web && pnpm exec vite) &
  trap "kill $! 2>/dev/null" EXIT
else
  (cd web && pnpm exec vite build >/dev/null)
fi
cd server && exec ../.venv/bin/python -m research_deck
