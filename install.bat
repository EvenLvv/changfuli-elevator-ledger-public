@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python 启动器 py。请先安装 Python 3.12 64位版本。
  exit /b 1
)
py -3.12 -c "import struct; assert struct.calcsize('P') == 8"
if errorlevel 1 (
  echo 请安装 Python 3.12 64位版本，并勾选 Python Launcher。
  exit /b 1
)
py -3.12 -m venv .venv
if errorlevel 1 exit /b 1
if exist "wheelhouse\*.whl" (
  ".venv\Scripts\python.exe" -m pip install --no-index --find-links wheelhouse -r requirements.txt -c requirements.lock.txt
) else (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt -c requirements.lock.txt
)
if errorlevel 1 exit /b 1
if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo 页面文件缺失。请安装 Node.js，或复制已构建的 frontend\dist 目录。
    exit /b 1
  )
  pushd frontend
  call npm ci
  if errorlevel 1 (popd & exit /b 1)
  call npm run build
  if errorlevel 1 (popd & exit /b 1)
  popd
)
echo 安装完成。
exit /b 0
