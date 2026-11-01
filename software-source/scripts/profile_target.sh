#!/usr/bin/env bash
set -euo pipefail

api_url="${AUTOSYNAPSE_API:-http://127.0.0.1:8000/api/dashboard}"
pid="$(pgrep -f 'uvicorn backend.main:app' | head -n 1 || true)"

echo "Target: $(uname -a)"
echo "Memory:"
grep -E 'MemTotal|MemAvailable' /proc/meminfo || true
if [[ -n "$pid" && -r "/proc/$pid/status" ]]; then
  echo "AUTOSYNAPSE process ($pid):"
  grep -E 'VmRSS|VmHWM|Threads' "/proc/$pid/status" || true
else
  echo "AUTOSYNAPSE PID not found; start it before profiling."
fi

echo "Dashboard request latency (10 samples):"
for n in $(seq 1 10); do
  curl --silent --show-error --output /dev/null --write-out "sample=$n seconds=%{time_total}\n" "$api_url"
done
