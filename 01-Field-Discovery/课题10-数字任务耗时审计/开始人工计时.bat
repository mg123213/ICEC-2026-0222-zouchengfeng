@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================================
echo   ICEC 2026 - 课题10 人工耗时实测
echo ================================================================
echo.
echo   接下来依次处理 10 个样本 S01 ~ S10。
echo   每个样本按屏幕上的 SOP 做完（清空行 / 改单位 / 算 4 个指标），
echo   做完立刻按 Enter，脚本自动记下这一个的真实耗时。
echo.
echo   全部做完约 12-15 分钟。中途输入 q 可提前结束（按均值外推）。
echo   计时过程中不要接电话、不要切窗口做别的事。
echo.
echo ================================================================
pause
"C:\Users\29099\AppData\Local\Programs\Python\Python311\python.exe" manual_timer.py
echo.
echo 完成。结果已写入 out\人工耗时.csv
echo 把这个窗口截图留作证据，然后告诉 AI 继续。
pause
