import type { ViewId } from "../../types";
import "./Sidebar.css";

interface SidebarProps {
  projectName: string;
  projectPath: string;
  connected: boolean;
  activeView: ViewId;
  onViewChange: (view: ViewId) => void;
  onSelectFolder: () => void;
}

const NAV_ITEMS: { id: ViewId; label: string }[] = [
  { id: "chat", label: "对话" },
  { id: "files", label: "文件" },
  { id: "tools", label: "工具" },
  { id: "settings", label: "设置" },
];

export default function Sidebar({
  projectName,
  projectPath,
  connected,
  activeView,
  onViewChange,
  onSelectFolder,
}: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>AiSync</h1>
      </div>

      <div className={`sidebar-status${connected ? " connected" : ""}`}>
        <span className="dot" />
        {connected ? "已连接" : "未连接"}
      </div>

      <div className="sidebar-divider" />

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={`sidebar-item${activeView === item.id ? " active" : ""}`}
            onClick={() => onViewChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

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
