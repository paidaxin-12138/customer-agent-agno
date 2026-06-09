<!-- Copyright (c) 2026 paidaxin-12138 — CC BY-NC 4.0 — see LICENSE -->

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

- **macOS `.app`**（本机已构建可直接试跑）：

```bash
uv run python scripts/build_mac_app.py --clean
open dist/AgentCustomer.app
```

  输出：`dist/AgentCustomer.app`（约 1.2GB，含 PyQt6 / Playwright 等）。用户数据在 `~/Library/Application Support/AgentCustomer/`。首次拼多多登录仍需本机安装 Playwright 浏览器（见 `dist/README-mac.txt`）。

- **Windows 发布目录**（须在 Windows 本机构建）：

```bash
uv run python scripts/build_win_exe.py --clean
# 运行: dist\AgentCustomer\AgentCustomer.exe
```

  输出：`dist/AgentCustomer/`（onedir，含 `AgentCustomer.exe` 与依赖）。用户数据在 `%LOCALAPPDATA%\AgentCustomer\`。Playwright 需本机执行 `uv run playwright install chromium`（见 `dist/README-win.txt`）。

- 通用构建（历史脚本）：`python scripts/build_exe.py`。

---

## 开发与测试

```bash
uv sync --group dev
uv run python -m pytest test/          # 默认不跑覆盖率，适合本地快速验证
uv run python -m pytest test/test_ui_smoke.py -v   # 单文件子集
```

**覆盖率（与 CI 一致）**：统计 `Message` / `bridge` / `core` / `database` / `utils`；`ui`、`Channel`、`Agent` 等见 `pyproject.toml` 的 `omit` 列表。门禁 **≥ 65%** 仅在 CI 启用。

```bash
QT_QPA_PLATFORM=offscreen uv run python -m pytest test/ -q \
  --cov=Message --cov=bridge --cov=core --cov=database --cov=utils \
  --cov-report=term-missing:skip-covered --cov-fail-under=65
```

可选 HTML 报告：`--cov-report=html`（输出到 `htmlcov/`，已 `.gitignore`）。

性能基线（非门禁）：`uv run python -m pytest test/test_concurrency_benchmark.py -m perf -s`（写入 `logs/perf_baseline.json`）

- **架构图（Mermaid）**：数据流与模块依赖见 **[docs/architecture.md](docs/architecture.md)**
- **生产部署**（PM2 / systemd / 健康检查）见 **[docs/生产部署说明.md](docs/生产部署说明.md)**

（集成与手工验证仍建议保留。）

---

## 已知限制

- **拼多多专用**：WebSocket + 商家后台 Cookie 为当前唯一完整接入渠道；开放平台仅覆盖物流等部分 API。
- **Cookie / Playwright**：登录态会过期，需重新登录或刷新 Cookie；无人值守环境要配合健康检查与告警。
- **历史消息**：断线重连后不一定能补齐全部 MMS 历史，以本地 SQLite 与 Hub 为准。
- **知识库**：向量检索依赖 embedder 配置；大文件首次导入与全量同步可能占用数秒 CPU/网络。
- **桌面单进程**：适合单店/少量账号；大规模多租户需自行拆分服务。
- **测试范围**：`pytest` 覆盖消息链与核心工具；完整 UI 流程仍需人工点验。

---

## 贡献

欢迎针对**本仓库当前代码树**提交 Issue 与 Pull Request（说明环境、复现步骤或变更意图）。我们承认 **[L1S0NE](https://github.com/L1S0NE)** 的历史贡献；若变更涉及与上游共用的代码片段，请保留合理署名并遵守相应许可。

---

## 许可说明

Copyright (c) 2026 [paidaxin-12138](https://github.com/paidaxin-12138)

本仓库由当前维护者独立维护。其中**新增与修改**部分采用 [知识共享 署名-非商业性使用 4.0 国际许可协议](https://creativecommons.org/licenses/by-nc/4.0/)（CC BY-NC 4.0）进行许可：您可以自由地共享、复制、传播本作品的**非商业**用途，但须署名原作者。完整许可文本见根目录 [LICENSE](LICENSE)（安装包使用 [LICENSE.txt](LICENSE.txt)）。

对其中**仍沿用自 [L1S0NE](https://github.com/L1S0NE) 或上游**的代码段，使用条件**以原作者及上游实际声明为准**，请保留合理署名并遵守相应许可。

---

## 相关链接

- 问题反馈：[GitHub Issues](https://github.com/paidaxin-12138/customer-agent-agno/issues)

若文档或截图在本地 `docs/`、`icon/` 下，克隆后即可在 README 中按需恢复插图路径。
