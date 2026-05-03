运行python前请切换到虚拟环境：conda activate ./.conda
每次更新代码请更新md文件

## 项目状态（2026-05-03）

### Phase 1.5 — 已修复
WebSocket 重连、事件截断、API Key 保存、预设缓存失效、Anthropic await、
presets.json 路径、项目选择方式、SettingsPanel 错误颜色、颜色对比度、
预设删除确认、Tauri dialog 权限 + 版本对齐。

遗留（非阻塞）：Error Boundary、Agent 迭代上限、向量存储空实现、暗色模式、硬编码像素。

### Phase 2 — 基础版完成，UI 持续打磨
- 工具 UI：ToolsPanel + ToolDrawer + SchemaForm + `/api/tools`
- 写作工具：write_chapter、edit_chapter、create_character、update_worldview
- Markdown 编辑器：CodeMirror 6，lazy 加载
- 对话界面：ChatPanel + 角色区分（用户蓝色右对齐，Agent 左对齐）+ 对话列表可折叠
- **Agent 流式输出**：LLM 响应通过 WebSocket 实时流式推送到前端（Anthropic + OpenAI 双客户端支持）
- 项目选择：Tauri 原生目录选择 + 自动生成标准骨架（`POST /api/projects/init`）
- **文件树**：递归树形，目录可展开/折叠，目录在前文件在后，自动隐藏 `.aisync`/`.vectordb`
- 对话历史：`.aisync/conversations/` CRUD，首条消息自动生成标题，启动时优先恢复当前项目上次激活的对话

### 启动方式
- 后端: cd backend && conda activate ./.conda && uvicorn app.main:app --reload
- 前端: cd frontend && npm run dev
- Tauri 桌面端: cd frontend && npm run tauri dev
- 预设: `~/.aisync/presets.json`
- 对话: 项目目录 `.aisync/conversations/*.json`