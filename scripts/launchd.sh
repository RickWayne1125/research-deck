#!/bin/zsh
# Run Research Deck as a macOS launchd user agent: started at login, restarted if it exits, logs in ~/.research-deck/logs.
#   scripts/launchd.sh install     build the web app if needed, write the agent and start it
#   scripts/launchd.sh uninstall   stop it and remove the agent
#   scripts/launchd.sh restart     restart after an update (e.g. git pull)
#   scripts/launchd.sh status      is it loaded and answering?
# The server still listens on 127.0.0.1 only; publishing on a tailnet is a separate `tailscale serve` (README).
set -e
ROOT="${0:A:h:h}"
LABEL="local.research-deck"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGS="${RD_LOCAL_DIR:-$HOME/.research-deck}/logs"
DOMAIN="gui/$(id -u)"
PORT="${RD_PORT:-8765}"

health() { curl -s -m 3 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/system/health" 2>/dev/null || true; }

case "${1:-status}" in
  install)
    [[ -x "$ROOT/.venv/bin/python" ]] || { echo "missing $ROOT/.venv (see README)"; exit 1; }
    if [[ ! -f "$ROOT/web/dist/index.html" ]]; then
      [[ -n "$RD_NODE_BIN" ]] && export PATH="$RD_NODE_BIN:$PATH"
      command -v pnpm >/dev/null || { echo "build the web app first (scripts/dev.sh), or put pnpm on PATH / set RD_NODE_BIN"; exit 1; }
      (cd "$ROOT/web" && { [[ -d node_modules ]] || pnpm install --frozen-lockfile; } && pnpm exec vite build >/dev/null)
    fi
    if [[ "$(health)" == "200" ]] && ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      echo "something else already serves :$PORT; stop it first"; exit 1
    fi
    mkdir -p "$LOGS" "$HOME/Library/LaunchAgents"
    # PATH: git (Homebrew or Xcode tools) and the claude CLI (~/.local/bin); Codex is found at its app path.
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$ROOT/.venv/bin/python</string><string>-m</string><string>research_deck</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT/server</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$LOGS/server.log</string>
  <key>StandardErrorPath</key><string>$LOGS/server.log</string>
</dict>
</plist>
EOF
    plutil -lint "$PLIST" >/dev/null
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    launchctl enable "$DOMAIN/$LABEL"
    for i in {1..40}; do [[ "$(health)" == "200" ]] && break; sleep 0.5; done
    echo "installed $PLIST; health: $(health)"
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed $LABEL"
    ;;
  restart)
    launchctl kickstart -k "$DOMAIN/$LABEL"
    for i in {1..40}; do [[ "$(health)" == "200" ]] && break; sleep 0.5; done
    echo "restarted; health: $(health)"
    ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      launchctl print "$DOMAIN/$LABEL" | grep -E "^\s*(state|pid|last exit code) =" || true
    else
      echo "$LABEL is not loaded"
    fi
    echo "health: $(health)   logs: $LOGS/server.log"
    ;;
  *) echo "usage: $0 install|uninstall|restart|status"; exit 2 ;;
esac
