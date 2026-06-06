#!/usr/bin/env python3
"""macOS .app 打包：PyInstaller + icns 图标。"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "scripts" / "agent_customer_mac.spec"
ICNS = ROOT / "icon" / "app_icon.icns"
PNG = ROOT / "icon" / "app_icon.png"
APP_OUT = ROOT / "dist" / "AgentCustomer.app"


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=cwd or ROOT)


def ensure_macos() -> None:
    if platform.system() != "Darwin":
        raise SystemExit(f"此脚本仅支持 macOS，当前: {platform.system()}")


def ensure_uv() -> None:
    if shutil.which("uv") is None:
        raise SystemExit("未检测到 uv，请先安装: pip install uv")


def ensure_icns() -> None:
    if ICNS.is_file():
        print(f"使用图标: {ICNS}")
        return
    if not PNG.is_file():
        raise SystemExit(f"缺少图标: {PNG}")
    print("生成 app_icon.icns ...")
    run([sys.executable, str(ROOT / "create_app_icon.py")])
    if not ICNS.is_file():
        raise SystemExit("ICNS 生成失败，请确认已安装 iconutil（Xcode CLT）")


def _fix_macos_bundle_icon(app_path: Path) -> None:
    """macOS 要求 CFBundleIconFile 不含 .icns 扩展名，否则 Dock 可能显示默认文档图标。"""
    plist = app_path / "Contents" / "Info.plist"
    if not plist.is_file():
        return
    try:
        import plistlib

        with plist.open("rb") as f:
            data = plistlib.load(f)
        if data.get("CFBundleIconFile") != "app_icon":
            data["CFBundleIconFile"] = "app_icon"
            with plist.open("wb") as f:
                plistlib.dump(data, f)
            print(f"已修正 {plist} 中的 CFBundleIconFile")
    except Exception as exc:
        print(f"警告: 无法修正 Info.plist 图标键 ({exc})")


def sync_deps() -> None:
    run(["uv", "sync", "--group", "dev", "--extra", "build"])


def clean() -> None:
    for name in ("build", "dist"):
        p = ROOT / name
        if p.exists():
            shutil.rmtree(p)
            print(f"已删除 {p}/")


def build(*, debug: bool = False) -> Path:
    pyinstaller = ROOT / ".venv" / "bin" / "pyinstaller"
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

    if not APP_OUT.is_dir():
        raise SystemExit(f"构建失败，未找到 {APP_OUT}")

    _fix_macos_bundle_icon(APP_OUT)

    readme = APP_OUT.parent / "README-mac.txt"
    readme.write_text(
        """拼多多 AI 客服 — macOS 应用包

1. 将 AgentCustomer.app 拖到「应用程序」文件夹
2. 首次打开：若提示「无法验证开发者」，请 系统设置 → 隐私与安全性 → 仍要打开
3. 用户数据目录：~/Library/Application Support/AgentCustomer/
   （config.json、数据库、日志、Playwright 浏览器缓存）
4. 首次使用拼多多登录需网络；Playwright 浏览器请在本机执行一次：
   cd /path/to/source && uv run playwright install chromium
   或在终端对打包前的开发环境安装后，将 ~/.cache/ms-playwright 复制到
   ~/Library/Application Support/AgentCustomer/.browsers （可选）

技术支持：见项目 README.md
""",
        encoding="utf-8",
    )
    example = ROOT / "config.json.example"
    if example.is_file():
        shutil.copy2(example, APP_OUT.parent / "config.json.example")

    return APP_OUT


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 macOS AgentCustomer.app")
    parser.add_argument("--clean", action="store_true", help="构建前清理 build/dist")
    parser.add_argument("--debug", action="store_true", help="PyInstaller 调试日志")
    parser.add_argument("--check-only", action="store_true", help="仅检查依赖")
    args = parser.parse_args()

    ensure_macos()
    ensure_uv()

    required = [ROOT / "app.py", SPEC, PNG]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit("缺少文件:\n" + "\n".join(missing))

    if args.check_only:
        print("依赖检查通过，可执行: uv run python scripts/build_mac_app.py")
        return

    if args.clean:
        clean()

    sync_deps()
    ensure_icns()
    app_path = build(debug=args.debug)

    size_mb = sum(f.stat().st_size for f in app_path.rglob("*") if f.is_file()) / (
        1024 * 1024
    )
    print()
    print("=" * 60)
    print("构建完成")
    print("=" * 60)
    print(f"应用包: {app_path}")
    print(f"体积约: {size_mb:.0f} MB")
    print(f"说明:   {app_path.parent / 'README-mac.txt'}")
    print()
    print("本地试跑: open dist/AgentCustomer.app")


if __name__ == "__main__":
    main()
