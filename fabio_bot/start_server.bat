@echo off
title Fabio Bot Server
cd /d "%~dp0"

where python >nul 2>&1 && goto run
where py >nul 2>&1 && set PY=py -3 && goto run
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe" && goto run
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python311\python.exe" && goto run
if exist "C:\Python312\python.exe" set PY="C:\Python312\python.exe" && goto run
if exist "C:\Python311\python.exe" set PY="C:\Python311\python.exe" && goto run
echo Python not found. Install from https://www.python.org/downloads/ and check "Add Python to PATH".
pause
exit /b 1

:run
if not defined PY set PY=python
echo Starting server...
%PY% -m uvicorn api_server:app --host 0.0.0.0 --port 8000
pause
