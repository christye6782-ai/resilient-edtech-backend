#!/usr/bin/env bash
# ResilientEdTech launcher (macOS/Linux)
set -e
# Activate conda env if available
if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate resilient-edtech || true
fi
echo
echo " ResilientEdTech is starting..."
echo " Tip: ensure Ollama is running and 'ollama pull llama3.2:3b' has been done"
echo "      (the app still works in rule-based mode without it)."
echo " Open http://127.0.0.1:5000 in your browser."
echo
exec uvicorn app.main:app --host 127.0.0.1 --port 5000 --reload
