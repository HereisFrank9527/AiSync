# AiSync

AiSync 是一个面向长篇小说创作的本地桌面工具。当前形态是：

- Tauri 2 桌面壳
- React + Vite 前端
- Python FastAPI 后端
- Agent 通过 LLM tool calling 读写项目文件
- 项目内容保存在用户选择的本地文件夹中

核心目标是让小说项目保持“文件可控、工具可见、Agent 可协作”。前端提供对话、文件树、基础信息、章节/角色/世界观、大纲、向量索引、工具中心和 LLM 预设配置。

## 项目结构

```text
AiSync/
├── backend/                  # FastAPI 后端
│   ├── app/
│   │   ├── agent.py          # MasterAgent 主循环
│   │   ├── cli.py            # 后端命令行入口
│   │   ├── main.py           # FastAPI 应用入口
│   │   ├── api/              # REST / WebSocket API
│   │   ├── conversations/    # 对话历史与记忆压缩
│   │   ├── core/             # 配置与 LLM 预设
│   │   ├── llm/              # Anthropic / OpenAI 兼容客户端
│   │   ├── projects/         # 项目文件安全读写与大纲解析
│   │   ├── tools/            # Agent 工具
│   │   └── vector/           # 项目索引与检索
│   ├── tests/
│   └── pyproject.toml
├── frontend/                 # React + Vite + Tauri
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── config/
│   │   └── workspaceViews.tsx
│   ├── src-tauri/
│   │   ├── src/main.rs       # Tauri 壳、内置 Python 后端启动、自动 venv 回退、诊断日志
│   │   └── tauri.conf.json
│   └── package.json
├── scripts/
│   ├── tauri_dev.ps1         # 开发态：启动 Python 后端 + Vite
│   ├── tauri_build.ps1       # 发布态：构建前端并准备运行时资源
│   ├── prepare_runtime_python.ps1 # 准备内置 Python runtime
│   ├── prepare_runtime_wheels.ps1 # 准备离线 Python 依赖 wheels（可选）
│   └── prepare_tauri_backend.ps1 # 拷贝干净后端源码到 Tauri resources
├── 工具描述.md
└── 规划.md
```

## 环境要求

- Windows 当前支持最好
- Python 3.11，开发机需要；安装版已随包携带 Python runtime
- Node.js 18+
- Rust toolchain
- Tauri 2 依赖

可选：

- `chromadb`：启用 Chroma 向量库后端

## 安装依赖

后端：

```powershell
.\.conda\python.exe -m pip install -e "backend[dev,package]"
```

如果要使用 Chroma：

```powershell
.\.conda\python.exe -m pip install -e "backend[vector]"
```

前端：

```powershell
cd frontend
npm install
```

## 开发运行

推荐直接运行桌面开发模式：

```powershell
cd frontend
npm run tauri dev
```

开发态行为：

- 不会打包 Python 后端
- `scripts/tauri_dev.ps1` 会先检查 `http://127.0.0.1:8000/health`
- 如果后端没启动，会用源码方式启动：

```powershell
.\.conda\python.exe -m app.cli --host 127.0.0.1 --port 8000 --reload
```

- 前端由 Vite 提供，端口是 `1420`
- 开发后端日志写入 `.dev-logs/`

也可以手动分开跑：

```powershell
cd backend
..\.conda\python.exe -m app.cli --reload
```

```powershell
cd frontend
npm run dev
```

健康检查：

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

## 打包发布

发布态现在使用 `Tauri + 后端源码资源 + 内置 Python runtime`。打包时不再把后端临时编译成 PyInstaller exe；安装包会携带一个轻量 Python runtime 和后端依赖，安装后的桌面程序优先直接用随包 Python 启动 FastAPI 后端。

### 修改版本号

应用版本号的人工修改点只有一个：

```text
frontend/src-tauri/tauri.conf.json
```

修改：

```json
"version": "0.1.4"
```

前端启动状态、Rust 诊断日志和窗口标题都会从这个版本号派生。`frontend/package.json` 和 `frontend/src-tauri/Cargo.toml` 的版本当前只作为各自工具链包版本，不作为 AiSync 发布版本。

一条命令构建完整安装包：

```powershell
cd frontend
npm run tauri build
```

构建过程会自动：

1. 构建 React 前端
2. 拷贝干净后端源码到 `frontend/src-tauri/resources/backend-src/`
3. 如不存在内置 Python，则准备 `frontend/src-tauri/resources/runtime/python/`
4. 构建 Tauri 安装包

产物位置：

```text
frontend/src-tauri/target/release/bundle/msi/
frontend/src-tauri/target/release/bundle/nsis/
```

运行安装版时，后端启动顺序是：

1. 自动选择一个可用的 `127.0.0.1` 本地端口；如需固定端口，可设置 `AISYNC_BACKEND_PORT`
2. 查找随包资源 `runtime/python/pythonw.exe` / `runtime/python/python.exe`
3. 用随包 Python 直接启动 `python -m app.cli --host 127.0.0.1 --port <自动端口>`
4. 前端通过 Tauri 命令读取真实 API 地址，不再写死 `8000`
5. 如果随包 Python 不可用，回退到自动 venv
6. venv 回退会查找 `%APPDATA%\com.aisync.app\runtime\.venv\Scripts\python.exe`
7. 再查找 `AISYNC_PYTHON`
8. 再查找系统 `python` / `py`
9. 自动执行 `python -m venv ...` 和 `pip install <随包 backend-src>`

用户不需要安装 Python，也不需要手动创建 venv。

注意：

- 开发态 `npm run tauri dev` 不会再打包后端
- 开发态仍默认使用 `127.0.0.1:8000`，方便源码调试
- 发布态 `npm run tauri build` 不再跑 PyInstaller
- 安装包已携带 `frontend/src-tauri/resources/runtime/python/python.exe`
- 安装版会隐藏后端 Python 控制台窗口， stdout/stderr 写入日志文件
- 如需强制跳过 runtime 自动准备，可设置 `AISYNC_SKIP_RUNTIME_PREP=1`

手动准备内置 Python runtime：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_runtime_python.ps1
```

可选：准备离线 wheels。

默认交付包不携带 wheelhouse，因为 AiSync 本身仍依赖外部 LLM API，且当前安装版已经随包携带可直接运行的 Python runtime 和依赖。wheelhouse 只用于增强 venv 回退路径：当随包 runtime 不可用、客户机又不能联网安装依赖时才需要。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/prepare_runtime_wheels.ps1
```

如果要把 Chroma 依赖也打进离线 wheels：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/prepare_runtime_wheels.ps1 -IncludeVector
```

生成目录：

```text
frontend/src-tauri/resources/runtime/wheels/
```

安装版启动时如果发现该目录内有 `aisync-backend` wheel，会优先从 wheelhouse 离线安装；否则退回安装随包 `backend-src`。

## 运行日志

安装版日志位置：

```text
%APPDATA%\com.aisync.app\startup-diagnostics.txt
%LOCALAPPDATA%\com.aisync.app\logs\frontend.boot.log
%LOCALAPPDATA%\com.aisync.app\logs\backend.last_start.txt
%LOCALAPPDATA%\com.aisync.app\logs\backend.setup.out.log
%LOCALAPPDATA%\com.aisync.app\logs\backend.setup.err.log
%LOCALAPPDATA%\com.aisync.app\logs\backend.out.log
%LOCALAPPDATA%\com.aisync.app\logs\backend.err.log
```

开发态日志位置：

```text
.dev-logs/backend-dev.out.log
.dev-logs/backend-dev.err.log
```

诊断文件会记录：

- 当前版本
- app data / log / resource 路径
- Python / 后端源码 / 旧后端 exe 候选路径是否存在
- 安装版实际使用的后端 API 地址、端口状态和健康检查状态
- Tauri 管理的后端进程状态
- 关键日志文件是否存在

## 项目数据

默认项目根目录：

```text
~/.aisync/projects
```

桌面端通常由用户选择一个项目文件夹。项目初始化会创建基础结构，常见目录包括：

```text
chapters/
characters/
world/
plot/
.aisync/
```

`.aisync/` 用于保存对话历史、工具运行记录、向量索引等运行数据。

## LLM 预设

LLM 不再只有单一全局配置。前端设置页支持多个预设：

- 创建预设
- 复制已有预设
- 重命名预设
- 修改 provider / API Key / API Base / model / max tokens
- 自动获取模型列表
- 为主 Agent 配置可调用工具

支持的 provider：

- `anthropic`
- `openai`
- `custom`，用于 OpenAI 兼容 API

主要环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `anthropic` | 默认 LLM 提供商 |
| `LLM_API_KEY` | 空 | 直接写入 API Key |
| `LLM_API_KEY_ENV` | `ANTHROPIC_API_KEY` | 从哪个环境变量读取 API Key |
| `LLM_API_BASE` | 空 | OpenAI 兼容 API 地址 |
| `LLM_MODEL_NAME` | `claude-opus-4-7` | 默认模型名 |
| `LLM_MAX_TOKENS` | `16000` | 最大输出 token |
| `LLM_ENABLE_THINKING` | `true` | Anthropic thinking |
| `LLM_EFFORT` | `high` | thinking effort |
| `LLM_PROMPT_CACHE` | `true` | Anthropic prompt cache |
| `EMBEDDING_MODEL_NAME` | 空 | 向量检索使用的 embedding 模型名 |
| `VECTOR_BACKEND` | `local` | `local` 或 `chroma` |
| `CHROMA_PERSIST_PATH` | `.vectordb/chroma` | Chroma 存储目录 |
| `PROJECTS_ROOT` | `~/.aisync/projects` | 默认项目根目录 |

## Agent 对话

Agent 对话通过 WebSocket 工作：

```text
ws://127.0.0.1:8000/api/agent/current/ws?project_path=...
```

当前能力：

- 历史对话自动加载
- 默认打开上一次对话，没有历史时才新建
- Markdown 渲染
- 表格渲染
- 工具调用过程展示
- 工作状态指示
- 中断请求
- 对话记忆压缩

中断机制：

- 前端会通过 WebSocket 和独立 HTTP 请求双通道发起中断
- 后端会在 Agent 循环和流式输出回调中检查中断状态
- 如果正在执行工具，会等当前工具返回后停止后续步骤

## 工具系统

工具现在通过统一描述符暴露给 Agent、工具中心和侧边栏工具页。描述符包括：

- 工具名
- 中文描述
- 输入 schema
- UI schema
- 文件读写影响
- 默认 LLM 预设
- 前端呈现方式
- 是否提供工作区页面

当前主要工具：

| 工具 | 说明 | 主要影响 |
| --- | --- | --- |
| `write_chapter` | 写入章节草稿 | 写入 `chapters/**/*.md` |
| `edit_chapter` | 编辑已有章节 | 读写 `chapters/**/*.md` |
| `create_character` | 创建角色档案 | 写入 `characters/**` |
| `update_worldview` | 创建或更新世界观文档 | 读写 `world/**/*.md` |
| `outline_generate` | 生成/整理大纲 | 读写 `plot/outline.*` |
| `consistency_check` | 一致性检查 | 读取项目上下文，不直接写文件 |
| `search_project` | 搜索项目文件 | 读取文本文件 |

工具运行记录保存在：

```text
.aisync/tool_runs/
```

## 前端工作区

侧边栏主要入口：

- 基础信息：小说名、状态、目标章节、目标字数、完成统计
- 对话：主 Agent 对话
- 文件：文件树和 Markdown 编辑器
- 索引：向量索引状态、重建、搜索
- 工具中心：工具浏览、手动执行、AI 生成
- 设置：LLM 预设和 Agent 工具权限

工具也可以声明自己的工作区页面，例如：

- 大纲
- 章节
- 角色
- 世界观

这些页面是否出现在侧边栏，由工具描述符决定，不应依赖硬编码入口。

## 向量索引

向量接口：

- `GET /api/vector/status?project_path=...`
- `POST /api/vector/rebuild?project_path=...`
- `POST /api/vector/search`

当前支持：

- 本地索引后端
- 可选 Chroma 后端
- 按项目文件重建索引
- 在章节工具和索引页面中搜索相关片段

一致性检查等工具会使用项目索引，但数值和标题编号仍需要继续降噪优化。

## API 概览

常用 REST：

```text
GET    /health
GET    /api/projects/files
GET    /api/projects/overview
PUT    /api/projects/overview
GET    /api/conversations
POST   /api/conversations
GET    /api/conversations/{conversation_id}
DELETE /api/conversations/{conversation_id}
GET    /api/presets
POST   /api/presets
POST   /api/presets/models
POST   /api/presets/{preset_id}/copy
PUT    /api/presets/{preset_id}
GET    /api/tools
POST   /api/tools/{name}/execute
POST   /api/tools/{name}/invoke
GET    /api/tools/runs
POST   /api/vector/rebuild
GET    /api/vector/status
POST   /api/vector/search
POST   /api/agent/current/interrupt
```

WebSocket：

```text
ws://127.0.0.1:8000/api/agent/current/ws?project_path=...
```

发送：

```json
{"type":"user_message","content":"继续写下一章","preset_id":"default","enabled_tools":null}
```

```json
{"type":"interrupt","preset_id":"default"}
```

接收事件包括：

- `conversation`
- `memory_status`
- `agent_status`
- `stream`
- `stream_end`
- `tool_call_start`
- `tool_call_end`
- `tool_call_error`
- `tool_result`
- `agent_final`
- `error`

## 常用检查

前端构建：

```powershell
cd frontend
npm run build
```

Rust 检查：

```powershell
cd frontend/src-tauri
cargo check
```

后端语法检查：

```powershell
.\.conda\python.exe -m compileall backend\app
```

后端测试：

```powershell
.\.conda\python.exe -m pytest backend\tests
```

完整打包：

```powershell
cd frontend
npm run tauri build
```

## 当前注意事项

- `npm run tauri dev` 是开发模式，不会打包后端
- `npm run tauri build` 是发布模式，会打包前端和后端源码资源
- 安装版优先使用随包 `runtime/python/python.exe`，用户不需要安装 Python
- 自动 venv 只是随包 runtime 不可用时的回退路径
- 安装版侧栏的连接状态指 Agent WebSocket，不等同于后端是否启动
- 没选择项目时 Agent 会显示未选择或未连接，这是正常状态
- 中断不能强杀正在运行的工具内部逻辑，只会阻止后续 Agent 步骤
- 如果安装版空白或后端异常，优先查看 `%APPDATA%` 和 `%LOCALAPPDATA%` 下的诊断日志
