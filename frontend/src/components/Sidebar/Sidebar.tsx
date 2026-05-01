import type { ViewId } from "../../types";
import "./Sidebar.css";

interface SidebarProps {
  projectId: string;
  onProjectIdChange: (id: string) => void;
  connected: boolean;
  activeView: ViewId;
  onViewChange: (view: ViewId) => void;
}

const NAV_ITEMS: { id: ViewId; label: string; icon: string }[] = [
  { id: "chat", label: "对话", icon: "💬" },
  { id: "tools", label: "工具", icon: "🔧" },
  { id: "settings", label: "设置", icon: "⚙️" },
];

export default function Sidebar({
  projectId,
  onProjectIdChange,
  connected,
  activeView,
  onViewChange,
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
            <span className="icon">{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>

      <div className="sidebar-divider" />

      <div className="sidebar-project">
        <label htmlFor="project-id">项目 ID</label>
        <input
          id="project-id"
          value={projectId}
          onChange={(e) => onProjectIdChange(e.target.value)}
        />
      </div>
    </aside>
  );
}
