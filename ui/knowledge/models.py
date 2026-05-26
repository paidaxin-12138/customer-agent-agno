"""
知识库数据模型和转换工具

提供统一的数据结构和转换逻辑。
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import json
import os


@dataclass
class SimpleDocument:
    """
    简化文档对象，统一不同来源的文档数据结构

    支持从 LanceDB 行数据或 Agno 文档对象创建。
    """
    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    data: str = ""
    description: str = ""
    name: str = ""
    embedding: Optional[list] = None

    @classmethod
    def from_lancedb_row(cls, row_data: dict, idx: int) -> "SimpleDocument":
        """
        从LanceDB行数据创建文档对象

        Args:
            row_data: LanceDB 行数据字典
            idx: 行索引

        Returns:
            SimpleDocument 实例
        """
        doc_id = str(row_data.get('id', f'doc_{idx}'))
        raw_payload = row_data.get('payload', '')
        metadata = {}
        content = ""

        # 解析 payload 字段（JSON格式）
        if raw_payload:
            try:
                payload_data = json.loads(raw_payload)
                content = payload_data.get('content', '')

                # 提取元数据
                if 'meta_data' in payload_data:
                    metadata.update(payload_data['meta_data'])
                if 'name' in payload_data:
                    metadata['filename'] = payload_data['name']
            except (json.JSONDecodeError, TypeError):
                content = str(raw_payload)

        # 保存其他元数据
        for col in row_data.keys():
            if col not in ['id', 'content', 'text', 'payload']:
                metadata[col] = row_data.get(col)

        description = content[:100] + "..." if len(content) > 100 else content

        return cls(
            id=doc_id,
            content=content,
            data=content,
            description=description,
            metadata=metadata
        )

    @classmethod
    def from_kb_dict(cls, d: dict[str, Any], idx: int = 0) -> "SimpleDocument":
        """
        从 NailLampKnowledgeManager 等返回的原始文档字典构建 UI 文档。
        保留 import_format / display_payload 等以便按导入形式展示。
        """
        doc_id = str(d.get("id") or f"doc_{idx}")
        content = str(d.get("content") or "")
        description = content[:100] + "..." if len(content) > 100 else content
        md: dict[str, Any] = {
            "title": d.get("title") or "",
            "filename": d.get("filename") or "",
            "source": d.get("source") or "",
            "platform_shop_id": d.get("platform_shop_id") or "",
            "inherit_key": d.get("inherit_key") or "",
            "allow_child_override": bool(d.get("allow_child_override", False)),
        }
        if d.get("import_format"):
            md["import_format"] = str(d.get("import_format"))
        dp = d.get("display_payload")
        if dp is not None and str(dp).strip():
            md["display_payload"] = str(dp)
        return cls(
            id=doc_id,
            content=content,
            data=content,
            description=description,
            metadata=md,
        )

    @classmethod
    def from_agno_doc(cls, doc: Any) -> "SimpleDocument":
        """
        从Agno文档对象创建

        Args:
            doc: Agno 框架的文档对象

        Returns:
            SimpleDocument 实例
        """
        # 获取内容
        if hasattr(doc, 'data') and doc.data:
            content = str(doc.data)
        elif hasattr(doc, 'content') and doc.content:
            content = str(doc.content)
        elif hasattr(doc, 'description') and doc.description:
            content = str(doc.description)
        else:
            content = "无内容"

        # 获取 ID
        doc_id = str(getattr(doc, 'id', '')) if hasattr(doc, 'id') else ''

        # 获取元数据
        metadata = getattr(doc, 'metadata', {}) if hasattr(doc, 'metadata') else {}

        # 获取嵌入向量
        embedding = getattr(doc, 'embedding', None) if hasattr(doc, 'embedding') else None

        return cls(
            id=doc_id,
            content=content,
            data=content,
            description=content[:100] + "..." if len(content) > 100 else content,
            metadata=metadata,
            embedding=embedding
        )


def infer_import_format(doc: SimpleDocument) -> str:
    """
    推断文档应以何种视图展示（与导入形式一致）。
    优先使用存储的 import_format；否则按文件名后缀推断。
    """
    raw = (doc.metadata or {}).get("import_format")
    if raw is not None and str(raw).strip():
        return str(raw).strip().lower()
    fn = str((doc.metadata or {}).get("filename") or "").lower()
    ext = os.path.splitext(fn)[1]
    mapping = {
        ".md": "markdown",
        ".markdown": "markdown",
        ".csv": "csv",
        ".json": "json",
        ".xlsx": "excel",
        ".xls": "excel",
        ".pdf": "pdf",
        ".txt": "text",
        ".text": "text",
    }
    if ext in mapping:
        return mapping[ext]
    if (doc.metadata or {}).get("source") == "manual_input":
        return "manual"
    return "text"


def parse_display_payload(doc: SimpleDocument) -> Optional[dict]:
    """解析 metadata 中的 display_payload（JSON 字符串）。"""
    raw = (doc.metadata or {}).get("display_payload")
    if raw is None or not str(raw).strip():
        return None
    try:
        out = json.loads(str(raw))
        return out if isinstance(out, dict) else None
    except Exception:
        return None


def format_preview_line(doc: SimpleDocument, max_len: int = 150) -> str:
    """知识卡片上的内容预览一行。"""
    mode = infer_import_format(doc)
    pl = parse_display_payload(doc)
    if mode in ("excel", "csv") and pl and pl.get("sheets"):
        sheets = pl["sheets"]
        s0 = sheets[0]
        nr = int(s0.get("total_rows", len(s0.get("rows") or [])))
        nc = len(s0.get("columns") or [])
        tag = "Excel" if mode == "excel" else "CSV"
        return f"{tag} · {len(sheets)} 个工作表 · 约 {nr} 行 × {nc} 列"
    if mode == "json":
        return "JSON · 结构化内容"
    content = (doc.content or "").strip()
    if not content:
        return "（无内容）"
    if len(content) > max_len:
        return content[:max_len] + "..."
    return content


class DocumentTitleExtractor:
    """
    统一的文档标题提取器

    按优先级从多个来源提取文档标题。
    """

    # 标题字段优先级列表
    TITLE_KEYS = ['title', 'name', 'filename', 'file_name', 'question', 'subject', '标题']

    # 默认标题长度限制
    DEFAULT_TITLE_LENGTH = 20
    DESCRIPTION_TITLE_LENGTH = 30

    @classmethod
    def extract(cls, doc: SimpleDocument) -> str:
        """
        提取文档标题，按优先级尝试多个来源

        优先级：
        1. metadata 中的 title/name/filename 等字段
        2. name 属性
        3. description 属性前30字
        4. content 首行前20字
        5. ID 前8位

        Args:
            doc: SimpleDocument 实例

        Returns:
            提取的标题字符串
        """
        # 1. 尝试从 metadata 中获取标题
        if doc.metadata:
            for key in cls.TITLE_KEYS:
                if key in doc.metadata:
                    return str(doc.metadata[key])

        # 2. 尝试从 name 属性获取
        if doc.name:
            return doc.name

        # 3. 尝试从 description 属性获取
        if doc.description:
            desc = str(doc.description)
            if len(desc) > cls.DESCRIPTION_TITLE_LENGTH:
                return desc[:cls.DESCRIPTION_TITLE_LENGTH] + "..."
            return desc

        # 4. 如果有内容，使用内容的前20个字
        if doc.content:
            content = doc.content.strip()
            if content:
                # 尝试找到第一个换行符之前的内容
                lines = content.split('\n')
                first_line = lines[0].strip()
                if len(first_line) > cls.DEFAULT_TITLE_LENGTH:
                    return first_line[:cls.DEFAULT_TITLE_LENGTH] + "..."

                # 如果第一行太短或看起来不合适，使用内容的前20个字
                if len(first_line) < 5 or first_line.startswith('###'):
                    if len(content) > cls.DEFAULT_TITLE_LENGTH:
                        return content[:cls.DEFAULT_TITLE_LENGTH] + "..."
                return first_line

        # 5. 使用 ID 作为最后备选
        if doc.id:
            return f"文档 {doc.id[:8]}"

        return "无标题"


class MarkdownConverter:
    """
    Markdown转HTML转换器

    支持常见的 Markdown 语法转换。
    """

    @staticmethod
    def to_html(markdown_text: str) -> str:
        """
        将Markdown文本转换为HTML

        支持的语法：
        - 标题（# ## ###）
        - 粗体（**text**）
        - 斜体（*text*）
        - 行内代码（`code`）
        - 列表（- **key:** value）
        - 水平线（---）

        Args:
            markdown_text: Markdown 格式文本

        Returns:
            HTML 格式文本
        """
        if not markdown_text:
            return ""

        html_lines = []
        lines = markdown_text.split('\n')

        for line in lines:
            if line.startswith('# '):
                html_lines.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith('## '):
                html_lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith('### '):
                html_lines.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith('- **'):
                # 列表项
                content = line[3:]
                if ':**' in content:
                    key, value = content.split(':**', 1)
                    html_lines.append(f"<li><b>{key}:</b>{value}</li>")
                else:
                    html_lines.append(f"<li>{content}</li>")
            elif line.startswith('**') and line.endswith('**') and len(line) > 4:
                # 粗体
                content = line[2:-2]
                html_lines.append(f"<p><b>{content}</b></p>")
            elif line.startswith('`') and line.endswith('`') and len(line) > 2:
                # 行内代码
                content = line[1:-1]
                html_lines.append(f"<code style='background:#1B1F2A;color:#F2F2F7;padding:2px 4px;border-radius:3px;'>{content}</code>")
            elif line.startswith('*') and line.endswith('*') and len(line) > 2:
                # 斜体
                content = line[1:-1]
                html_lines.append(f"<p><i>{content}</i></p>")
            elif line.strip() == '':
                html_lines.append("<br>")
            elif line.startswith('*内容长度:'):
                # 统计信息
                html_lines.append(f"<p style='color:#9EA6B8;font-size:11px;'>{line[1:]}</p>")
            else:
                # 普通文本
                html_lines.append(f"<p>{line}</p>")

        return '\n'.join(html_lines)

    @staticmethod
    def doc_to_markdown(doc_title: str, doc: SimpleDocument) -> str:
        """
        将文档信息转换为Markdown格式

        Args:
            doc_title: 文档标题
            doc: SimpleDocument 实例

        Returns:
            Markdown 格式字符串
        """
        markdown_lines = []

        # 标题
        markdown_lines.append(f"# {doc_title}")
        markdown_lines.append("")

        # 文档ID
        if doc.id:
            markdown_lines.append(f"**文档ID:** `{doc.id}`")
            markdown_lines.append("")

        # 元数据
        if doc.metadata:
            markdown_lines.append("**元数据:**")
            for key, value in doc.metadata.items():
                if key.lower() not in ['title', 'name', 'filename', 'file_name']:
                    markdown_lines.append(f"- **{key}:** {value}")
            markdown_lines.append("")

        # 文档内容
        if doc.content:
            markdown_lines.append("**文档内容:**")
            markdown_lines.append("")
            markdown_lines.append(doc.content)
            markdown_lines.append("")
            markdown_lines.append(f"*内容长度: {len(doc.content)} 字符*")
            markdown_lines.append("")

        # 向量信息
        if doc.embedding is not None:
            markdown_lines.append(f"**向量信息:** 维度 {len(doc.embedding)}")

        return "\n".join(markdown_lines)


class ImportError(Exception):
    """
    导入错误封装

    提供友好的错误信息和解决建议。
    """

    def __init__(self, message: str, suggestions: Optional[list[str]] = None):
        """
        初始化导入错误

        Args:
            message: 错误消息
            suggestions: 解决建议列表
        """
        self.message = message
        self.suggestions = suggestions or []
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """格式化错误消息"""
        if not self.suggestions:
            return self.message
        formatted = f"{self.message}\n\n解决建议:\n"
        formatted += "\n".join(f"{i}. {s}" for i, s in enumerate(self.suggestions, 1))
        return formatted

    @classmethod
    def from_connection_error(cls, original_error: Exception) -> "ImportError":
        """从连接错误创建"""
        return cls(
            "网络连接错误，无法连接到嵌入模型服务",
            [
                "检查网络连接是否正常",
                "检查API密钥是否有效",
                "检查嵌入模型服务是否可用"
            ]
        )

    @classmethod
    def from_encoding_error(cls, file_path: str, original_error: Exception) -> "ImportError":
        """从编码错误创建"""
        if file_path.lower().endswith(('.xlsx', '.xls')):
            return cls(
                "Excel文件编码错误",
                [
                    "尝试用Excel重新保存文件",
                    "检查文件是否损坏",
                    "考虑将文件转换为CSV格式（UTF-8编码）"
                ]
            )
        return cls(
            "文件编码错误，可能使用了非UTF-8编码",
            [
                "将文件另存为UTF-8编码格式",
                "检查文件是否包含特殊字符"
            ]
        )

    @classmethod
    def from_pdf_error(cls, original_error: Exception) -> "ImportError":
        """从PDF导入错误创建"""
        return cls(
            "PDF导入失败，可能缺少依赖或文件损坏",
            [
                "确认已安装 pypdf 库",
                "检查文件完整性"
            ]
        )

    @classmethod
    def from_docx_error(cls, original_error: Exception) -> "ImportError":
        """从DOCX导入错误创建"""
        return cls(
            "DOCX导入失败，可能缺少依赖或文件损坏",
            [
                "确认已安装 python-docx 库",
                "检查文件完整性"
            ]
        )

    @classmethod
    def from_excel_error(cls, original_error: Exception) -> "ImportError":
        """从Excel导入错误创建"""
        return cls(
            "Excel导入失败，可能缺少依赖或文件损坏",
            [
                "安装 openpyxl (xlsx) 或 xlrd (xls)",
                "检查文件完整性"
            ]
        )

    @classmethod
    def from_empty_file(cls) -> "ImportError":
        """从空文件错误创建"""
        return cls(
            "导入完成，但没有新增文档",
            [
                "文件内容为空",
                "文件格式不正确",
                "相同内容已存在于知识库中",
                "网络连接问题导致嵌入生成失败"
            ]
        )
