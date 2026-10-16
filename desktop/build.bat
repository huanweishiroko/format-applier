@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem ===========================================================================
rem  Word 格式助手 · 打包脚本（Phase 4）
rem  用法：在本机终端手动执行（不要在受限的 DSH 会话里跑）
rem      cd E:\dsh_plugins\word-format-applier\desktop
rem      .\build.bat
rem  产物：desktop\dist\Word格式助手\Word格式助手.exe
rem  注意：本文件必须是 CRLF 换行、无 BOM，否则 cmd 解析 if(...) 块会出错。
rem        中文路径一律交给 Python 的 shutil 处理，cmd 的 move/rmdir 不碰中文。
rem ===========================================================================

set "PROJ=E:\dsh_plugins\word-format-applier"
set "PYTHON=%PROJ%\.venv\Scripts\python.exe"
set "TEMP=%PROJ%\.venv\pip-tmp"
set "TMP=%TEMP%"
cd /d "%~dp0"
if not exist "%TEMP%" mkdir "%TEMP%" >nul 2>&1

if not exist "%PYTHON%" (
    echo [错误] 找不到解释器：%PYTHON%
    echo        请确认 .venv 存在，或改 build.bat 里的 PYTHON 变量。
    pause
    exit /b 1
)

echo [0/4] 环境
echo        PYTHON = %PYTHON%
echo        TEMP   = %TEMP%
echo.

echo [1/4] 检查 PyInstaller...
"%PYTHON%" -m PyInstaller --version
if errorlevel 1 (
    echo        未安装，正在用 pip 安装（走 %TEMP%，首次会拉几 MB bootloader）...
    "%PYTHON%" -m pip install pyinstaller
    if errorlevel 1 (
        echo [错误] pyinstaller 安装失败。把上面的原始输出发给排障方，或手动执行：
        echo        "%PYTHON%" -m pip install pyinstaller
        pause
        exit /b 1
    )
    "%PYTHON%" -m PyInstaller --version
)
echo.

echo [2/4] 打包中（onedir + windowed，首次约 1-3 分钟）...
"%PYTHON%" -m PyInstaller --noconfirm --clean WordFormatAssistant.spec
if errorlevel 1 (
    echo [错误] 打包失败。把上面的原始输出（尤其最后 30 行）发给排障方。
    echo        常见原因：pyinstaller 版本过老 / _internal 被占用 / 杀毒拦截写入。
    pause
    exit /b 1
)
echo.

echo [3/4] 收尾：预设归位、放 .env 模板、清理 build\ ...
if not exist "dist\Word格式助手" (
    echo [错误] 没有生成 dist\Word格式助手，打包可能被中断。
    pause
    exit /b 1
)
rem spec 已把预设指向 exe 同级；这里再兜一次底：万一仍落在 _internal\presets，
rem 就搬出来。整段交给 Python —— cmd 的 move 遇到中文路径会报
rem "'...\presets' is not recognized as an internal or external command"。
"%PYTHON%" -c "import shutil,os;p=r'dist\Word格式助手';s=os.path.join(p,'_internal','presets');d=os.path.join(p,'presets');shutil.rmtree(d,True) if os.path.isdir(d) else None;shutil.move(s,d) if os.path.isdir(s) else None" >nul 2>&1
if errorlevel 1 (
    echo [警告] 预设归位脚本没跑起来（见上一行的报错）。
)
if not exist "dist\Word格式助手\presets\格式要求1.txt" (
    if not exist "dist\Word格式助手\_internal\presets\格式要求1.txt" (
        echo [警告] 两处都没有内置预设 —— 首页下拉框会是空的。
    ) else (
        echo [警告] 内置预设仍在 _internal\presets\（程序自己能兜住，但 cli 自检可能为 0）。
    )
)
rem .env.example 必须放在 **exe 同级** —— 新版的 .env 就在那儿读（旧版 _internal 仍兼容）。
if exist ".env.example" copy /Y ".env.example" "dist\Word格式助手\.env.example" >nul
if exist "build" rmdir /S /Q "build" >nul 2>&1
echo.

echo [4/4] 完成
if not exist "dist\Word格式助手\Word格式助手.exe" (
    echo [错误] 没看到 Word格式助手.exe。
    pause
    exit /b 1
)
for %%f in ("dist\Word格式助手\Word格式助手.exe") do echo        exe：%%~ff  ^(%%~zf 字节^)
echo        目录：%~dp0dist\Word格式助手\
echo.
echo 自检（不开界面；count 应为 4）：
echo        dist\Word格式助手\Word格式助手.exe --wfa-cli --list-presets-json
echo.
echo 下一步：
echo   1^) 双击 dist\Word格式助手\Word格式助手.exe
echo   2^) 需要 AI 解析格式要求时：把 exe 同级的 .env.example 改名 .env（同目录）并填 key
echo   3^) 换内置预设：在 exe 同级放 presets\（优先级高于 _internal\presets\）
echo   4^) 用户数据（config.json / presets / usage.json）在 %%APPDATA%%\WordFormatAssistant\
echo.
pause
endlocal