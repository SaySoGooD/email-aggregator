@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === email-aggregator: Windows installer build ===

rem --- 1. uv -----------------------------------------------------------
where uv >nul 2>nul
if errorlevel 1 (
    echo [uv] not found, installing via winget...
    winget install --id astral-sh.uv -e --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [uv] winget failed, falling back to official installer...
        powershell -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    )
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>nul
    if errorlevel 1 (
        echo [uv] still not found after install. Open a new terminal and re-run this script.
        exit /b 1
    )
) else (
    echo [uv] found
)

rem --- 2. project dependencies ------------------------------------------
echo [uv sync] installing project dependencies...
uv sync
if errorlevel 1 (
    echo [uv sync] failed.
    exit /b 1
)

rem --- 3. Inno Setup (ISCC.exe) ------------------------------------------
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
    echo [Inno Setup] not found, installing via winget...
    winget install --id JRSoftware.InnoSetup -e --silent --accept-package-agreements --accept-source-agreements
    if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    if "%ISCC%"=="" (
        echo [Inno Setup] still not found after install. Open a new terminal and re-run this script.
        exit /b 1
    )
) else (
    echo [Inno Setup] found: %ISCC%
)

rem --- 4. PyInstaller build ------------------------------------------------
echo [pyinstaller] building executable...
uv run pyinstaller --noconfirm --clean All-in-one-Email.spec
if errorlevel 1 (
    echo [pyinstaller] build failed.
    exit /b 1
)

rem --- 5. Inno Setup installer -----------------------------------------
echo [ISCC] packaging installer...
"%ISCC%" installer\All-in-one-Email.iss
if errorlevel 1 (
    echo [ISCC] packaging failed.
    exit /b 1
)

rem --- 6. copy the installer into the project root ----------------------
for %%F in (installer\Output\All-in-one-Email-Setup-*.exe) do copy /y "%%F" ".\" >nul

rem --- 7. clean up PyInstaller intermediates -----------------------------
rem dist\ and build\ are only scaffolding ISCC already consumed; the
rem Setup.exe is self-contained, so there's nothing left worth keeping them for.
echo [cleanup] removing dist\ and build\...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

echo.
echo === Done ===
echo Installer: %~dp0All-in-one-Email-Setup-*.exe
endlocal
