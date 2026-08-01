import type { ToolWorkspaceView, ViewId } from "../../types";
import "./Sidebar.css";

interface SidebarProps {
  projectName: string;
  projectPath: string;
  projects: Array<{ id?: string; name: string; path: string }>;
  projectsLoading: boolean;
  projectError: string | null;
  connected: boolean;
  activeView: ViewId;
  toolViews: ToolWorkspaceView[];
  onViewChange: (view: ViewId) => void;
  onSelectFolder: () => void;
  onSetProjectPath: (path: string) => void;
  onSelectProject: (path: string) => void;
  onCreateProject: () => void;
  onImportProject: (file: File) => void;
  onExportProject: () => void;
  onRenameProject: () => void;
  onDeleteProject: () => void;
  onRefreshProjects: () => void;
}

const PRIMARY_NAV_ITEMS: { id: ViewId; label: string }[] = [
  { id: "overview", label: "基础" },
  { id: "chat", label: "对话" },
  { id: "files", label: "文件" },
  { id: "vector", label: "索引" },
  { id: "workflows", label: "工作流" },
  { id: "tools", label: "工具" },
  { id: "settings", label: "设置" },
];

export default function Sidebar({
  projectName,
  projectPath,
  projects,
  projectsLoading,
  projectError,
  connected,
  activeView,
  toolViews,
  onViewChange,
  onSelectFolder,
  onSetProjectPath,
  onSelectProject,
  onCreateProject,
  onImportProject,
  onExportProject,
  onRenameProject,
  onDeleteProject,
  onRefreshProjects,
}: SidebarProps) {
  const statusKind = !projectPath ? "idle" : connected ? "connected" : "disconnected";
  const statusLabel = !projectPath ? "未选择项目" : connected ? "已连接" : "未连接";
  const projectInLibrary = projects.some((item) => item.path === projectPath);

  const projectOptions = (
    <>
      <option value="">{projectsLoading ? "加载项目中..." : "选择项目"}</option>
      {projects.map((item) => (
        <option key={item.path} value={item.path}>
          {item.name}
        </option>
      ))}
    </>
  );

  return (
    <>
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>AiSync</h1>
        </div>

        <div
          className={`sidebar-status ${statusKind}`}
          title="这里显示对话 Agent 的 WebSocket 状态；后端启动状态会在启动页和诊断日志中显示。"
        >
          <span className="dot" />
          Agent {statusLabel}
        </div>

        <div className="sidebar-divider" />

        <nav className="sidebar-nav">
          {PRIMARY_NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={`sidebar-item${activeView === item.id ? " active" : ""}`}
              onClick={() => onViewChange(item.id)}
              type="button"
            >
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        {toolViews.length > 0 && (
          <>
            <div className="sidebar-section-label">创作工具页</div>
            <nav className="sidebar-nav">
              {toolViews.map((item) => (
                <button
                  key={item.view_id}
                  className={`sidebar-item sidebar-item--tool${activeView === item.view_id ? " active" : ""}`}
                  onClick={() => onViewChange(item.view_id as ViewId)}
                  type="button"
                >
                  <span>{item.label}</span>
                  <em className="sidebar-item-marker">{item.marker}</em>
                </button>
              ))}
            </nav>
          </>
        )}

        <div className="sidebar-divider" />

        <div className="sidebar-project">
          <div className="sidebar-project-heading">
            <label>项目库</label>
            <button className="sidebar-text-action" onClick={onRefreshProjects} type="button">
              刷新
            </button>
          </div>
          <div className="sidebar-project-name">{projectName || "未选择"}</div>
          <div className="sidebar-project-path">{projectPath || "请选择项目文件夹"}</div>
          {projectError && <div className="sidebar-project-error">{projectError}</div>}
          <select
            className="sidebar-project-select"
            value={projectPath}
            onChange={(event) => onSelectProject(event.target.value)}
            disabled={projectsLoading}
          >
            {projectOptions}
          </select>
          <div className="sidebar-project-actions">
            <button className="btn-secondary" onClick={onCreateProject} type="button">
              新建
            </button>
            <label className="btn-secondary sidebar-import-button">
              导入
              <input
                type="file"
                accept=".zip,.aisync.zip,application/zip"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) onImportProject(file);
                }}
              />
            </label>
            <button className="btn-secondary" onClick={onExportProject} type="button" disabled={!projectPath}>
              导出
            </button>
          </div>
          <div className="sidebar-project-actions sidebar-project-actions--secondary">
            <button className="btn-secondary" onClick={onRenameProject} type="button" disabled={!projectPath}>
              重命名
            </button>
            <button className="btn-secondary" onClick={onDeleteProject} type="button" disabled={!projectInLibrary}>
              删除
            </button>
          </div>
          <button className="btn-secondary sidebar-project-action" onClick={onSelectFolder} type="button">
            打开外部文件夹
          </button>
          <form
            className="sidebar-project-path-form"
            onSubmit={(event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              const value = String(data.get("projectPath") ?? "");
              onSetProjectPath(value);
            }}
          >
            <input name="projectPath" type="text" defaultValue={projectPath} placeholder="或粘贴项目绝对路径" />
            <button className="btn-secondary" type="submit">
              打开
            </button>
          </form>
        </div>
      </aside>

      <header className="mobile-app-bar">
        <div className="mobile-app-row">
          <div className="mobile-brand">
            <strong>AiSync</strong>
            <span className={`mobile-status ${statusKind}`}>
              <i />
              Agent {statusLabel}
            </span>
          </div>
          <button className="mobile-refresh" onClick={onRefreshProjects} type="button">
            刷新
          </button>
        </div>
        <div className="mobile-project-row">
          <span title={projectPath}>{projectName || "未选择项目"}</span>
          <select
            value={projectPath}
            onChange={(event) => onSelectProject(event.target.value)}
            disabled={projectsLoading}
            aria-label="选择项目"
          >
            {projectOptions}
          </select>
        </div>
        {projectError && <div className="mobile-project-error">{projectError}</div>}
        {toolViews.length > 0 && (
          <nav className="mobile-tool-rail" aria-label="创作工具">
            {toolViews.map((item) => (
              <button
                key={item.view_id}
                className={activeView === item.view_id ? "active" : ""}
                onClick={() => onViewChange(item.view_id as ViewId)}
                type="button"
              >
                <span>{item.label}</span>
                <em>{item.marker}</em>
              </button>
            ))}
          </nav>
        )}
      </header>

      <nav className="mobile-bottom-nav" aria-label="主导航">
        {PRIMARY_NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`mobile-bottom-item${activeView === item.id ? " active" : ""}`}
            onClick={() => onViewChange(item.id)}
            type="button"
          >
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </>
  );
}
