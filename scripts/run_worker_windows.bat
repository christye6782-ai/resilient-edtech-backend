@echo off
REM Run the worker in a persistent loop on Windows. Use NSSM or Task Scheduler to install as a service.
:loop
python "%~dp0worker.py"
echo Worker exited; restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto loop
