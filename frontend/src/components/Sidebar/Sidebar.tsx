import type { ToolWorkspaceView, ViewId } from "../../types";
import "./Sidebar.css";

interface SidebarProps {
  projectName: string;
  projectPath: string;
  connected: boolean;
  activeView: ViewId;
  toolViews: ToolWorkspaceView[];
  onViewChange: (view: ViewId) => void;
  onSelectFolder: () => void;
}

const PRIMARY_NAV_ITEMS: { id: ViewId; label: string }[] = [
  { id: "overview", label: "基础信息" },
  { id: "chat", label: "对话" },
  { id: "files", label: "文件" },
  { id: "vector", label: "索引" },
  { id: "workflows", label: "工作流" },
  { id: "tools", label: "工具中心" },
  { id: "settings", label: "设置" },
];

export default function Sidebar({
  projectName,
  projectPath,
  connected,
  activeView,
  toolViews,
  onViewChange,
  onSelectFolder,
}: SidebarProps) {
  const statusKind = !projectPath ? "idle" : connected ? "connected" : "disconnected";
  const statusLabel = !projectPath ? "未选择项目" : connected ? "Agent 已连接" : "Agent 未连接";

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>AiSync</h1>
      </div>

      <div
        className={`sidebar-status ${statusKind}`}
        title="这里显示对话 Agent 的 WebSocket 状态；后端启动状态会在启动页和诊断日志中显示。"
      >
        <span className="dot" />
        {statusLabel}
      </div>

      <div className="sidebar-divider" />

      <nav className="sidebar-nav">
        {PRIMARY_NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`sidebar-item${activeView === item.id ? " active" : ""}`}
            onClick={() => onViewChange(item.id)}
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
        <label>当前项目</label>
        <div className="sidebar-project-name">{projectName || "未选择"}</div>
        <div className="sidebar-project-path">{projectPath || "请选择项目文件夹"}</div>
        <button className="btn-secondary sidebar-project-action" onClick={onSelectFolder}>
          选择文件夹
        </button>
      </div>
    </aside>
  );
}
