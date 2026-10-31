@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo 首次运行需要安装环境，正在检查...
  call install.bat
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8; import fastapi,uvicorn,docx,PIL,qrcode,multipart" >nul 2>nul
if errorlevel 1 (
  echo 运行环境不完整，正在重新检查安装...
  call install.bat
  if errorlevel 1 goto failed
)
if not exist "frontend\dist\index.html" (
  echo 页面文件缺失。请按 INSTALL.md 构建页面后重试。
  goto failed
)
".venv\Scripts\python.exe" scripts\run.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo 启动失败，请查看 INSTALL.md 或 logs\system.log。
pause
exit /b 1
