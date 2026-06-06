"""实时聊天 QSS。"""
from __future__ import annotations

from ui.chat import tokens as T
from ui.chat.tree_icons import CHEVRON_DOWN_URI, CHEVRON_RIGHT_URI
from ui import apple_ui_tokens as UI


def build_live_chat_stylesheet() -> str:
    return f"""
            #LiveChatRoot {{
                background-color: {T.C_BG};
                border: none;
            }}
            #LiveChatSessionPanel {{
                background-color: {T.C_PANEL};
                border: none;
            }}
            #LiveChatSessionHeader {{
                background-color: {T.C_PANEL};
                border-bottom: 1px solid {T.C_BORDER};
            }}
            #LiveChatSessionSearch {{
                background-color: {T.C_CARD};
                border: 1px solid {T.C_BORDER};
                border-radius: 12px;
                padding: 8px 12px;
                color: {T.C_TEXT};
                font-size: 14px;
            }}
            #LiveChatSessionSearch:focus {{
                border: 1px solid {UI.ACCENT_SURFACE_BORDER};
            }}
            #LiveChatAccountList {{
                background-color: {T.C_BG};
                color: {T.C_MUTED};
                border: none;
                border-right: 1px solid {T.C_BORDER};
                font-size: 13px;
                outline: none;
            }}
            #LiveChatAccountList::item {{
                padding: 12px 14px;
                border-radius: 10px;
                margin: 2px 6px;
                color: {T.C_MUTED};
            }}
            #LiveChatAccountList::item:hover {{
                background-color: {T.C_CARD};
                color: {T.C_TEXT};
            }}
            #LiveChatAccountList::item:selected {{
                background-color: {T.C_CARD};
                color: {UI.ACCENT};
                font-weight: 500;
            }}
            QTreeWidget#LiveChatSessionTree {{
                background-color: {T.C_PANEL};
                color: {T.C_TEXT};
                border: none;
                outline: none;
                font-size: 13px;
            }}
            QTreeWidget#LiveChatSessionTree::item {{
                padding: 10px 12px 10px 4px;
                border-radius: 10px;
                min-height: 44px;
                margin: 2px 4px;
            }}
            QTreeWidget#LiveChatSessionTree::item:hover {{
                background-color: rgba(255, 255, 255, 0.04);
            }}
            QTreeWidget#LiveChatSessionTree::item:selected {{
                background-color: {UI.ACCENT_SURFACE};
                color: {T.C_TEXT};
                border: none;
            }}
            QTreeWidget#LiveChatSessionTree::branch {{
                background: transparent;
            }}
            QTreeWidget#LiveChatSessionTree::branch:has-children:!has-siblings:closed,
            QTreeWidget#LiveChatSessionTree::branch:closed:has-children:has-siblings {{
                border-image: none;
                image: {CHEVRON_RIGHT_URI};
                width: 24px;
                height: 24px;
                margin: 4px 2px;
            }}
            QTreeWidget#LiveChatSessionTree::branch:open:has-children:has-siblings,
            QTreeWidget#LiveChatSessionTree::branch:open:has-children:!has-siblings {{
                border-image: none;
                image: {CHEVRON_DOWN_URI};
                width: 24px;
                height: 24px;
                margin: 4px 2px;
            }}
            QTreeWidget#LiveChatSessionTree::branch:has-siblings:!adjoins-item,
            QTreeWidget#LiveChatSessionTree::branch:has-siblings:adjoins-item {{
                border-image: none;
                image: none;
            }}

            #LiveChatRightPanel {{
                background-color: {T.C_CHAT_BG};
                border: none;
            }}
            #LiveChatTopBar {{
                background-color: {T.C_CHAT_BG};
                border-bottom: 1px solid {T.C_BORDER};
            }}
            #LiveChatAvatar {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #FF6B6B, stop:1 #FF8E8E);
                color: #FFFFFF;
                font-weight: bold;
                font-size: 16px;
                border-radius: 12px;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                max-height: 40px;
            }}
            #LiveChatNameLabel {{
                color: {T.C_TEXT};
                font-size: 16px;
                font-weight: 600;
            }}
            #LiveChatSubLabel {{
                font-size: 12px;
            }}
            QListWidget#LiveChatMsgList {{
                background-color: {T.C_CHAT_BG};
                border: none;
                outline: none;
                padding: 8px 0;
            }}
            ScrollArea#LiveChatMsgScroll {{
                background-color: {T.C_CHAT_BG};
                border: none;
            }}
            QWidget#LiveChatMsgList {{
                background-color: {T.C_CHAT_BG};
            }}
            #LiveChatInputArea {{
                background-color: {T.C_CHAT_BG};
                border: none;
            }}
            #LiveChatInput {{
                background-color: {T.C_CHROME_BG};
                border: 1px solid {T.C_CHROME_BORDER};
                border-radius: 12px;
                padding: 12px;
                color: {T.C_TEXT};
                font-size: 14px;
                outline: none;
            }}
            #LiveChatInput:focus {{
                border: 1px solid {UI.ACCENT_SURFACE_BORDER};
            }}
            #LiveChatTopBar PushButton#LiveChatModeButton,
            #LiveChatTopBar PushButton#LiveChatCloseButton {{
                min-height: 36px;
                max-height: 36px;
                padding: 6px 12px;
                font-size: 13px;
            }}
            QScrollArea#LiveChatTopBarActionsScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#LiveChatTopBarActionsScroll > QWidget {{
                background: transparent;
                border: none;
            }}
            QScrollArea#LiveChatQuickScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#LiveChatQuickScroll > QWidget {{
                background: transparent;
                border: none;
            }}
            #LiveChatQuickStrip {{
                background: transparent;
                border: none;
            }}
            #LiveChatToolsStrip PushButton {{
                background-color: {T.C_CHROME_BG};
                color: {T.C_TEXT};
                border: 1px solid {T.C_CHROME_BORDER};
                border-radius: 8px;
                font-size: 12px;
                padding: 4px 8px;
            }}
            #LiveChatToolsStrip PushButton:hover {{
                background-color: {T.C_CHROME_HOVER};
                border-color: {UI.ACCENT_SURFACE_BORDER};
            }}
            #LiveChatToolsStrip PushButton:pressed {{
                background-color: {T.C_CHROME_PRESSED};
            }}
            #LiveChatToolsStrip PushButton:disabled {{
                background-color: {T.C_PANEL};
                color: {T.C_DIM};
                border-color: {T.C_BORDER};
            }}
            #LiveChatQuickStrip PushButton {{
                background-color: {T.C_CHROME_BG};
                color: {T.C_TEXT};
                border: 1px solid {T.C_CHROME_BORDER};
                border-radius: 14px;
                font-size: 12px;
                padding: 6px 14px;
            }}
            #LiveChatQuickStrip PushButton:hover {{
                background-color: {T.C_CHROME_HOVER};
                border-color: {UI.ACCENT_SURFACE_BORDER};
                color: {T.C_TEXT};
            }}
            #LiveChatQuickStrip PushButton:pressed {{
                background-color: {T.C_CHROME_PRESSED};
            }}
            """


def _chat_toolbar_btn_base() -> str:
    return (
        "min-height: 36px; max-height: 36px; padding: 6px 12px; font-size: 13px;"
        " border-radius: 10px;"
    )


def _mode_btn_icon_pad() -> str:
    """qfluentwidgets PushButton 自绘图标在 x≈12；为文字留出左侧空间避免叠字。"""
    return "padding-left: 34px; padding-right: 10px;"


def mode_toggle_button_styles() -> tuple[str, str]:
    base = _chat_toolbar_btn_base()
    pad = _mode_btn_icon_pad()
    outline = (
        f"#LiveChatModeButton {{ {base} {pad}"
        f" border: 1px solid {T.C_BORDER};"
        f" background: transparent; color: {T.C_MUTED}; }}"
        f"#LiveChatModeButton:hover {{ background-color: {T.C_CARD}; color: {T.C_TEXT}; }}"
        f"#LiveChatModeButton:disabled {{ color: {T.C_DIM}; border-color: {T.C_BORDER}; }}"
    )
    primary = (
        f"#LiveChatModeButton {{ {base} {pad}"
        f" border: 1px solid {UI.ACCENT_SURFACE_BORDER};"
        f" background: {UI.ACCENT_SURFACE}; color: {UI.ACCENT}; font-weight: 600; }}"
        f"#LiveChatModeButton:hover {{ background: {UI.ACCENT_SURFACE_HOVER}; border-color: {UI.ACCENT};"
        f" color: {UI.ACCENT_HOVER}; }}"
        f"#LiveChatModeButton:disabled {{ background: {T.C_BORDER}; color: {T.C_DIM};"
        f" border-color: {T.C_BORDER}; }}"
    )
    return outline, primary


def action_button_outline_style() -> str:
    base = _chat_toolbar_btn_base()
    pad = _mode_btn_icon_pad()
    return (
        f"#LiveChatCloseButton {{ {base} {pad}"
        f" border: 1px solid {T.C_BORDER};"
        f" background: transparent; color: {T.C_MUTED}; }}"
        f"#LiveChatCloseButton:hover {{ background-color: {T.C_CARD}; color: {T.C_TEXT}; }}"
    )


def loading_subtitle_style() -> str:
    return f"color: {T.C_LOADING}; font-size: 12px; font-weight: 500;"
