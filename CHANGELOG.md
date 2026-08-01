# Changelog

## 0.2.0 - 2026-08-01

AiSync 从 Tauri 桌面应用切换为本地 Web / 局域网 Web 架构。

主要变化：

- FastAPI 同时提供 API、Agent WebSocket 和构建后的 React 页面。
- 增加程序管理的项目库，以及项目新建、导入、导出、重命名和删除能力。
- 重构 Agent 多轮工具循环、运行恢复、流式草稿、文件改动包和人工确认链路。
- 完善章节、角色、世界观、大纲、伏笔、工作流、提示词包和项目规则管理。
- 增加工具级模型路由、上下文窗口、Thinking、Tavily 搜索和一致性检查治理。
- 移除 Tauri、NSIS、内置 Python runtime 和 Windows 安装包链路。
- GitHub Release 改为提供预构建 Web ZIP；使用者需要 Python 3.11，但不需要 npm。

已知限制：

- Web ZIP 首次启动需要联网安装 Python 依赖。
- 局域网模式尚无登录和鉴权，不应直接暴露到公网。
- 当前不提供 Windows 安装器或完全免 Python 的独立运行包。
