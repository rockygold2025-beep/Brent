@echo off
cd /d "%~dp0"
if not exist venv (
  echo Creating virtual environment...
  python -m venv venv
  if errorlevel 1 (
    echo Failed. Try: py -3 -m venv venv
    pause
    exit /b 1
  )
)
call venv\Scripts\activate
pip install -r requirements.txt -q
if not exist .env copy .env.example .env
echo.
echo Starting app...
python app.py
pause
