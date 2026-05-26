from typing import List
from pathlib import Path
from agno.knowledge.document.base import Document
try:
    from agno.knowledge.reader.base import Reader
except Exception:
    Reader = object
import shutil
import subprocess
import importlib
import tempfile
import os

from utils.logger_loguru import get_logger

_doc_log = get_logger("doc_reader")

try:
    textract = importlib.import_module("textract")
except Exception:
    textract = None

class DocReader(Reader):
    def __init__(self, chunk_size: int = 4000):
        self.chunk_size = chunk_size

    def read(self, obj, name: str | None = None) -> List[Document]:
        p = Path(obj) if not isinstance(obj, Path) else obj
        if p.suffix.lower() != ".doc":
            raise ValueError("不支持的 Doc 文件类型")
        text = self._extract_text(p)
        base_name = name or p.stem
        return self._split_to_documents(text, base_name, {"source_ext": ".doc"})

    async def async_read(self, obj, name: str | None = None) -> List[Document]:
        return self.read(obj, name)

    def _extract_text(self, path: Path) -> str:
        if textract is not None:
            try:
                data = textract.process(str(path))
                return data.decode("utf-8", errors="ignore")
            except Exception as e:
                _doc_log.debug("textract 解析 .doc 失败: {}", e)
        aw = shutil.which("antiword")
        if aw:
            proc = subprocess.run([aw, "-f", str(path)], capture_output=True)
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout.decode("utf-8", errors="ignore")
        cd = shutil.which("catdoc")
        if cd:
            proc = subprocess.run([cd, str(path)], capture_output=True)
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout.decode("utf-8", errors="ignore")
        pd = shutil.which("pandoc")
        if pd:
            proc = subprocess.run([pd, "-s", str(path), "-t", "plain"], capture_output=True)
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout.decode("utf-8", errors="ignore")
        soffice = shutil.which("soffice")
        if soffice:
            with tempfile.TemporaryDirectory() as tmpdir:
                subprocess.run([soffice, "--headless", "--convert-to", "txt:Text", "--outdir", tmpdir, str(path)], capture_output=True)
                out_txt = os.path.join(tmpdir, f"{path.stem}.txt")
                if os.path.exists(out_txt):
                    with open(out_txt, "rb") as f:
                        return f.read().decode("utf-8", errors="ignore")
        raise ImportError("缺少 textract/antiword/catdoc/pandoc/libreoffice，无法读取 .doc 文件")

    def _split_to_documents(self, text: str, base_name: str, meta: dict) -> List[Document]:
        if not text:
            return [Document(content="", name=base_name, meta_data=meta)]
        docs: List[Document] = []
        start = 0
        idx = 1
        size = self.chunk_size
        while start < len(text):
            chunk = text[start:start+size]
            docs.append(Document(content=chunk, name=f"{base_name}#{idx}", meta_data=meta | {"chunk_index": idx}))
            start += size
            idx += 1
        return docs
