@echo off
rem ============================================================================
rem  CaptionShot - build the Windows installer.  Double-click, or run in cmd.
rem  Result: dist\CaptionShot-Setup-1.1.4.exe
rem  Needs: Python 3.10-3.15 (python.org). Inno Setup is installed for you if missing.
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo [1/5] Finding Python...
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo   Python not found. Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^), then run this again.
  goto :fail
)
%PY% -c "import sys; v=sys.version_info; print('  Python %%d.%%d' %% v[:2]); sys.exit(0 if (3,10)<=v[:2]<=(3,15) else 1)" || (
  echo   This Python version is not supported. Use Python 3.10 to 3.15.
  goto :fail
)

echo.
echo [2/5] Creating a clean build environment (.venv-build)...
if not exist ".venv-build\Scripts\python.exe" %PY% -m venv .venv-build || goto :fail
set "VPY=%CD%\.venv-build\Scripts\python.exe"
"%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip || goto :fail
"%VPY%" -m pip install --disable-pip-version-check -q -r packaging\requirements-build.txt || goto :fail

echo.
echo [3/5] Packaging the app with PyInstaller...
if exist "dist\CaptionShot" rmdir /s /q "dist\CaptionShot"
"%VPY%" -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\CaptionShot.spec || goto :fail
if not exist "dist\CaptionShot\CaptionShot.exe" (
  echo   PyInstaller finished but CaptionShot.exe is missing.
  goto :fail
)

echo.
echo [4/5] Self-test of the packaged app...
del "%TEMP%\captionshot_selftest.txt" >nul 2>&1
start "" /wait "dist\CaptionShot\CaptionShot.exe" --selftest
set "RC=%ERRORLEVEL%"
if not exist "%TEMP%\captionshot_selftest.txt" (
  echo   The app did not start ^(no self-test report^). Exit code %RC%.
  goto :fail
)
type "%TEMP%\captionshot_selftest.txt"
echo.
if not "%RC%"=="0" goto :fail

echo.
echo [5/5] Building the installer with Inno Setup...
set "ISCC="
for %%P in ("%ProgramFiles%\Inno Setup 7\ISCC.exe" "%LocalAppData%\Programs\Inno Setup 7\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe") do (
  if not defined ISCC if exist %%P set "ISCC=%%~P"
)
if not defined ISCC for /f "delims=" %%I in ('where iscc 2^>nul') do if not defined ISCC set "ISCC=%%I"
if not defined ISCC (
  echo   Inno Setup not found - installing it with winget...
  winget install --id JRSoftware.InnoSetup.7 -e -s winget --silent --accept-package-agreements --accept-source-agreements
  for %%P in ("%ProgramFiles%\Inno Setup 7\ISCC.exe" "%LocalAppData%\Programs\Inno Setup 7\ISCC.exe") do (
    if not defined ISCC if exist %%P set "ISCC=%%~P"
  )
)
if not defined ISCC (
  echo   Could not find Inno Setup. Install it from https://jrsoftware.org/isdl.php and run this again.
  echo   ^(The app itself is ready in dist\CaptionShot\ - you can already run CaptionShot.exe from there.^)
  goto :fail
)
"%ISCC%" /Q "packaging\CaptionShot.iss" || goto :fail
if not exist "dist\CaptionShot-Setup-1.1.4.exe" (
  echo   Inno Setup finished but the installer is missing.
  goto :fail
)

echo.
echo  DONE:  dist\CaptionShot-Setup-1.1.4.exe
echo  Double-click it to install. Windows may say "Windows protected your PC" because the
echo  installer is not code-signed: click "More info" ^> "Run anyway".
rem CI is set on GitHub Actions: nobody is there to press a key or look at Explorer.
if not defined CI explorer /select,"dist\CaptionShot-Setup-1.1.4.exe"
echo.
if not defined CI pause
exit /b 0

:fail
echo.
echo  BUILD FAILED - see the message above. Nothing was installed.
echo.
if not defined CI pause
exit /b 1
