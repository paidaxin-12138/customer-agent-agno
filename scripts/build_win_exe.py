#!/usr/bin/env python3
"""Windows onedir 发布包：PyInstaller + icon.ico。"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "scripts" / "agent_customer.spec"
ICO = ROOT / "icon" / "icon.ico"
PNG = ROOT / "icon" / "app_icon.png"
DIST_DIR = ROOT / "dist" / "AgentCustomer"
DIST_EXE = DIST_DIR / "AgentCustomer.exe"


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd or ROOT)


def ensure_windows() -> None:
    if platform.system() != "Windows":
        raise SystemExit(
            f"此脚本仅支持 Windows，当前: {platform.system()}\n"
            "请在 Windows 上运行: uv run python scripts/build_win_exe.py"
        )


def ensure_uv() -> None:
    if shutil.which("uv") is None:
        raise SystemExit("未检测到 uv，请先安装: pip install uv")


def ensure_icon() -> None:
    if ICO.is_file():
        print(f"使用图标: {ICO}")
        return
    if PNG.is_file():
        print(f"警告: 缺少 {ICO}，将使用 {PNG}（建议在 Windows 上用 icon.ico）")
        return
    raise SystemExit(f"缺少图标: {ICO} 或 {PNG}")


def sync_deps() -> None:
    run(["uv", "sync", "--group", "dev", "--extra", "build"])


def clean() -> None:
    for name in ("build", "dist"):
        p = ROOT / name
        if p.exists():
            shutil.rmtree(p)
            print(f"已删除 {p}/")


def build(*, debug: bool = False) -> Path:
    pyinstaller = ROOT / ".venv" / "Scripts" / "pyinstaller.exe"
    if not pyinstaller.is_file():
        pyinstaller = Path("pyinstaller")

    cmd = [
        str(pyinstaller),
        "--noconfirm",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build"),
        str(SPEC),
    ]
    if debug:
        cmd.insert(-1, "--log-level=DEBUG")
    run(cmd)

    if not DIST_EXE.is_file():
        raise SystemExit(f"构建失败，未找到 {DIST_EXE}")

    readme = ROOT / "dist" / "README-win.txt"
    readme.write_text(
        """拼多多 AI 客服 — Windows 发布包

1. 进入 dist\\AgentCustomer 目录，双击 AgentCustomer.exe
2. 用户数据目录：%LOCALAPPDATA%\\AgentCustomer\\
   （config.json、数据库、日志、Playwright 浏览器缓存）
3. 首次使用拼多多登录需网络；Playwright 浏览器请在本机执行一次：
   uv run playwright install chromium
4. 若 SmartScreen 拦截，请添加信任或使用代码签名后的安装包

技术支持：见项目 README.md
""",
        encoding="utf-8",
    )
    example = ROOT / "config.json.example"
    if example.is_file():
        shutil.copy2(example, ROOT / "dist" / "config.json.example")

    return DIST_EXE


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 Windows AgentCustomer 发布目录")
    parser.add_argument("--clean", action="store_true", help="构建前清理 build/dist")
    parser.add_argument("--debug", action="store_true", help="PyInstaller 调试日志")
    parser.add_argument("--check-only", action="store_true", help="仅检查依赖")
    args = parser.parse_args()

    ensure_windows()
    ensure_uv()

    required = [ROOT / "app.py", SPEC]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit("缺少文件:\n" + "\n".join(missing))

    if args.check_only:
        print("依赖检查通过，可执行: uv run python scripts/build_win_exe.py")
        return

    if args.clean:
        clean()

    sync_deps()
    ensure_icon()
    exe_path = build(debug=args.debug)

    size_mb = sum(f.stat().st_size for f in DIST_DIR.rglob("*") if f.is_file()) / (
        1024 * 1024
    )
    print()
    print("=" * 60)
    print("构建完成")
    print("=" * 60)
    print(f"可执行文件: {exe_path}")
    print(f"发布目录:   {DIST_DIR}")
    print(f"体积约:     {size_mb:.0f} MB")
    print(f"说明:       {ROOT / 'dist' / 'README-win.txt'}")


if __name__ == "__main__":
    main()
