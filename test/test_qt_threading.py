# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""主线程调度桥单元测试。"""
from utils.qt_threading import init_main_thread_bridge, run_on_main_thread


def test_run_on_main_thread_inline(qapp):
    init_main_thread_bridge()
    seen = []

    run_on_main_thread(lambda: seen.append(1))
    qapp.processEvents()
    assert seen == [1]
