运行python前请切换到虚拟环境：conda activate ./.conda
每次更新代码请更新md文件

## 项目状态（2026-05-01）

### Phase 1 — 已完成
后端：FastAPI + WebSocket、Agent 循环、LLM 适配器（Anthropic/OpenAI/自定义）、工具基类+注册、
项目文件系统（asyncio.Lock）、预设系统（JSON 文件存储）
前端：React + Tauri 壳、Notion 风格 CSS 变量、Sidebar/ChatPanel/SettingsPanel 三视图布局、
usePresets hook、预设管理面板、WebSocket 通信

### Phase 1.5 — 待修复（高优先级）
- 预设 loading/error 状态未在 UI 展示
- SettingsPanel 错误消息始终绿色
- --color-text-tertiary 对比度不足

已修复：WebSocket 重连/错误处理、事件列表截断、应用内 API Key 保存、预设更新后 Agent 缓存失效、Anthropic 流式响应 await 错误、.gitignore 覆盖依赖/构建/运行产物。

### Phase 2 — 未开始

### 启动方式
- 后端: cd backend && uvicorn app.main:app --reload
- 前端: cd frontend && npm run dev
- 预设文件: 项目根目录 presets.json（自定义预设可直接保存 API Key；留空时才使用 api_key_env 环境变量）