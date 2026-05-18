# AiSync

AiSync 是一个面向长篇小说创作的本地桌面工具。

它的核心目标是让小说项目保持“文件可控、工具可见、Agent 可协作”。项目内容保存在用户选择的本地文件夹中，前端提供对话、文件树、基础信息、章节/角色/世界观、大纲、向量索引、工具中心和 LLM 预设配置。

## 当前形态

- Tauri 2 桌面壳
- React + Vite 前端
- Python FastAPI 后端
- Agent 通过 LLM tool calling 读写项目文件
- 安装版随包携带轻量 Python runtime，用户不需要手动安装 Python

更多工程细节见 [技术细节.md](技术细节.md)。

## 快速开始

开发机需要：

- Windows 当前支持最好
- Python 3.11
- Node.js 18+
- Rust toolchain
- Tauri 2 依赖

安装依赖：

```powershell
.\.conda\python.exe -m pip install -e "backend[dev,package]"
cd frontend
npm install
```

启动桌面开发模式：

```powershell
npm run dev
```

开发态不会打包 Python 后端，会直接从源码启动后端并启动 Vite 前端。

## 打包发布

应用版本号的人工修改点：

```text
frontend/src-tauri/tauri.conf.json
```

修改：

```json
"version": "0.1.8"
```

每次准备安装包或 GitHub Release 都必须递增版本号。同版本覆盖安装可能被 Windows/NSIS 视为维护安装，不能可靠验证新二进制是否已替换。

构建安装包：

```powershell
npm run build
```

产物位置：

```text
frontend/src-tauri/target/release/bundle/nsis/
```

安装版默认优先使用随包 Python 启动后端，并自动选择本地可用端口。安装器会禁止降级安装，并在安装前清理安装目录内旧版主程序、卸载器、后端源码和 runtime 残留；用户项目与 `%APPDATA%\com.aisync.app` 数据不受影响。

## 项目数据

桌面端通常由用户选择一个项目文件夹。项目初始化会创建常见目录：

```text
chapters/
characters/
world/
plot/
.aisync/
```

`.aisync/` 用于保存对话历史、工具运行记录、向量索引等运行数据。

## 主要能力

- Agent 对话：历史加载、Markdown/表格渲染、工具调用展示、工作状态、中断、记忆压缩
- 文件工作区：文件树和 Markdown 编辑
- 基础信息：小说名、状态、目标章节、目标字数、完成统计
- 工具中心：工具浏览、手动执行、AI 生成
- 向量索引：项目文件索引、重建、搜索、Agent 上下文注入
- LLM 预设：多预设、复制、重命名、模型列表获取、主 Agent 工具权限
- 检查更新：读取 GitHub Releases latest 并打开下载/发布页

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

后端测试：

```powershell
.\.conda\python.exe -m pytest backend\tests
```

完整打包：

```powershell
npm run build
```

清理旧构建产物：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/clean_build_artifacts.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File scripts/clean_build_artifacts.ps1
```

## 当前注意事项

- 仓库根目录 `npm run build` 是发布模式，会打包前端、后端源码资源和随包 Python runtime
- `cd frontend && npm run build` 只构建前端网页资源，不会生成安装包
- 仓库根目录 `npm run dev` 是开发模式，不会打包后端
- 安装版侧栏的连接状态指 Agent WebSocket，不等同于后端是否启动
- 没选择项目时 Agent 会显示未选择或未连接，这是正常状态
- 中断不能强杀正在运行的工具内部逻辑，只会阻止后续 Agent 步骤
- 如果安装版空白或后端异常，优先查看 `%APPDATA%` 和 `%LOCALAPPDATA%` 下的诊断日志，路径见 [技术细节.md](技术细节.md)

## 许可说明

AiSync 不是开源许可下的自由软件。仓库代码和产物默认仅供内部评估、个人测试和已获授权的使用场景。

如需商用、分发、二次发布或嵌入到其他产品，请先取得明确书面许可。未经许可，不授予商用权利。
