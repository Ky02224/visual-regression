@echo off
cd /d "C:\Users\HP\Desktop\FYP(VISUAL)"
call .venv\Scripts\activate.bat
set LENS_ADMIN_PASSWORD=TempAdmin123!
set LENS_DEVELOPER_PASSWORD=TempDev123!
python -m visual_regression.cli serve-dashboard --port 8130
pause
