# 设置界面

import json
import os
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QWidget, QLabel, 
                            QFormLayout, QGroupBox, QMessageBox)
from PyQt6.QtGui import QFont
from qfluentwidgets import (CardWidget, SubtitleLabel, CaptionLabel, BodyLabel, 
                           PrimaryPushButton, PushButton, StrongBodyLabel, 
                           LineEdit, ComboBox, ScrollArea, FluentIcon as FIF,
                           InfoBar, InfoBarPosition, TextEdit, PasswordLineEdit,
                           TimePicker)
from PyQt6.QtCore import QTime
from utils.logger_loguru import get_logger
from config import config
from utils.dialogs import confirm_action




class LLMConfigCard(CardWidget):
    """LLM配置卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 卡片标题
        title_label = StrongBodyLabel("LLM模型配置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        # API Base URL
        self.api_base_edit = LineEdit()
        self.api_base_edit.setPlaceholderText("https://ark.cn-beijing.volces.com/api/v3")
        self.api_base_edit.setText("https://ark.cn-beijing.volces.com/api/v3")
        form_layout.addRow("API Base URL:", self.api_base_edit)

        # API Key
        self.api_key_edit = PasswordLineEdit()
        self.api_key_edit.setPlaceholderText("输入您的 API Key")
        form_layout.addRow("API Key:", self.api_key_edit)

        # Model Name
        self.model_name_edit = LineEdit()
        self.model_name_edit.setPlaceholderText("输入模型名称，如：doubao-seed-1-6-flash-250828")
        form_layout.addRow("模型名称:", self.model_name_edit)

        layout.addLayout(form_layout)

        # 说明文本
        description_label = CaptionLabel(
            "配置LLM模型的连接参数。\n"
            "支持OpenAI兼容的API接口，包括豆包、通义千问等模型。"
        )
        description_label.setStyleSheet("color: #9EA6B8; padding: 8px 0;")
        layout.addWidget(description_label)

    def getConfig(self) -> dict:
        """获取配置"""
        return {
            "api_base": self.api_base_edit.text().strip() or "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": self.api_key_edit.text().strip(),
            "model_name": self.model_name_edit.text().strip()
        }

    def setConfig(self, config: dict):
        """设置配置"""
        self.api_base_edit.setText(config.get("api_base", "https://ark.cn-beijing.volces.com/api/v3"))
        self.api_key_edit.setText(config.get("api_key", ""))
        self.model_name_edit.setText(config.get("model_name", ""))


class EmbedderConfigCard(CardWidget):
    """嵌入器配置卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 卡片标题
        title_label = StrongBodyLabel("嵌入模型配置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        # Embedder API Base URL
        self.api_base_edit = LineEdit()
        self.api_base_edit.setPlaceholderText("https://ark.cn-beijing.volces.com/api/v3")
        form_layout.addRow("API Base URL:", self.api_base_edit)

        # Embedder API Key
        self.api_key_edit = PasswordLineEdit()
        self.api_key_edit.setPlaceholderText("输入嵌入模型的 API Key（可选）")
        form_layout.addRow("API Key:", self.api_key_edit)

        # Embedder Model Name
        self.model_name_edit = LineEdit()
        self.model_name_edit.setPlaceholderText("输入嵌入模型名称，如：doubao-embedding-large-text-250515")
        form_layout.addRow("模型名称:", self.model_name_edit)

        layout.addLayout(form_layout)

        # 说明文本
        description_label = CaptionLabel(
            "配置向量嵌入模型参数。\n"
            "用于知识库的语义搜索和相似度匹配。"
        )
        description_label.setStyleSheet("color: #9EA6B8; padding: 8px 0;")
        layout.addWidget(description_label)

    def getConfig(self) -> dict:
        """获取配置"""
        return {
            "api_base": self.api_base_edit.text().strip() or "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": self.api_key_edit.text().strip(),
            "model_name": self.model_name_edit.text().strip()
        }

    def setConfig(self, config: dict):
        """设置配置"""
        self.api_base_edit.setText(config.get("api_base", "https://ark.cn-beijing.volces.com/api/v3"))
        self.api_key_edit.setText(config.get("api_key", ""))
        self.model_name_edit.setText(config.get("model_name", ""))


class KnowledgeConfigCard(CardWidget):
    """知识库配置卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 卡片标题
        title_label = StrongBodyLabel("知识库配置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        # Contents DB Path
        self.contents_db_edit = LineEdit()
        self.contents_db_edit.setPlaceholderText("内容数据库路径")
        form_layout.addRow("内容数据库路径:", self.contents_db_edit)

        # Vector DB Path
        self.vector_db_edit = LineEdit()
        self.vector_db_edit.setPlaceholderText("向量数据库路径")
        form_layout.addRow("向量数据库路径:", self.vector_db_edit)

        layout.addLayout(form_layout)

        # 说明文本
        description_label = CaptionLabel(
            "配置知识库的存储路径。\n"
            "内容数据库存储结构化数据，向量数据库存储嵌入向量。"
        )
        description_label.setStyleSheet("color: #9EA6B8; padding: 8px 0;")
        layout.addWidget(description_label)

    def getConfig(self) -> dict:
        """获取配置"""
        return {
            "contents_db_path": self.contents_db_edit.text().strip(),
            "vector_db_path": self.vector_db_edit.text().strip()
        }

    def setConfig(self, config: dict):
        """设置配置"""
        self.contents_db_edit.setText(config.get("contents_db_path", ""))
        self.vector_db_edit.setText(config.get("vector_db_path", ""))


class PromptConfigCard(CardWidget):
    """提示词配置卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()

    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # 卡片标题
        title_label = StrongBodyLabel("AI提示词配置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)

        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)

        # 角色描述
        self.description_edit = TextEdit()
        self.description_edit.setPlaceholderText(
            "输入AI助手的角色描述，如：你是一个专业的电商客服助手..."
        )
        self.description_edit.setMaximumHeight(100)
        form_layout.addRow("角色描述:", self.description_edit)

        # 额外提示词
        self.additional_context_edit = TextEdit()
        self.additional_context_edit.setPlaceholderText(
            "输入额外的提示词或上下文信息..."
        )
        self.additional_context_edit.setMaximumHeight(100)
        form_layout.addRow("额外提示词:", self.additional_context_edit)

        self.instructions_edit = TextEdit()
        self.instructions_edit.setPlaceholderText("输入行为指令，每行一条")
        self.instructions_edit.setMaximumHeight(120)
        form_layout.addRow("行为指令:", self.instructions_edit)

        layout.addLayout(form_layout)

        # 说明文本
        description_label = CaptionLabel(
            "配置AI助手的行为和回复风格。\n"
            "清晰的提示词可以帮助AI提供更准确和有用的回复。"
        )
        description_label.setStyleSheet("color: #9EA6B8; padding: 8px 0;")
        layout.addWidget(description_label)

    def getConfig(self) -> dict:
        """获取配置"""
        return {
            "description": self.description_edit.toPlainText().strip(),
            "additional_context": self.additional_context_edit.toPlainText().strip(),
            "instructions": [
                line.strip() for line in self.instructions_edit.toPlainText().splitlines() if line.strip()
            ]
        }

    def setConfig(self, config: dict):
        """设置配置"""
        self.description_edit.setPlainText(config.get("description", ""))
        self.additional_context_edit.setPlainText(config.get("additional_context", ""))
        instructions = config.get("instructions", [])
        if isinstance(instructions, list):
            self.instructions_edit.setPlainText("\n".join(instructions))
        elif isinstance(instructions, str):
            self.instructions_edit.setPlainText(instructions)


class BusinessHoursCard(CardWidget):
    """业务时间配置卡片"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()
    
    def setupUI(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)
        
        # 卡片标题
        title_label = StrongBodyLabel("业务时间设置")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title_label)
        
        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form_layout.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        
        # 开始时间
        self.start_time_picker = TimePicker()
        self.start_time_picker.setTime(QTime(8, 0))  # 默认8:00
        form_layout.addRow("开始时间:", self.start_time_picker)
        
        # 结束时间
        self.end_time_picker = TimePicker()
        self.end_time_picker.setTime(QTime(23, 0))  # 默认23:00
        form_layout.addRow("结束时间:", self.end_time_picker)
        
        layout.addLayout(form_layout)
        
        # 说明文本
        description_label = CaptionLabel(
            "设置AI客服的工作时间。在工作时间内，系统将自动响应客户消息。\n"
            "在非工作时间，系统将不会自动回复。"
        )
        description_label.setStyleSheet("color: #9EA6B8; padding: 8px 0;")
        layout.addWidget(description_label)
    
    def getConfig(self) -> dict:
        """获取配置"""
        return {
            "businessHours": {
                "start": self.start_time_picker.getTime().toString("HH:mm"),
                "end": self.end_time_picker.getTime().toString("HH:mm")
            },
            "business_hours": {
                "start": self.start_time_picker.getTime().toString("HH:mm"),
                "end": self.end_time_picker.getTime().toString("HH:mm")
            }
        }
    
    def setConfig(self, config: dict):
        """设置配置"""
        # 支持新旧配置格式
        business_hours = config.get("businessHours", config.get("business_hours", {}))

        # 解析开始时间
        start_time_str = business_hours.get("start", "08:00")
        start_time = QTime.fromString(start_time_str, "HH:mm")
        if start_time.isValid():
            self.start_time_picker.setTime(start_time)

        # 解析结束时间
        end_time_str = business_hours.get("end", "23:00")
        end_time = QTime.fromString(end_time_str, "HH:mm")
        if end_time.isValid():
            self.end_time_picker.setTime(end_time)


class SettingUI(QFrame):
    """设置界面"""
    
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.logger = get_logger("SettingUI")
        self.setupUI()
        self.loadConfig()
        
        # 设置对象名
        self.setObjectName("设置")
    
    def setupUI(self):
        """设置主界面UI"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)
        
        # 创建头部区域
        header_widget = self.createHeaderWidget()
        
        # 创建内容区域
        content_widget = self.createContentWidget()
        
        # 连接按钮信号
        self.save_btn.clicked.connect(self.onSaveConfig)
        self.reset_btn.clicked.connect(self.onResetConfig)
        
        # 添加到主布局
        main_layout.addWidget(header_widget)
        main_layout.addWidget(content_widget, 1)
    
    def createHeaderWidget(self):
        """创建头部区域"""
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(20)
        
        # 标题（与关键词管理等页一致：SubtitleLabel + CaptionLabel，无单独放大字号）
        title_label = SubtitleLabel("系统设置")

        # 描述
        description_label = CaptionLabel("配置AI客服的基本参数和工作时间")
        
        # 左侧标题区域
        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(5)
        title_layout.addWidget(title_label)
        title_layout.addWidget(description_label)
        
        # 按钮区域
        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)
        
        # 重置按钮
        self.reset_btn = PushButton("重置")
        self.reset_btn.setIcon(FIF.UPDATE)
        self.reset_btn.setFixedSize(120, 40)
        
        # 保存按钮
        self.save_btn = PrimaryPushButton("保存")
        self.save_btn.setIcon(FIF.SAVE)
        self.save_btn.setFixedSize(120, 40)
        
        buttons_layout.addWidget(self.reset_btn)
        buttons_layout.addWidget(self.save_btn)
        
        # 添加到头部布局
        header_layout.addWidget(title_area)
        header_layout.addStretch()
        header_layout.addWidget(buttons_widget)
        
        return header_widget
    
    def createContentWidget(self):
        """创建内容区域"""
        # 滚动区域
        scroll_area = ScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # 去除边框
        scroll_area.setStyleSheet("""
            ScrollArea {
                border: none;
                background-color: transparent;
            }
        """)

        # 内容容器
        content_container = QWidget()
        content_layout = QVBoxLayout(content_container)
        content_layout.setSpacing(20)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 创建配置卡片
        self.llm_config_card = LLMConfigCard()
        self.embedder_config_card = EmbedderConfigCard()
        self.knowledge_config_card = KnowledgeConfigCard()
        self.prompt_config_card = PromptConfigCard()
        self.business_hours_card = BusinessHoursCard()

        # 添加到布局
        content_layout.addWidget(self.llm_config_card)
        content_layout.addWidget(self.embedder_config_card)
        content_layout.addWidget(self.knowledge_config_card)
        content_layout.addWidget(self.prompt_config_card)
        content_layout.addWidget(self.business_hours_card)
        content_layout.addStretch()

        # 设置容器样式
        content_container.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
            }
        """)

        scroll_area.setWidget(content_container)

        return scroll_area
    
    def loadConfig(self):
        """从config模块加载配置"""
        try:
            # 从配置模块获取各个配置项
            loaded_config = {
                "llm": {
                    "api_base": config.get("llm.api_base", "https://ark.cn-beijing.volces.com/api/v3"),
                    "api_key": config.get("llm.api_key", ""),
                    "model_name": config.get("llm.model_name", "doubao-seed-1-6-flash-250828")
                },
                "embedder": {
                    "api_base": config.get("embedder.api_base", "https://ark.cn-beijing.volces.com/api/v3"),
                    "api_key": config.get("embedder.api_key", ""),
                    "model_name": config.get("embedder.model_name", "doubao-embedding-large-text-250515")
                },
                "knowledge_base": {
                    "contents_db_path": config.get("knowledge_base.contents_db_path", ""),
                    "vector_db_path": config.get("knowledge_base.vector_db_path", "")
                },
                "prompt": {
                    "description": config.get("prompt.description", ""),
                    "additional_context": config.get("prompt.additional_context", ""),
                    "instructions": config.get("prompt.instructions", [])
                },
                "business_hours": {
                    "start": config.get("business_hours.start", "08:00"),
                    "end": config.get("business_hours.end", "23:00")
                }
            }

            # 验证并设置配置
            self._validateAndSetConfig(loaded_config)
            self.logger.info("配置加载成功")

        except Exception as e:
            self.logger.error(f"加载配置失败: {e}")
            QMessageBox.warning(self, "加载失败", f"加载配置失败：{str(e)}")
            self._loadDefaultConfig()
    
    def _loadDefaultConfig(self):
        """加载默认配置"""
        default_config = {
            "llm": {
                "api_base": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key": "",
                "model_name": "doubao-seed-1-6-flash-250828"
            },
            "embedder": {
                "api_base": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key": "",
                "model_name": "doubao-embedding-large-text-250515"
            },
            "knowledge_base": {
                "contents_db_path": "",
                "vector_db_path": ""
            },
            "prompt": {
                "description": "你是一个专业的电商客服助手，负责为拼多多店铺提供优质的客户服务。请遵循以下原则：\n\n1. 友好专业：始终保持礼貌、耐心和专业的态度\n2. 准确回答：根据客户问题提供准确、有用的信息\n3. 主动服务：主动了解客户需求，提供个性化建议\n4. 及时响应：快速响应客户咨询，提高服务效率\n5. 问题解决：积极帮助客户解决购物和售后问题",
                "additional_context": "请用简洁明了的语言回复，避免过长的回答。如果遇到无法解决的复杂问题，请礼貌地建议客户联系人工客服。",
                "instructions": [
                    "1. 请用中文回复客户问题",
                    "2. 如果客户问题超出了你的能力范围，请建议客户联系人工客服"
                ]
            },
            "business_hours": {
                "start": "08:00",
                "end": "23:00"
            }
        }

        self._validateAndSetConfig(default_config)
        self.logger.info("已加载默认配置")

    def _validateAndSetConfig(self, config_data):
        """验证并设置配置"""
        # 确保必要的字段存在
        validated_config = {
            "llm": config_data.get("llm", {
                "api_base": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key": "",
                "model_name": "doubao-seed-1-6-flash-250828"
            }),
            "embedder": config_data.get("embedder", {
                "api_base": "https://ark.cn-beijing.volces.com/api/v3",
                "api_key": "",
                "model_name": "doubao-embedding-large-text-250515"
            }),
            "knowledge_base": config_data.get("knowledge_base", {
                "contents_db_path": "",
                "vector_db_path": ""
            }),
            "prompt": config_data.get("prompt", {
                "description": "",
                "additional_context": "",
                "instructions": []
            }),
            "business_hours": config_data.get("business_hours", {"start": "08:00", "end": "23:00"})
        }

        # 验证business_hours格式
        business_hours = validated_config["business_hours"]
        if not isinstance(business_hours, dict):
            business_hours = {"start": "08:00", "end": "23:00"}
            validated_config["business_hours"] = business_hours

        if "start" not in business_hours:
            business_hours["start"] = "08:00"
        if "end" not in business_hours:
            business_hours["end"] = "23:00"

        # 设置到界面
        self.llm_config_card.setConfig(validated_config["llm"])
        self.embedder_config_card.setConfig(validated_config["embedder"])
        self.knowledge_config_card.setConfig(validated_config["knowledge_base"])
        self.prompt_config_card.setConfig(validated_config["prompt"])

        # 处理业务时间配置
        business_hours_config = validated_config["business_hours"]
        self.business_hours_card.setConfig({"business_hours": business_hours_config})
    
    def onSaveConfig(self):
        """保存配置到config模块"""
        try:
            # 获取各配置卡片的配置
            llm_config = self.llm_config_card.getConfig()
            embedder_config = self.embedder_config_card.getConfig()
            knowledge_config = self.knowledge_config_card.getConfig()
            prompt_config = self.prompt_config_card.getConfig()
            business_config = self.business_hours_card.getConfig()

            # 合并配置为新的结构
            new_config = {
                "llm": llm_config,
                "embedder": embedder_config,
                "knowledge_base": knowledge_config,
                "prompt": prompt_config,
                "business_hours": business_config.get("businessHours", {"start": "08:00", "end": "23:00"}),
                # 保持与旧配置的兼容性
                "db_path": config.get("db_path", "")
            }

            # 验证 LLM 必填项
            if not llm_config.get("api_key"):
                QMessageBox.warning(self, "配置错误", "请输入LLM API Key！")
                return
            if not llm_config.get("model_name"):
                QMessageBox.warning(self, "配置错误", "请输入LLM模型名称！")
                return

            # 验证时间设置
            start_time = self.business_hours_card.start_time_picker.getTime()
            end_time = self.business_hours_card.end_time_picker.getTime()

            if start_time >= end_time:
                QMessageBox.warning(self, "时间设置错误", "开始时间必须早于结束时间！")
                return

            # 使用config模块保存配置
            config.update(new_config, save=True)

            self.logger.info("配置保存成功")

            # 显示成功消息
            InfoBar.success(
                title="保存成功",
                content="配置已保存！",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )

        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")
            QMessageBox.critical(self, "保存失败", f"保存配置时发生错误：{str(e)}")
    
    def onResetConfig(self):
        """重置配置"""
        if confirm_action(
            self,
            "确认重置",
            "确定要重置所有配置吗？\n这将重新加载配置文件中的原始设置。",
            confirm_text="确认重置",
            cancel_text="取消",
            destructive=True,
        ):
            try:
                # 使用config模块重新加载配置文件
                config.reload()
                self.loadConfig()
                self.logger.info("配置已重置")
                
                InfoBar.success(
                    title="重置成功",
                    content="配置已重置为配置文件中的设置！",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self
                )
            except Exception as e:
                self.logger.error(f"重置配置失败: {e}")
                QMessageBox.critical(self, "重置失败", f"重置配置失败：{str(e)}")
    
 
