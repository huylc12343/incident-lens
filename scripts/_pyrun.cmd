@echo off
REM Cross-platform Python launcher for AI log hooks (Windows cmd.exe).
REM Prefer a working project virtualenv, then working PATH interpreters.
REM A stale venv or Windows Store alias must not make hooks silently fail.

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
  if not errorlevel 1 (
    ".venv\Scripts\python.exe" %*
    exit /b %ERRORLEVEL%
  )
)

where python >nul 2>nul
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
  if not errorlevel 1 (
    python %*
    exit /b %ERRORLEVEL%
  )
)

where python3 >nul 2>nul
if not errorlevel 1 (
  python3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
  if not errorlevel 1 (
    python3 %*
    exit /b %ERRORLEVEL%
  )
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
  if not errorlevel 1 (
    py -3 %*
    exit /b %ERRORLEVEL%
  )
)

REM Hooks must never block the AI tool if Python is unavailable.
exit /b 0
