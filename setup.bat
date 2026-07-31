@echo off
REM ResilientEdTech - one-time setup (Windows)
REM Run once:  setup.bat      Then start the app with:  run.bat
setlocal

echo === ResilientEdTech setup ===

REM 1. Python environment ----------------------------------------------------
where conda >NUL 2>&1
if %ERRORLEVEL%==0 (
  if exist environment.yml (
    echo -^> Conda found. Creating/updating the 'resilient-edtech' env...
    call conda env create -f environment.yml 2>NUL || call conda env update -f environment.yml
    call conda activate resilient-edtech
    goto deps_done
  )
)
echo -^> Using a local virtual environment (.venv)
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
:deps_done

REM 2. Ollama + local model (optional but recommended) -----------------------
where ollama >NUL 2>&1
if %ERRORLEVEL%==0 (
  echo -^> Ollama found. Pulling the local model ^(one-time, needs internet^)...
  ollama pull llama3.2:3b
) else (
  echo -^> Ollama NOT found ^(optional^). Install from https://ollama.com then run:
  echo      ollama pull llama3.2:3b
  echo    Without it, the app automatically uses the offline rule-based engine.
)

REM 3. Tesseract note --------------------------------------------------------
echo -^> Optional: install Tesseract OCR to read photographed plans:
echo      https://github.com/UB-Mannheim/tesseract/wiki
echo    If installed off-PATH, set TESSERACT_CMD in your .env file.

echo.
echo === Setup complete. Start the app with:  run.bat ===
echo     Then open http://127.0.0.1:5000
endlocal
