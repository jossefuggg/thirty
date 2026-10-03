#!/usr/bin/env bash
# Start Vigil Console v2 in the background on http://localhost:5001 (survives closing the terminal).
# Runs under the docker group (like `vigil.py sync`) so console approvals can push to the OpenClaw sandbox.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$HOME/hackathon/venv/bin/python"
PIDFILE="$DIR/console.pid"; LOGFILE="$DIR/console.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Vigil Console already running (pid $(cat "$PIDFILE")) on http://localhost:5001"; exit 0
fi
if ss -ltn 2>/dev/null | grep -q ':5001 '; then
  echo "Port 5001 is already in use by another process. Run stop_console.sh or free the port."; exit 1
fi

CMD="cd '$DIR' && exec '$PY' -u app.py"
if getent group docker >/dev/null && ! id -nG | grep -qw docker; then
  nohup setsid sg docker -c "$CMD" >>"$LOGFILE" 2>&1 < /dev/null &
else
  nohup setsid bash -c "$CMD" >>"$LOGFILE" 2>&1 < /dev/null &
fi
echo $! > "$PIDFILE"

for _ in $(seq 1 40); do
  if curl -fs -o /dev/null http://localhost:5001/api/health; then
    echo "Vigil Console running on http://localhost:5001 (pid $(cat "$PIDFILE"), log: $LOGFILE)"; exit 0
  fi
  sleep 0.25
done
echo "Vigil Console did not come up - last log lines:"; tail -n 20 "$LOGFILE"; exit 1
