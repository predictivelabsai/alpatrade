#!/usr/bin/env bash
# Agent box (tertiary): keep ONE live BTD event scheduler process alive. No scheduling here —
# this only restarts scripts/live_btd_scheduler.py if it exits (the box has no systemd/cron).
# Install as /home/box/alpatrade-runner/loop.sh (started by ensure.sh via setsid nohup, under flock).
# Pause: touch $R/STOP (scheduler stopped, keep-alive waits)   Disable: ./stop.sh (creates DISABLED)
R=/home/box/alpatrade-runner
LOG="$R/logs/loop.log"
exec 9>"$R/loop.lock"
flock -n 9 || { echo "$(date '+%F %T') keep-alive already running" >> "$LOG"; exit 0; }
echo $$ > "$R/loop.pid"
echo "$(date '+%F %T') keep-alive started pid $$" >> "$LOG"
while true; do
  [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 10485760 ] && mv -f "$LOG" "$LOG.1"
  if [ -f "$R/STOP" ]; then sleep 30; continue; fi
  echo "$(date '+%F %T') scheduler start" >> "$LOG"
  ( set -a; . "$R/runner.env"; set +a; cd "$R/repo" && exec "$R/venv/bin/python" scripts/live_btd_scheduler.py --live ) >> "$LOG" 2>&1
  echo "$(date '+%F %T') scheduler exited rc=$? -> restart in 15 s" >> "$LOG"
  sleep 15
done
