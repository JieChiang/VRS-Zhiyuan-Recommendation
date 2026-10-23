@echo off
setlocal
chcp 65001 >nul
title VRS 桌面版
cd /d "%~dp0"
set "VRS_PYTHON=D:\Software\Miniconda3\envs\VRS\python.exe"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
if not exist "%VRS_PYTHON%" (
  echo [错误] 找不到指定 VRS 环境：%VRS_PYTHON%
  goto failed
)
echo 正在启动 VRS 桌面版，默认端口8765...
echo 已运行的 VRS 服务将被复用；关闭最后一个桌面窗口会停止本次新建的服务。
"%VRS_PYTHON%" -B -s desktop_app.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo [启动失败] 请查看上方错误。需要依赖时，请仅在指定 VRS 环境安装 requirements.txt。
pause
exit /b 1
