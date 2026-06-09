# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
在独立子进程中执行商品同步（含 PaddleOCR），避免与 PyQt 主进程争用 GIL 导致界面卡死。
"""

from __future__ import annotations

import json
import sys
from typing import Optional

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, pyqtSignal

from utils.logger_loguru import get_logger
from utils.runtime_path import get_base_path

logger = get_logger(__name__)

_PROGRESS_MARKER = "@@GOODS_SYNC_PROGRESS@@"


class GoodsSyncSubprocessRunner(QObject):
    """通过 QProcess 调用 scripts.sync_goods_to_kb，主界面保持可响应。"""

    progress = pyqtSignal(str, int, int)
    list_ready = pyqtSignal(int)
    item_synced = pyqtSignal(str, int, int, str)
    catalog_cleared = pyqtSignal()
    success = pyqtSignal(int)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: Optional[QProcess] = None
        self._stdout_buf = ""
        self._handled_done = False

    def is_running(self) -> bool:
        return (
            self._proc is not None
            and self._proc.state() != QProcess.ProcessState.NotRunning
        )

    def start(
        self,
        shop_id: str = "",
        user_id: str = "",
        *,
        use_ocr: bool,
        sync_all: bool = False,
    ) -> None:
        if self.is_running():
            return

        self._handled_done = False
        self._stdout_buf = ""
        self._proc = QProcess(self.parent())

        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        self._proc.setProcessEnvironment(env)
        self._proc.setWorkingDirectory(str(get_base_path()))
        self._proc.setProgram(sys.executable)

        args = ["-m", "scripts.sync_goods_to_kb", "--emit-progress"]
        if sync_all:
            args.append("--all")
        else:
            args.extend([f"--shop-id={shop_id}", f"--user-id={user_id}"])
        if not use_ocr:
            args.append("--no-ocr")
        self._proc.setArguments(args)

        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_process_error)
        self._proc.start()
        logger.info("商品同步子进程已启动")

    def cancel(self) -> None:
        if self._proc and self.is_running():
            self._proc.kill()
            logger.info("已请求终止商品同步子进程")

    def _on_stdout(self) -> None:
        if not self._proc:
            return
        chunk = bytes(self._proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._stdout_buf += chunk
        while "\n" in self._stdout_buf:
            line, self._stdout_buf = self._stdout_buf.split("\n", 1)
            self._parse_line(line.strip())

    def _on_stderr(self) -> None:
        if not self._proc:
            return
        err = bytes(self._proc.readAllStandardError()).decode("utf-8", errors="replace")
        if err.strip():
            logger.debug(f"商品同步 stderr: {err.strip()[:500]}")

    def _parse_line(self, line: str) -> None:
        if not line or _PROGRESS_MARKER not in line:
            return
        payload_raw = line.split(_PROGRESS_MARKER, 1)[1]
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            return

        if payload.get("done"):
            self._handled_done = True
            if payload.get("cancelled"):
                count = int(payload.get("synced_count") or 0)
                if count > 0:
                    self.success.emit(count)
                else:
                    self.failed.emit("已取消同步")
                return
            if payload.get("success") and int(payload.get("synced_count") or 0) > 0:
                self.success.emit(int(payload["synced_count"]))
            else:
                err = payload.get("error") or "未同步任何商品"
                if payload.get("empty_catalog"):
                    err = "店铺暂无在售商品，未写入知识库"
                err_text = str(err)
                if "会话已过期" in err_text and "用户管理" not in err_text:
                    err_text = (
                        "拼多多商家后台登录已过期。请先在「用户管理」重新登录该店铺，"
                        "或确认左侧自动回复已显示连接成功后再同步。"
                    )
                self.failed.emit(err_text)
            return

        if payload.get("catalog_cleared"):
            self.catalog_cleared.emit()

        if payload.get("list_ready"):
            total = int(payload.get("total_planned") or payload.get("total") or 0)
            if total > 0:
                self.list_ready.emit(total)

        if payload.get("item_synced"):
            self.item_synced.emit(
                str(payload.get("title") or payload.get("msg") or ""),
                int(payload.get("cur") or 0),
                int(payload.get("total") or 0),
                str(payload.get("goods_id") or ""),
            )

        self.progress.emit(
            str(payload.get("msg") or ""),
            int(payload.get("cur") or 0),
            int(payload.get("total") or 0),
        )

    def _parse_partial_synced_count(self) -> int:
        """进程被 kill 时从 stdout 进度行恢复已同步数量。"""
        last = 0
        for line in self._stdout_buf.splitlines():
            if _PROGRESS_MARKER not in line:
                continue
            try:
                payload = json.loads(line.split(_PROGRESS_MARKER, 1)[1])
            except json.JSONDecodeError:
                continue
            if payload.get("item_synced"):
                last = max(last, int(payload.get("cur") or 0))
        return last

    def _on_finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        if not self._handled_done:
            partial = self._parse_partial_synced_count()
            if partial > 0:
                self._handled_done = True
                logger.warning(
                    "商品同步子进程异常退出(code=%s)，保留已同步 %s 个",
                    exit_code,
                    partial,
                )
                self.success.emit(partial)
            elif exit_code == 0:
                self.failed.emit("同步进程异常结束，未收到完成信号")
            else:
                hint = "（可能因取消或内存不足被终止）" if exit_code == 9 else ""
                tail = self._stdout_buf.strip()[-200:]
                self.failed.emit(
                    f"同步进程退出码 {exit_code}{hint}"
                    + (f"\n{tail}" if tail else "")
                )
        self._proc = None
        self.finished.emit()

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.failed.emit("无法启动同步进程，请检查 Python 环境与项目路径")
