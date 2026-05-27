#!/bin/bash
# 拼多多 AI 客服助手 - 一键启动（可放在桌面，自动定位项目目录）

set -e

echo -ne "\033]0;拼多多 AI 客服助手\007"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

resolve_project_dir() {
    if [ -n "${AGENT_CUSTOMER_HOME:-}" ] && [ -f "${AGENT_CUSTOMER_HOME}/app.py" ]; then
        printf '%s\n' "$AGENT_CUSTOMER_HOME"
        return 0
    fi
    if [ -f "$SCRIPT_DIR/app.py" ]; then
        printf '%s\n' "$SCRIPT_DIR"
        return 0
    fi
    local d
    for d in \
        "$HOME/Downloads/Customer-Agent-main" \
        "$HOME/Documents/Customer-Agent-main" \
        "$HOME/Customer-Agent-main" \
        "$HOME/Downloads/Customer-Agent" \
        ; do
        if [ -f "$d/app.py" ]; then
            printf '%s\n' "$d"
            return 0
        fi
    done
    return 1
}

PROJECT_DIR="$(resolve_project_dir)" || {
    echo "❌ 找不到项目目录（需要包含 app.py）"
    echo ""
    echo "请任选一种方式："
    echo "  1. 把本脚本放到项目根目录（与 app.py 同级）"
    echo "  2. 设置环境变量：export AGENT_CUSTOMER_HOME=/你的项目路径"
    echo "  3. 将项目放在 ~/Downloads/Customer-Agent-main"
    echo ""
    read -r -p "按回车键退出..."
    exit 1
}

cd "$PROJECT_DIR" || exit 1
mkdir -p logs

echo "╔════════════════════════════════════════╗"
echo "║   拼多多 AI 客服助手                   ║"
echo "║   正在启动...                          ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "📂 项目目录: $PROJECT_DIR"
echo ""

if ! command -v python3 &>/dev/null; then
    echo "❌ 未找到 python3，请安装 Python 3.11+"
    read -r -p "按回车键退出..."
    exit 1
fi

PYTHON="python3"
if [ -d ".venv/bin" ]; then
    echo "✅ 使用虚拟环境 .venv"
    # shellcheck source=/dev/null
    source .venv/bin/activate
    PYTHON="python"
elif command -v uv &>/dev/null; then
    echo "⚠️  未找到 .venv，正在执行 uv sync..."
    uv sync
    # shellcheck source=/dev/null
    source .venv/bin/activate
    PYTHON="python"
else
    echo "⚠️  未找到 .venv，使用系统 Python（建议先执行: cd \"$PROJECT_DIR\" && uv sync）"
fi

if ! "$PYTHON" -c "import PyQt6" 2>/dev/null; then
    echo "❌ 缺少 PyQt6"
    if command -v uv &>/dev/null; then
        echo "📦 正在 uv sync 安装依赖..."
        uv sync
        # shellcheck source=/dev/null
        source .venv/bin/activate
        PYTHON="python"
    else
        echo "请安装 uv 后在该目录执行: uv sync"
        read -r -p "按回车键退出..."
        exit 1
    fi
fi

echo ""
echo "🚀 启动应用..."
echo "─────────────────────────────────────"
export PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" app.py
