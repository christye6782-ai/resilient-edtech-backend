#!/usr/bin/env bash
set -e
if command -v conda >/dev/null 2>&1; then
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate resilient-edtech || true
fi

echo "Starting ResilientEdTech API and worker..."

ohai=0
trap 'kill $api_pid $wrk_pid 2>/dev/null || true' EXIT

uvicorn app.main:app --host 127.0.0.1 --port 5000 --reload &
api_pid=$!
python scripts/worker.py &
wrk_pid=$!

echo "API PID=$api_pid"
echo "Worker PID=$wrk_pid"
echo "Open http://127.0.0.1:5000 in your browser."

wait $api_pid $wrk_pid
