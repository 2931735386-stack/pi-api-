@echo off
chcp 65001 >nul
echo ============================================
echo   pi-api-switcher 打包脚本
echo ============================================
echo.

REM 检查 PyInstaller
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [1/3] 安装 PyInstaller ...
    pip install pyinstaller
)

echo [2/3] 生成图标（若不存在）...
python -c "from pathlib import Path; import sys; sys.path.insert(0,'.'); from app import generate_icon_ico; generate_icon_ico(Path('icon.ico')); print('icon.ico ready')"

echo [3/3] 打包为 exe ...
python -m PyInstaller --clean --noconfirm pi-api-switcher.spec
if errorlevel 1 (
    echo 打包失败，请查看上方错误。
    exit /b 1
)

echo.
echo 打包完成！输出在 dist\pi-api-switcher.exe
pause
