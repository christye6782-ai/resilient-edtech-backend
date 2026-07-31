@echo off
REM ResilientEdTech launcher (Windows)
REM Activates the conda env and starts the uvicorn server.

CALL conda activate resilient-edtech 2>NUL
echo.
echo  ResilientEdTech is starting...
echo  Tip: make sure Ollama is running and 'ollama pull llama3.2:3b' has been done
echo       (the app still works in rule-based mode without it).
echo  Open http://127.0.0.1:5000 in your browser.
echo.
uvicorn app.main:app --host 127.0.0.1 --port 5000 --reload
