# Customer-Agent · 电商 AI 客服桌面端

面向拼多多商家的 **PyQt6 桌面应用**：接入店铺会话、AI 自动回复、知识库与关键词转人工，可选对接拼多多开放平台（物流轨迹等）。

> **致谢与代码库说明**  
> **[L1S0NE](https://github.com/L1S0NE)** 为项目的重要贡献者与早期开源基础来源，特此致谢。  
> **本仓库**由当前维护者**独立维护**，是**自有代码库**（Issue、PR、Release 均以本仓库为准）；在持续开发中，功能与实现已与 L1S0NE 及他人维护的上游存在**显著差异**，并非对方仓库的镜像。若使用或二次分发，请尊重历史贡献者的劳动，并对沿用自上游的代码段遵守其许可与署名要求。

---

## 功能概览

| 模块 | 说明 |
|------|------|
| **账号与会话** | 多账号管理；Playwright 登录保存 Cookie；WebSocket 接收买家消息并自动回复 |
| **AI 回复** | 基于 [Agno](https://github.com/agno-agi/agno) 与 OpenAI 兼容接口（DeepSeek、通义、Gemini 等），支持嵌入向量与知识检索 |
| **知识库** | 导入 PDF / 表格 / 文本，向量检索 + 本地持久化 |
| **关键词** | 自定义命中词转人工或触发协助流程 |
| **订单与物流** | 买家咨询物流时，可调用开放平台 `pdd.logistics.ordertrace.get`（需在 `config.json` 配置 `pinduoduo_open`）；修改收货信息等意图可走转人工 |
| **AI 测试对话** | 无需登录店铺即可调试模型与话术（见主界面入口） |
| **日志与设置** | Loguru 日志、模型与路径等配置 |

---

## 环境要求

- **Python** 3.11+
- **操作系统**：Windows 10/11、macOS、Linux（打包脚本以 Windows 为主）
- 稳定的网络（LLM API、拼多多 WebSocket / HTTP）

---

## 安装

推荐使用 [uv](https://github.com/astral-sh/uv)：

```bash
# 协作与克隆请以本仓库为准（以下为当前维护方地址）
git clone https://github.com/JC0v0/Customer-Agent.git
cd Customer-Agent

pip install uv
uv venv
uv sync
```

安装 Playwright 浏览器（用于商家后台登录）：

```bash
uv run playwright install chromium
```

---

## 运行

```bash
# 激活虚拟环境后
python app.py
```

首次运行会在可写目录生成默认 `config.json`（含敏感信息，请勿提交到版本库）。

---

## 配置要点

### LLM 与 Embedding

在 **设置** 界面或编辑 `config.json` 中的 `llm`、`embedder`：填写 `api_base`、`api_key`、`model_name`。

### 拼多多开放平台（物流查询等）

在 `config.json` 中配置 `pinduoduo_open`（用于调用 `https://gw-api.pinduoduo.com/api/router`）：

```json
"pinduoduo_open": {
  "enabled": true,
  "client_id": "",
  "client_secret": "",
  "access_token": ""
}
```

在开放平台创建应用、完成店铺授权后填入 `access_token`。物流接口说明见官方文档：[pdd.logistics.ordertrace.get](https://open.pinduoduo.com/application/document/api?id=pdd.logistics.ordertrace.get)。

### 其他

- `knowledge_base`：内容与向量库路径  
- `chat.manual_mode_send_notice`：人工模式下是否向买家发送提示（可选）

---

## 技术栈

| 类别 | 技术 |
|------|------|
| UI | PyQt6、PyQt-Fluent-Widgets |
| AI | Agno、OpenAI 兼容 API、LanceDB / SQLite |
| 数据 | SQLAlchemy、SQLite |
| 渠道 | WebSocket、Requests、Playwright |
| 日志 | Loguru |
| 依赖管理 | uv、`pyproject.toml` |

---

## 仓库结构（节选）

```
├── app.py                 # 入口
├── config.py              # 配置加载与校验
├── Agent/                 # 客服 Agent、知识库、工具
├── Channel/pinduoduo/     # 拼多多：登录、WS、API（消息、商品、开放平台封装等）
├── Message/               # 消息队列、AI/关键词/订单物流等 Handler
├── core/                  # DI、连接状态、缓存
├── database/              # ORM 与业务数据
├── ui/                    # 主窗口与各功能页（设置、知识库、关键词、AI 测试等）
├── utils/                 # 日志、路径、运行时目录
└── scripts/               # 打包与辅助脚本
```

---

## 打包

- Windows 可执行文件：在 Windows 上执行 `python scripts/build_win_exe.py`（详见 `scripts/` 内说明）。
- 通用构建：`python scripts/build_exe.py`。

---

## 开发与测试

```bash
uv sync --group dev
uv run python -m pytest test/
```

覆盖率（核心包）：终端摘要 + HTML 报告可输出到 `htmlcov/`（见下方命令；`htmlcov/` 已加入 `.gitignore`）。

```bash
uv run python -m pytest test/ \
  --cov=utils --cov=database --cov=Message --cov=bridge --cov=core \
  --cov-report=term-missing --cov-report=html
```

- 内部 HTTP / 开放平台 / WebSocket 索引见 **[API.md](API.md)**  
- 常见启动、登录、配置错误见 **[ERRORS.md](ERRORS.md)**  
- **代码与架构说明**（模块职责、消息流、处理器链、扩展方式）见 **[docs/代码架构说明.md](docs/代码架构说明.md)**

（集成与手工验证仍建议保留。）

---

## 贡献

欢迎针对**本仓库当前代码树**提交 Issue 与 Pull Request（说明环境、复现步骤或变更意图）。我们承认 **[L1S0NE](https://github.com/L1S0NE)** 的历史贡献；若变更涉及与上游共用的代码片段，请保留合理署名并遵守相应许可。

完整流程（Fork、分支、推送、PR）见 **[CONTRIBUTING.md](CONTRIBUTING.md)**。

---

## 许可说明

本仓库为**独立维护、自行演进的分发版本**，**不以维护者名义**提供「整项目统一开源许可证（如 MIT）」。对其中**仍沿用自 L1S0NE 或上游**的代码，使用条件**以原作者及上游实际声明为准**；本仓库内**新增与修改**部分的合规与再分发，请参阅根目录 `LICENSE`（**许可与版权说明 / NOTICE**），勿将其误读为对全部代码的 MIT 式再授权。

---

## 相关链接

- 问题反馈：[GitHub Issues](https://github.com/JC0v0/Customer-Agent/issues)

若文档或截图在本地 `docs/`、`icon/` 下，克隆后即可在 README 中按需恢复插图路径。
