"""主线程调度桥单元测试。"""
from utils.qt_threading import init_main_thread_bridge, run_on_main_thread


def test_run_on_main_thread_inline(qapp):
    init_main_thread_bridge()
    seen = []

    run_on_main_thread(lambda: seen.append(1))
    qapp.processEvents()
    assert seen == [1]
