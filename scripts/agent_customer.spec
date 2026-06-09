# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Windows onedir 发布包。用法: pyinstaller scripts/agent_customer.spec"""

import sys
from pathlib import Path

block_cipher = None

if "__file__" in globals():
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
else:
    PROJECT_ROOT = Path.cwd()

ICON_FILE = str(PROJECT_ROOT / "icon" / "icon.ico")

from PyInstaller.utils.hooks import collect_all, collect_submodules

try:
    _qfw_datas, _qfw_binaries, _qfw_hidden = collect_all("qfluentwidgets")
except Exception:
    _qfw_datas, _qfw_binaries, _qfw_hidden = [], [], []

_handler_hidden = collect_submodules("Message.handlers")
try:
    _channel_hidden = collect_submodules("Channel.pinduoduo")
except Exception:
    _channel_hidden = []

_HANDLER_FALLBACK = [
    "Message.handlers.address_change_handler",
    "Message.handlers.order_logistics_handler",
    "Message.handlers.image_video_handler",
    "Message.handlers.after_sales_apply_handler",
    "Message.handlers.buyer_emotion_handler",
    "Message.handlers.fallback_reply",
    "Message.handlers.channel_send",
    "Message.handlers.ai_reply_watchdog",
    "Message.handlers.preprocessor",
    "Message.handler_chain_factory",
    "Message.core.handlers",
]

_datas = [
    (str(PROJECT_ROOT / "icon" / "app_icon.png"), "icon"),
    (str(PROJECT_ROOT / "icon" / "icon.ico"), "icon"),
    (str(PROJECT_ROOT / "ui" / "dark_theme.qss"), "ui"),
    (str(PROJECT_ROOT / "config.json.example"), "."),
] + _qfw_datas

a = Analysis(
    [str(PROJECT_ROOT / "app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=_qfw_binaries,
    datas=_datas,
    hiddenimports=[
        "config_schema",
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.sip",
        "qfluentwidgets",
        "agno",
        "agno.agent",
        "agno.models.openai",
        "agno.knowledge.embedder.openai",
        "agno.db.sqlite",
        "openai",
        "tiktoken",
        "tiktoken_ext.openai_public",
        "sqlalchemy",
        "sqlalchemy.dialects.sqlite",
        "lancedb",
        "loguru",
        "websockets",
        "aiohttp",
        "playwright",
        "playwright.async_api",
        "pandas",
        "numpy",
        "openpyxl",
        "pypdf",
        "PIL",
        "pydantic",
        "httpx",
        "httpcore",
        "certifi",
        "charset_normalizer",
        "requests",
        "dotenv",
        "cryptography",
        "alembic",
        "config",
        "core.di_container",
        "core.connection_status",
        "core.channel_facade",
        "core.app_shutdown",
        "core.production_services",
        "database.db_manager",
        "database.models",
        "database.ops_repository",
        "bridge.context",
        "bridge.reply",
        "Message.core.queue",
        "Message.core.consumer",
        "Message.handler_chain_factory",
        "Message.handlers.ai_handler",
        "Message.handlers.keyword_handler",
        "Agent.bot",
        "Agent.CustomerAgent.agent",
        "Agent.CustomerAgent.agent_knowledge",
        "Channel.pinduoduo.pdd_channel",
        "Channel.pinduoduo.pdd_login",
        "Channel.pinduoduo.pdd_message",
        "Channel.pinduoduo.ws_account",
        "Channel.pinduoduo.ws_inbound_pipeline",
        "Channel.pinduoduo.ws_lifecycle",
        "ui.main_ui",
        "ui.ops_dashboard.ops_dashboard_ui",
        "ui.theme",
        "ui.dark_theme_loader",
        "utils.logger_loguru",
        "utils.runtime_path",
        "utils.best_effort",
    ] + _qfw_hidden + _HANDLER_FALLBACK + _handler_hidden + _channel_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentCustomer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_FILE,
    version="",
    description="拼多多 AI 客服助手",
    product_name="AgentCustomer",
    product_version="1.1.0",
    company_name="",
    legal_copyright="",
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    a.zipfiles,
    strip=False,
    upx=False,
    name="AgentCustomer",
)
