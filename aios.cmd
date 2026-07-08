@echo off
REM The AI OS launcher (cmd.exe). Usage: aios <command> [args...]
setlocal
set "HERE=%~dp0"
where py >nul 2>nul && (py -3 "%HERE%aios.py" %* & exit /b %ERRORLEVEL%)
where python >nul 2>nul && (python "%HERE%aios.py" %* & exit /b %ERRORLEVEL%)
echo Python 3 not found. Install it from https://www.python.org/downloads/ and retry.
exit /b 1
