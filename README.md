# AiSync — AI 辅助长篇小说创作平台

Tauri 2 桌面应用 + FastAPI 后端 + React 前端。后端 Agent 通过 LLM tool calling 循环自动读写项目文件，前端通过 WebSocket 实时展示 Agent 事件。

## 项目结构

```
AiSync/
├── backend/                  # Python FastAPI 后端
│   ├── app/
│   │   ├── agent.py          # MasterAgent — agentic loop 核心
│   │   ├── main.py           # FastAPI 应用入口
│   │   ├── api/
│   │   │   ├── agent.py      # /api/agent — WebSocket + REST 路由
│   │   │   ├── config.py     # /api/config/llm — LLM 配置 GET/PUT
│   │   │   ├── projects.py   # /api/projects — 项目文件 CRUD
│   │   │   └── websocket.py  # ConnectionManager
│   │   ├── core/
│   │   │   └── config.py     # Settings (pydantic-settings)
│   │   ├── llm/
│   │   │   ├── types.py      # ChatRequest / ChatResponse / LLMClient Protocol
│   │   │   ├── factory.py    # create_llm_client() 工厂
│   │   │   ├── anthropic_client.py  # Anthropic Claude 后端
│   │   │   └── openai_client.py     # OpenAI 兼容后端 (OpenAI/DeepSeek/本地)
│   │   ├── tools/
│   │   │   ├── base.py       # BaseTool / ToolResult / ToolCall
│   │   │   ├── registry.py   # ToolRegistry (自动发现)
│   │   │   ├── factory.py    # create_tool_registry()
│   │   │   ├── write_chapter.py   # 写章节工具
│   │   │   └── search_project.py  # 搜索项目文件工具
│   │   ├── projects/
│   │   │   └── context.py    # ProjectContext — 安全的项目文件读写
│   │   └── vector/
│   │       └── store.py      # ProjectVectorStore (当前为空壳)
│   └── pyproject.toml
├── frontend/                 # React + Vite + Tauri 2
│   ├── src/
│   │   ├── App.tsx           # 主界面（含 LLM 设置面板入口）
│   │   ├── main.tsx          # React 入口
│   │   ├── components/
│   │   │   └── SettingsPanel.tsx  # LLM 运行时配置面板
│   │   ├── hooks/
│   │   │   └── useAgentSocket.ts  # WebSocket hook
│   │   └── style.css
│   ├── src-tauri/            # Tauri 2 Rust 壳
│   │   ├── src/main.rs
│   │   ├── tauri.conf.json
│   │   └── Cargo.toml
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
└── projects/                 # 小说项目数据目录 (运行时生成)
```

## 环境要求

- Python >= 3.11 (推荐 conda)
- Node.js >= 18
- Rust (Tauri 2 编译需要)

## 快速开始

### 1. 后端

```bash
cd backend

# 创建 .env 文件
cat > .env << 'EOF'
# --- 选择 LLM 提供商 ---
# 方案 A: Anthropic Claude (默认)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxx
LLM_MODEL_NAME=claude-opus-4-7

# 方案 B: OpenAI
# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-xxxxx
# LLM_API_KEY_ENV=OPENAI_API_KEY
# LLM_MODEL_NAME=gpt-4o

# 方案 C: OpenAI 兼容 API (DeepSeek / 本地 Ollama 等)
# LLM_PROVIDER=custom
# LLM_API_KEY_ENV=DEEPSEEK_API_KEY
# DEEPSEEK_API_KEY=sk-xxxxx
# LLM_API_BASE=https://api.deepseek.com/v1
# LLM_MODEL_NAME=deepseek-chat
EOF

# 安装依赖 (conda 环境)
pip install -e ".[dev]"

# 启动后端
uvicorn app.main:app --reload --port 8000
```

后端启动后：
- 健康检查: http://localhost:8000/health
- API 文档: http://localhost:8000/docs
- WebSocket: ws://localhost:8000/api/agent/{project_id}/ws

### 2. 前端 (纯 Web 开发模式)

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:1420 即可使用。

### 3. 前端 (Tauri 桌面应用模式)

```bash
cd frontend
npm run tauri dev
```

## 打包发布

当前桌面端采用 `Tauri + Python backend sidecar` 的方式打包。Windows 下推荐直接用现成脚本：

```bash
# 1. 构建 backend 可执行文件
powershell -ExecutionPolicy Bypass -File scripts/build_backend.ps1

# 2. 构建完整桌面安装包
cd frontend
npm run tauri build
```

打包产物会生成在：
- `backend/dist/aisync-backend.exe`
- `frontend/src-tauri/target/release/bundle/msi/`
- `frontend/src-tauri/target/release/bundle/nsis/`

说明：
- `scripts/build_backend.ps1` 会先用 PyInstaller 把 Python 后端打成单文件 exe
- `npm run tauri build` 会自动先执行后端构建，再生成 Tauri 安装包
- 当前 Windows 首次打包可能会下载 WiX / NSIS 组件，属于正常现象

## 配置说明

所有配置通过 `backend/.env` 文件或环境变量设置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_PROVIDER` | `anthropic` | LLM 提供商: `anthropic` / `openai` / `custom` |
| `LLM_API_KEY_ENV` | `ANTHROPIC_API_KEY` | 存放 API Key 的环境变量名 |
| `LLM_API_BASE` | (空) | 自定义 API 地址，用于 OpenAI 兼容服务 |
| `LLM_MODEL_NAME` | `claude-opus-4-7` | 模型名称 |
| `LLM_MAX_TOKENS` | `16000` | 最大输出 token 数 |
| `LLM_ENABLE_THINKING` | `true` | 启用 Claude 思考模式 (仅 Anthropic) |
| `LLM_EFFORT` | `high` | 思考力度: `low`/`medium`/`high`/`xhigh`/`max` |
| `LLM_PROMPT_CACHE` | `true` | 启用 Anthropic prompt cache |
| `PROJECTS_ROOT` | `./projects` | 小说项目数据存储路径 |
| `CORS_ORIGINS` | `["http://localhost:1420", "http://localhost:5173"]` | CORS 允许的源 |

所有 LLM 配置也可以在前端侧边栏的「LLM 设置」面板中运行时修改，无需重启后端。修改 provider / API Key / API Base 时会自动重建所有活跃 Agent 的 LLM 客户端。

## Agent 工作流

1. 用户通过前端发送创作指令
2. WebSocket 将消息传递给 `MasterAgent.run()`
3. Agent 构造 LLM 请求，附带可用工具列表
4. LLM 返回文本或 tool_call
5. 如果有 tool_call，Agent 执行工具并将结果推送到前端，然后将 tool_result 回传给 LLM 继续循环
6. 循环直到 LLM 返回纯文本（最终回答）

### 当前可用工具

工具现在以统一描述符暴露给 Agent 和前端工具中心：包含参数 schema、默认 Agent、可能读取/修改/生成的文件，以及前端呈现类型。每次手动执行或 AI 生成都会写入 `.aisync/tool_runs/{run_id}.json`，方便前端展示最近运行记录。

| 工具 | 说明 | 文件影响 | 呈现 |
|------|------|----------|------|
| `write_chapter` | 写入/覆盖章节 Markdown 文件 | 修改 `chapters/**/*.md` | `stream:editor` |
| `edit_chapter` | 替换、追加或前置编辑已有章节 | 读取/修改 `chapters/**/*.md` | `stream:editor` |
| `create_character` | 创建角色档案 Markdown 与 YAML 元数据 | 生成 `characters/{slug}/profile.md`、`characters/{slug}/profile.yaml` | `card:character` |
| `update_worldview` | 创建或更新世界观 Markdown 文件 | 读取/修改/生成 `world/**/*.md` | `document:worldview` |
| `search_project` | 按关键词搜索项目中的文本文件 | 读取 `*.md/*.txt/*.yaml/*.yml/*.json` | `list:search_results` |

前端「工具中心」支持两种入口：
- **直接执行**：用户填写表单后调用工具本体，立即读写项目文件。
- **AI 生成**：根据工具默认提示词和当前预设交给 Agent 生成，再由 Agent 自行决定如何调用工具。

## API 端点

### REST

- `GET /health` — 健康检查
- `POST /api/projects` — 创建项目
- `GET /api/projects/{id}/files` — 列出项目文件
- `GET /api/projects/{id}/files/{path}` — 读取文件
- `PUT /api/projects/{id}/files/{path}` — 写入文件
- `GET /api/config/llm` — 获取当前 LLM 配置
- `PUT /api/config/llm` — 更新 LLM 配置（支持部分更新，自动重建 Agent 客户端）
- `GET /api/tools` — 获取工具描述符列表（schema、默认 Agent、文件影响、呈现类型）
- `POST /api/tools/{name}/execute` — 直接执行工具并写入 `.aisync/tool_runs/` 记录
- `POST /api/tools/{name}/invoke` — 将工具提示词交给 Agent 执行并写入运行记录
- `GET /api/tools/runs` — 获取当前项目最近工具运行记录
- `GET /api/tools/runs/{run_id}` — 获取单次工具运行详情
- `POST /api/agent/{id}/run` — 同步运行 Agent
- `POST /api/agent/{id}/interrupt` — 中断 Agent

### WebSocket

- `ws://localhost:8000/api/agent/{id}/ws`
  - 发送: `{"type": "user_message", "content": "..."}`
  - 发送: `{"type": "interrupt"}`
  - 接收: `{"type": "tool_result", "content": "...", "ui_hint": {...}}`
  - 接收: `{"type": "agent_final", "content": "..."}`
