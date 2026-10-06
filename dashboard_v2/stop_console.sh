#!/usr/bin/env bash
# Stop Thirty console (and any demo replay it started).
DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$DIR/console.pid"

if [ ! -f "$PIDFILE" ]; then echo "Thirty console is not running (no pid file)."; exit 0; fi
PID="$(cat "$PIDFILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill -TERM -- "-$PID" 2>/dev/null || kill -TERM "$PID"   # whole process group (setsid): sg -> python
  for _ in $(seq 1 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.25; done
  kill -0 "$PID" 2>/dev/null && kill -KILL -- "-$PID" 2>/dev/null
  echo "Thirty console stopped (pid $PID)."
else
  echo "Thirty console was not running (stale pid $PID)."
fi
rm -f "$PIDFILE"
