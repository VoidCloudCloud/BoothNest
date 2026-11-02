@echo off
setlocal
cd /d "%~dp0"
title BoothNest
echo BoothNest
echo Open http://127.0.0.1:4317 after the server starts.
echo Keep this window open. Press Ctrl+C to stop.
echo.
if defined BOOTH_NEST_NODE (
  "%BOOTH_NEST_NODE%" server.mjs
) else (
  node server.mjs
)
if errorlevel 1 pause
