@echo off
REM Launch both the ResilientEdTech server and worker on Windows.
SETLOCAL
CALL conda activate resilient-edtech 2>NUL
echo.
echo Starting ResilientEdTech API...
start "ResilientEdTech API" cmd /k "CALL conda activate resilient-edtech 2>NUL && uvicorn app.main:app --host 127.0.0.1 --port 5000 --reload"
echo Starting ResilientEdTech worker...
start "ResilientEdTech Worker" cmd /k "CALL conda activate resilient-edtech 2>NUL && python "%~dp0scripts\worker.py""
echo.
echo Two windows were started: API and worker.
echo Open http://127.0.0.1:5000 in your browser.
ENDLOCAL
