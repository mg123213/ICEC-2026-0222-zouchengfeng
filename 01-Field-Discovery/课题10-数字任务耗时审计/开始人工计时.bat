@echo off
cd /d "%~dp0"
REM  ICEC 2026 / topic 10 : manual stopwatch track (second timing source)
REM  Chinese instructions are printed by manual_timer.py, not by this file.
echo.
echo  ===  ICEC 2026 / topic 10  -  manual stopwatch track  ===
echo.
echo  Starting manual_timer.py ...
echo  Read the Chinese instructions in the window; input q to stop early.
echo.
pause
"C://Users//29099//AppData//Local//Programs//Python//Python311//python.exe" manual_timer.py
echo.
echo  Done. Output file name is printed above.
echo  Next:  python compare.py
echo.
pause
