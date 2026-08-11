@echo off
REM Cross-platform Python launcher for AI log hooks (Windows cmd.exe).
REM Prefer the repository virtual environment, then py -3.

if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe %*
  exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python %*
  exit /b %ERRORLEVEL%
)

where python3 >nul 2>nul
if %ERRORLEVEL%==0 (
  python3 %*
  exit /b %ERRORLEVEL%
)

echo [ai-log] Python runtime not found; logs were not processed. 1>&2
exit /b 1
