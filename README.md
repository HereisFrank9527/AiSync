# AiSync

AiSync 是一个面向长篇小说创作的本地 Web 工具。

它的核心目标是让小说项目保持“文件可控、工具可见、Agent 可协作”。项目内容保存在本机项目库或用户显式打开的本地目录中，前端提供对话、文件树、基础信息、章节/角色/世界观、大纲、向量索引、工具中心、工作流、提示词包和 LLM 预设配置。

## 当前形态

- React + Vite 前端
- Python FastAPI 后端
- FastAPI 可托管构建后的前端静态资源
- Agent 通过 LLM tool calling 读写项目文件
- 本地 Web / 局域网 Web 优先，不再维护 Tauri 桌面壳和安装包链路

更多工程细节见 [项目文档/技术细节.md](项目文档/技术细节.md)。

## 下载发布版

GitHub Release 提供 `AiSync-web-vX.Y.Z.zip`。该压缩包已经包含构建后的前端，普通使用者不需要安装 Node.js 或 npm。

运行要求：

- Windows
- Python 3.11 或更高版本
- 首次启动安装 Python 依赖时需要联网

解压后运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

首次启动会在解压目录创建 `.venv`，以后启动直接复用。默认访问地址为 `http://127.0.0.1:27631`。

## 快速开始

以下内容面向源码开发。开发机需要：

- Windows 当前支持最好
- Python 3.11
- Node.js 18+

安装依赖：

```powershell
.\.conda\python.exe -m pip install -e "backend[dev]"
cd frontend
npm install
```

启动开发模式：

```powershell
npm run dev
```

`npm run dev` 当前等价于局域网开发模式，会把后端和 Vite 前端绑定到 `0.0.0.0`，并在终端打印本机和局域网访问地址。当前没有登录/鉴权，只建议在可信局域网临时使用。

启动构建后的本地 Web：

```powershell
npm run web
```

`npm run web` 会先构建前端静态资源，再由 FastAPI 在 `http://127.0.0.1:27631` 托管前端和 API。

## 构建与发布

构建前端静态资源：

```powershell
npm run build
```

产物位置：

```text
frontend/dist/
```

启动构建产物：

```powershell
npm run web:start
```

检查版本并生成 GitHub Release 使用的预构建 Web 包：

```powershell
npm run release:check
npm run release:web
```

产物位置：

```text
.release/AiSync-web-v0.2.0.zip
.release/AiSync-web-v0.2.0.zip.sha256
```

发布包包含后端源码和 `frontend/dist/`，使用者不需要 npm。当前不再生成 Windows 安装包，也不内置 Python runtime。

## 项目数据

AiSync 支持程序管理的项目库。默认项目库位于：

```text
~/.aisync/projects/
```

推荐使用主界面或侧边栏的“新建 / 导入 / 导出 / 项目选择”。没有当前项目时，主界面会显示首次启动入口。项目库内项目可在侧边栏重命名或删除；删除操作限定在项目库内，避免误删外部目录。

项目初始化会创建常见目录：

```text
chapters/
characters/
world/
plot/
temp/
.aisync/
```

`.aisync/` 用于保存对话历史、工具运行记录、工作流记录、向量索引等运行数据。

## 主要能力

- Agent 对话：历史加载、Markdown/表格渲染、工具调用展示、工作状态、中断、记忆压缩
- 文件工作区：文件树和 Markdown 编辑
- 基础信息：小说名、状态、目标章节、目标字数、完成统计
- 章节/角色/世界观/大纲：面向小说对象的管理页面
- 工作流：章节草稿、草稿转正式章节、步骤级提示词包和模型预设
- Agent 项目规则：根目录 `AGENT.md` 统一维护长期工作习惯和当前文风，Agent 可通过差异预览提议修改
- 提示词管理：管理需要跨项目复用或随时切换的文风、写作和检查提示词包
- 工具中心：工具浏览、手动执行、AI 生成、工具级 LLM 路由
- 向量索引：项目文件索引、重建、搜索、Agent 上下文注入
- LLM 预设：多预设、复制、重命名、模型列表获取、上下文窗口和超时设置
- 检查更新：读取 GitHub Releases latest 并打开下载/发布页

## 常用检查

前端构建：

```powershell
npm run build
```

后端语法检查：

```powershell
.\.conda\python.exe -m compileall backend\app
```

后端测试：

```powershell
.\.conda\python.exe -m pytest backend\tests
```

发布元数据检查：

```powershell
npm run release:check
```

清理旧构建产物：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/clean_build_artifacts.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File scripts/clean_build_artifacts.ps1
```

## 当前注意事项

- 仓库根目录 `npm run dev` 是局域网开发模式，默认后端端口 `27631`、Vite 端口 `1420`
- 仓库根目录 `npm run build` 只构建前端静态资源，不生成安装包
- 仓库根目录 `npm run web` 是本地 Web 模式，默认端口 `27631`
- 仓库根目录 `npm run release:web` 生成不依赖 npm 的用户发布 ZIP；构建发布包的开发机仍需要 npm
- Web 模式优先使用项目库导入/导出，不建议让用户手填项目路径
- LAN dev 当前没有鉴权，只适合可信网络临时使用
- 侧栏连接状态指 Agent WebSocket，不等同于 LLM 服务是否可用
- 没选择项目时 Agent 会显示未选择或未连接，这是正常状态
- 中断不能强杀正在运行的工具内部逻辑，只会阻止后续 Agent 步骤或取消可取消的模型请求

## 许可说明

AiSync 采用 [PolyForm Noncommercial License 1.0.0](LICENSE)。

仓库代码和产物可用于非商用的个人学习、研究、测试和评估。商用、付费分发、二次发布、转售、嵌入商业产品或服务、作为托管/代运营服务提供，均需先取得明确书面许可。

第三方依赖仍遵循其各自许可证。
