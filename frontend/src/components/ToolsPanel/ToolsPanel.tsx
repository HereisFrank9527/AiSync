import type { ToolDescriptor } from "../../types";
import "./ToolsPanel.css";

interface ToolsPanelProps {
  tools: ToolDescriptor[];
  loading: boolean;
  error: string;
  onSelect: (tool: ToolDescriptor) => void;
}

export default function ToolsPanel({ tools, loading, error, onSelect }: ToolsPanelProps) {
  return (
    <section className="tools-panel">
      <header className="tools-header">
        <h2>工具</h2>
        <p>选择工具后可手动填参直接执行，也可交给 AI 补全执行。</p>
      </header>

      {loading && <p className="tools-muted">加载工具中…</p>}
      {error && <p className="tools-error">{error}</p>}
      {!loading && !error && tools.length === 0 && <p className="tools-muted">暂无工具</p>}

      <div className="tools-grid">
        {tools.map((tool) => (
          <button className="tool-card" key={tool.name} onClick={() => onSelect(tool)}>
            <span>{tool.name}</span>
            <p>{tool.description}</p>
          </button>
        ))}
      </div>
    </section>
  );
}
