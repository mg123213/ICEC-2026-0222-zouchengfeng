@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  ICEC 2026 - Task 10 - Manual Timing (3 samples)
echo ================================================
echo.
echo  Work on samples\S01.csv, S02.csv, S03.csv one by one.
echo  Press Enter right after finishing each one.
echo.
pause
"C:\Users\29099\AppData\Local\Programs\Python\Python311\python.exe" manual_timer.py --files S01.csv S02.csv S03.csv
echo.
pause
