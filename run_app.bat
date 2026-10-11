@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
)

python -m streamlit run app.py

if errorlevel 1 (
    echo.
    echo Streamlit failed to start. Please check the error messages above.
    pause
)
