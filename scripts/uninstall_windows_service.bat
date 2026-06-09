@echo off
REM Copyright (c) 2026 paidaxin-12138
REM Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
REM https://creativecommons.org/licenses/by-nc/4.0/
setlocal

set SERVICE_NAME=CustomerAgent

where nssm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] 未找到 nssm.exe
  exit /b 1
)

echo 停止并删除服务 %SERVICE_NAME% ...
nssm stop %SERVICE_NAME%
nssm remove %SERVICE_NAME% confirm
echo 完成。
endlocal
