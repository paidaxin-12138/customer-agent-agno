@echo off
setlocal EnableDelayedExpansion

REM Customer-Agent Windows 服务注册（NSSM）
REM 需已安装 NSSM: https://nssm.cc/download
REM 并以管理员身份运行本脚本。

set SERVICE_NAME=CustomerAgent
set PROJECT_ROOT=%~dp0..
cd /d "%PROJECT_ROOT%"

where nssm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] 未找到 nssm.exe，请先安装 NSSM 并加入 PATH。
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] 未找到 .venv\Scripts\python.exe，请先在项目根目录执行: uv sync
  exit /b 1
)

set PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe
set APP_SCRIPT=%PROJECT_ROOT%\app.py

echo 注册服务 %SERVICE_NAME% ...
nssm install %SERVICE_NAME% "%PYTHON_EXE%" "%APP_SCRIPT%"
nssm set %SERVICE_NAME% AppDirectory "%PROJECT_ROOT%"
nssm set %SERVICE_NAME% DisplayName "Customer-Agent AI 客服"
nssm set %SERVICE_NAME% Description "拼多多 AI 客服桌面应用（需已登录图形会话）"
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START
nssm set %SERVICE_NAME% AppStdout "%PROJECT_ROOT%\logs\service-out.log"
nssm set %SERVICE_NAME% AppStderr "%PROJECT_ROOT%\logs\service-error.log"

echo.
echo 请通过「系统 - 高级系统设置 - 环境变量」或 NSSM GUI 配置:
echo   AGENT_CREDENTIAL_KEY, LLM_API_KEY 等。
echo.
echo 启动服务: nssm start %SERVICE_NAME%
echo 查看状态: nssm status %SERVICE_NAME%
endlocal
