@echo off
setlocal
chcp 65001 >nul
title VRS 志愿推荐系统
cd /d "%~dp0"

set "VRS_CONDA_ENV=D:\Software\Miniconda3\envs\VRS"
set "VRS_PYTHON=%VRS_CONDA_ENV%\python.exe"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"

if not exist "%VRS_PYTHON%" (
  echo [错误] 找不到指定环境：%VRS_PYTHON%
  goto failed
)
if not exist "D:\Software\Miniconda3\Scripts\activate.bat" (
  echo [错误] 找不到 Miniconda 激活脚本。
  goto failed
)

echo 正在激活 VRS 虚拟环境...
call "D:\Software\Miniconda3\Scripts\activate.bat" "%VRS_CONDA_ENV%"
if errorlevel 1 goto failed

echo 正在检查项目依赖...
"%VRS_PYTHON%" -B -c "import fastapi, uvicorn, jinja2, pydantic, dotenv, yaml, multipart, pytesseract, PIL, numpy, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo 依赖不完整，正在按 requirements.txt 安装，请稍候...
  "%VRS_PYTHON%" -m pip install --no-input -r requirements.txt
  if errorlevel 1 goto failed
)

echo 使用环境：%VRS_CONDA_ENV%
echo 项目地址：http://127.0.0.1:8765
echo 请确保 Neo4j 已启动，具体配置状态可在项目页面查看。
echo 关闭此窗口或按 Ctrl+C 可停止本次启动的 Web 服务。
echo.
"%VRS_PYTHON%" -B scripts\start_local.py --port 8765 %*
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo [启动失败] 请查看上方错误信息；本机私有配置仍由项目正常加载。
pause
exit /b 1
