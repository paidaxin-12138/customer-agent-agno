from typing import List
from pathlib import Path
from agno.knowledge.document.base import Document
try:
    from agno.knowledge.reader.base import Reader
except Exception:
    Reader = object
import importlib
try:
    openpyxl = importlib.import_module("openpyxl")
except Exception:
    openpyxl = None
try:
    xlrd = importlib.import_module("xlrd")
except Exception:
    xlrd = None

class ExcelReader(Reader):
    def __init__(self, chunk_size: int = 4000):
        self.chunk_size = chunk_size

    def read(self, obj, name: str | None = None) -> List[Document]:
        p = Path(obj) if not isinstance(obj, Path) else obj
        ext = p.suffix.lower()
        if ext == ".xlsx":
            if openpyxl is None:
                raise ImportError("缺少 openpyxl 依赖，无法读取 .xlsx 文件")
            return self._read_xlsx(p, name)
        if ext == ".xls":
            if xlrd is None:
                raise ImportError("缺少 xlrd 依赖，无法读取 .xls 文件")
            return self._read_xls(p, name)
        raise ValueError("不支持的 Excel 文件类型")

    async def async_read(self, obj, name: str | None = None) -> List[Document]:
        return self.read(obj, name)

    def _read_xlsx(self, path: Path, name: str | None) -> List[Document]:
        wb = openpyxl.load_workbook(filename=str(path), data_only=True, read_only=True)
        docs: List[Document] = []
        for ws in wb.worksheets:
            lines = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                lines.append(",".join(cells))
            text = "\n".join(lines)
            base_name = name or f"{path.stem}:{ws.title}"
            docs.extend(self._split_to_documents(text, base_name, {"sheet_name": ws.title, "source_ext": ".xlsx"}))
        return docs

    def _read_xls(self, path: Path, name: str | None) -> List[Document]:
        wb = xlrd.open_workbook(filename=str(path))
        docs: List[Document] = []
        for si in range(wb.nsheets):
            sh = wb.sheet_by_index(si)
            lines = []
            for r in range(sh.nrows):
                cells = [str(sh.cell_value(r, c)) if sh.cell_value(r, c) is not None else "" for c in range(sh.ncols)]
                lines.append(",".join(cells))
            text = "\n".join(lines)
            base_name = name or f"{path.stem}:{sh.name}"
            docs.extend(self._split_to_documents(text, base_name, {"sheet_name": sh.name, "source_ext": ".xls"}))
        return docs

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
