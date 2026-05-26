"""
知识库模块自定义异常
提供统一的异常处理和错误提示
"""
from typing import Optional, List


class KnowledgeException(Exception):
    """知识库异常基类"""

    def __init__(self, message: str, suggestions: Optional[List[str]] = None):
        """
        初始化异常

        Args:
            message: 错误消息
            suggestions: 解决建议列表
        """
        self.message = message
        self.suggestions = suggestions or []
        super().__init__(self.message)

    def get_formatted_message(self) -> str:
        """
        获取格式化的错误消息

        Returns:
            包含建议的完整错误消息
        """
        if not self.suggestions:
            return self.message

        formatted = f"{self.message}\n\n建议：\n"
        formatted += "\n".join(f"• {s}" for s in self.suggestions)
        return formatted


class ImportException(KnowledgeException):
    """导入异常"""

    @classmethod
    def from_empty_file(cls) -> 'ImportException':
        """创建空文件异常"""
        return cls(
            "文件为空或没有可导入的内容",
            [
                "请检查文件是否包含有效数据",
                "尝试使用其他文件",
                "确认文件格式正确"
            ]
        )

    @classmethod
    def from_validation_error(cls, error_message: str, suggestions: List[str]) -> 'ImportException':
        """创建验证错误异常"""
        return cls(error_message, suggestions)


class LoadException(KnowledgeException):
    """加载异常"""

    @classmethod
    def from_database_error(cls, error: str) -> 'LoadException':
        """创建数据库错误异常"""
        return cls(
            f"数据库加载失败: {error}",
            [
                "检查数据库文件是否存在",
                "确认数据库文件未被损坏",
                "尝试重启应用程序",
                "如果问题持续，请联系技术支持"
            ]
        )


class ValidationException(KnowledgeException):
    """验证异常"""

    @classmethod
    def from_file_error(cls, file_path: str, error: str) -> 'ValidationException':
        """创建文件验证错误异常"""
        return cls(
            f"文件验证失败: {file_path}\n{error}",
            [
                "检查文件格式是否支持",
                "确认文件未损坏",
                "尝试重新保存文件"
            ]
        )
