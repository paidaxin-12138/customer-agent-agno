"""敏感路径权限（Unix）。"""
import os
import sys
from pathlib import Path

import pytest

from utils.private_paths import ensure_private_dir, ensure_private_file


@pytest.mark.skipif(sys.platform == "win32", reason="chmod 语义在 Windows 上不一致")
def test_ensure_private_file_sets_600(tmp_path: Path):
    f = tmp_path / "secret.db"
    f.write_text("data", encoding="utf-8")
    ensure_private_file(f)
    mode = f.stat().st_mode & 0o777
    assert mode == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="chmod 语义在 Windows 上不一致")
def test_ensure_private_dir_sets_700(tmp_path: Path):
    d = tmp_path / "data"
    ensure_private_dir(d)
    assert d.is_dir()
    mode = d.stat().st_mode & 0o777
    assert mode == 0o700
