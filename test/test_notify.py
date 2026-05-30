"""桌面通知工具测试（不依赖真实通知服务）。"""
from unittest.mock import patch

from utils.notify import send_desktop_notification


def test_send_desktop_notification_swallows_errors():
    with patch("utils.notify.platform.system", return_value="Linux"):
        with patch("utils.notify.shutil.which", return_value=None):
            assert send_desktop_notification("t", "m") is False


def test_send_desktop_notification_linux_notify_send():
    with patch("utils.notify.platform.system", return_value="Linux"):
        with patch("utils.notify.shutil.which", return_value="/usr/bin/notify-send"):
            with patch("utils.notify.subprocess.run") as run:
                run.return_value.returncode = 0
                assert send_desktop_notification("标题", "内容") is True
