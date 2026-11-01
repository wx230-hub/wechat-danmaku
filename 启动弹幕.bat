@echo off
rem 微信消息弹幕 —— 静默启动（无控制台窗口）
chcp 65001 >nul
cd /d "%~dp0"

set "PYW="
for %%p in (pythonw.exe) do if not "%%~$PATH:p"=="" set "PYW=%%~$PATH:p"
if not defined PYW if exist "E:\Programs\Python\Python314\pythonw.exe" set "PYW=E:\Programs\Python\Python314\pythonw.exe"

if not defined PYW (
  echo 未找到 pythonw.exe，请先把 Python 加入 PATH，或修改本脚本里的路径。
  pause
  exit /b 1
)

start "" "%PYW%" "%~dp0main.py"
exit /b 0
